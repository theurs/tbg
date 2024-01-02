#!/usr/bin/env python3
# https://ai.google.dev/
# pip install Proxy-List-Scrapper


import concurrent.futures
import base64
import pickle
import random
import threading
import time
import requests
from Proxy_List_Scrapper import Scrapper

import cfg
import my_log


# Blocking chats to avoid spoiling the history
# {id:lock}
LOCKS = {}

# Do not accept more requests than this, this is a Telegram bot limitation, not used in this module
MAX_REQUEST = 14000

# Maximum chat history size (Google 32k limit?)
MAX_CHAT_SIZE = 25000


# Dialog storage {id:list(mem)}
CHATS = {}


# If no proxies are specified in the config, then we first try to work directly
# and if that doesn't work, we start looking for free proxies using
# a constantly running daemon
PROXY_POOL = []
PROXY_POLL_SPEED = {}
PROXY_POOL_REMOVED = []

# искать и добавлять прокси пока не найдется хотя бы 10 проксей
MAX_PROXY_POOL = 10
# начинать повторный поиск если осталось всего 5 проксей
MAX_PROXY_POOL_LOW_MARGIN = 5

PROXY_POOL_DB_FILE = 'db/gemini_proxy_pool.pkl'
PROXY_POLL_SPEED_DB_FILE = 'db/gemini_proxy_pool_speed.pkl'
# PROXY_POOL_REMOVED_DB_FILE = 'db/gemini_proxy_pool_removed.pkl'
SAVE_LOCK = threading.Lock()
POOL_MAX_WORKERS = 50


def img2txt(data_: bytes, prompt: str = "What is in the image, in detail?") -> str:
    """
    Generates a textual description of an image based on its contents.

    Args:
        data_: The image data as bytes.
        prompt: The prompt to provide for generating the description. Defaults to "Что на картинке, подробно?".

    Returns:
        A textual description of the image.

    Raises:
        None.
    """
    global PROXY_POOL

    try:
        img_data = base64.b64encode(data_).decode("utf-8")
        data = {
            "contents": [
                {
                "parts": [
                    {"text": prompt},
                    {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": img_data
                    }
                    }
                ]
                }
            ]
            }

        result = ''
        keys = cfg.gemini_keys[:]
        random.shuffle(keys)

        proxies = PROXY_POOL[:]
        random.shuffle(proxies)

        for api_key in keys:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent?key={api_key}"

            if proxies:
                sort_proxies_by_speed(proxies)
                for proxy in proxies:
                    start_time = time.time()
                    session = requests.Session()
                    session.proxies = {"http": proxy, "https": proxy}
                    try:
                        response = session.post(url, json=data, timeout=60).json()
                        result = response['candidates'][0]['content']['parts'][0]['text']
                        if result:
                            end_time = time.time()
                            total_time = end_time - start_time
                            if total_time > 45:
                                remove_proxy(proxy)
                            # не участвовать в рейтинге скорости прокси так как ответы всегда заметно более долгие
                            # else:
                            #     PROXY_POLL_SPEED[proxy] = total_time
                            break
                    except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as error:
                        remove_proxy(proxy)
                        continue
            else:
                try:
                    response = requests.post(url, json=data, timeout=60).json()
                    try:
                        result = response['candidates'][0]['content']['parts'][0]['text']
                    except AttributeError:
                        my_log.log2(f'img2txt:{api_key} {str(response)} {response.text}')
                except Exception as error:
                    my_log.log2(f'img2txt:{error}')
            if result:
                break
        return result.strip()
    except Exception as unknown_error:
        my_log.log2(f'my_gemini:img2txt:{unknown_error}')
        return ''


def update_mem(query: str, resp: str, mem) -> list:
    """
    Update the memory with the given query and response.

    Parameters:
        query (str): The input query.
        resp (str): The response to the query.
        mem: The memory object to update, if str than mem is a chat_id

    Returns:
        list: The updated memory object.
    """
    chat_id = ''
    if isinstance(mem, str): # if mem - chat_id
        chat_id = mem
        if mem not in CHATS:
            CHATS[mem] = []
        mem = CHATS[mem]

    if resp:
        mem.append({"role": "user", "parts": [{"text": query}]})
        mem.append({"role": "model", "parts": [{"text": resp}]})
        size = 0
        for x in mem:
            text = x['parts'][0]['text']
            size += len(text)
        while size > MAX_CHAT_SIZE:
            mem = mem[2:]
            size = 0
            for x in mem:
                text = x['parts'][0]['text']
                size += len(text)
        if chat_id:
            CHATS[chat_id] = mem
        return mem


def ai(q: str, mem = [], temperature: float = 0.1, proxy_str: str = '') -> str:
    """
    Generate the response from an AI model based on a user query.

    Args:
        q (str): The user query.
        mem (list, optional): The list of previous queries and responses. Defaults to an empty list.
        temperature (float, optional): The temperature parameter for generating the response. 
            Should be between 0.0 and 1.0. Defaults to 0.1.
        proxy_str (str, optional): The proxy server to use for the request. Defaults to an empty string.

    Returns:
        str: The generated response from the AI model.
    """
    global PROXY_POOL

    mem_ = {"contents": mem + [{"role": "user", "parts": [{"text": q}]}],
            "safetySettings": [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE"
                }
            ],
            "generationConfig": {
                # "stopSequences": [
                #     "Title"
                # ],
                "temperature": temperature,
                # "maxOutputTokens": 8000,
                # "topP": 0.8,
                # "topK": 10
                }
            }

    keys = cfg.gemini_keys[:]
    random.shuffle(keys)
    result = ''

    if proxy_str:
        proxies = [proxy_str, ]
    else:
        proxies = PROXY_POOL[:]
        # random.shuffle(proxies)

    proxy = ''
    try:
        for key in keys:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=" + key

            if proxies:
                sort_proxies_by_speed(proxies)
                for proxy in proxies:
                    start_time = time.time()
                    session = requests.Session()
                    session.proxies = {"http": proxy, "https": proxy}
                    try:
                        response = session.post(url, json=mem_, timeout=60)
                    except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as error:
                        reasons = ['Connection aborted', 'Max retries exceeded with url',]
                        if any(x in str(error) for x in reasons):
                            remove_proxy(proxy)
                        else:
                            my_log.log3(f'{error}\n\n{proxy}')
                        continue

                    if response.status_code == 200:
                        result = response.json()['candidates'][0]['content']['parts'][0]['text']
                        end_time = time.time()
                        total_time = end_time - start_time
                        if total_time > 50:
                            remove_proxy(proxy)
                        else:
                            PROXY_POLL_SPEED[proxy] = total_time
                            save_proxy_pool()
                        break
                    else:
                        remove_proxy(proxy)
                        my_log.log2(f'my_gemini:ai:{proxy} {key} {str(response)} {response.text}')
            else:
                response = requests.post(url, json=mem_, timeout=60)
                if response.status_code == 200:
                    result = response.json()['candidates'][0]['content']['parts'][0]['text']
                else:
                    my_log.log2(f'my_gemini:ai:{key} {str(response)} {response.text}')

            if result:
                break
    except Exception as unknown_error:
        my_log.log2(f'my_gemini:ai:{unknown_error}')

    return result.strip()


def chat(query: str, chat_id: str, temperature: float = 0.1, update_memory: bool = True) -> str:
    """
    Executes a chat query and returns the response.

    Args:
        query (str): The query string.
        chat_id (str): The ID of the chat.
        temperature (float, optional): The temperature value for the chat response. Defaults to 0.1.
        update_memory (bool, optional): Indicates whether to update the chat memory. Defaults to True.

    Returns:
        str: The response generated by the chat model.
    """
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        if chat_id not in CHATS:
            CHATS[chat_id] = []
        mem = CHATS[chat_id]
        r = ai(query, mem, temperature)
        if r and update_memory:
            mem = update_mem(query, r, mem)
            CHATS[chat_id] = mem
        return r


def reset(chat_id: str):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    CHATS[chat_id] = []


def get_mem_as_string(chat_id: str) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
    result = ''
    for x in mem:
        role = x['role']
        try:
            text = x['parts'][0]['text'].split(']: ', maxsplit=1)[1]
        except IndexError:
            text = x['parts'][0]['text']
        result += f'{role}: {text}\n'
        if role == 'model':
            result += '\n'
    return result    


def save_proxy_pool():
    """
    Saves the proxy pool to disk.
    """
    global PROXY_POLL_SPEED
    with SAVE_LOCK:
        s = {}
        for x in PROXY_POOL:
            try:
                s[x] = PROXY_POLL_SPEED[x]
            except:
                pass
        PROXY_POLL_SPEED = s
        with open(PROXY_POOL_DB_FILE, 'wb') as f:
            pickle.dump(PROXY_POOL, f)
        with open(PROXY_POLL_SPEED_DB_FILE, 'wb') as f:
            pickle.dump(PROXY_POLL_SPEED, f)
        # with open(PROXY_POOL_REMOVED_DB_FILE, 'wb') as f:
        #     pickle.dump(PROXY_POOL_REMOVED, f)


def remove_proxy(proxy: str):
    """
    Remove a proxy from the proxy pool and add it to the removed proxy pool.

    Args:
        proxy (str): The proxy to be removed.

    Returns:
        None
    """
    # не удалять прокси из конфига
    try:
        if proxy in cfg.gemini_proxies:
            return
    except AttributeError:
        pass

    global PROXY_POOL, PROXY_POOL_REMOVED

    PROXY_POOL = [x for x in PROXY_POOL if x != proxy]

    PROXY_POOL_REMOVED.append(proxy)
    PROXY_POOL_REMOVED = list(set(PROXY_POOL_REMOVED))
    
    save_proxy_pool()


def sort_proxies_by_speed(proxies):
    """
    Sort proxies by speed.

    Args:
        proxies (list): The list of proxies to be sorted.

    Returns:
        list: The sorted list of proxies.
    """
    # неопробованные прокси считаем что имеют скорость как было при поиске = 5 секунд(или менее)
    for x in PROXY_POOL:
        if x not in PROXY_POLL_SPEED:
            PROXY_POLL_SPEED[x] = 5

    try:
        proxies.sort(key=lambda x: PROXY_POLL_SPEED[x])
    except KeyError as key_error:
        # my_log.log2(f'sort_proxies_by_speed: {key_error}')
        pass


def test_proxy_for_gemini(proxy: str = '') -> bool:
    """
    A function that tests a proxy for the Gemini API.

    Parameters:
        proxy (str): The proxy to be tested (default is an empty string).

    Returns:
        Если proxy = '', то проверяем работу напрямую и отвечает True/False.
        Если proxy != '', то заполняем пул новыми проксями.

    Description:
        This function tests a given proxy for the Gemini API by sending a query to the AI
        with the specified proxy. The query is set to '1+1= answer very short'. The function
        measures the time it takes to get an answer from the AI and stores it in the variable
        'total_time'. If the proxy parameter is not provided, the function checks if the answer
        from the AI is True. If it is, the function returns True, otherwise it returns False.
        If the proxy parameter is provided and the answer from the AI is not in the list
        'PROXY_POOL_REMOVED', and the total time is less than 5 seconds, the proxy is added
        to the 'PROXY_POOL' list.

    Note:
        - The 'ai' function is assumed to be defined elsewhere in the code.
        - The 'PROXY_POOL_REMOVED' and 'PROXY_POOL' variables are assumed to be defined elsewhere in the code.
        - The 'time' module is assumed to be imported.
    """

    # # не искать больше чем нужно
    # if proxy and len(PROXY_POOL) > MAX_PROXY_POOL:
    #     return

    query = '1+1= answer very short'
    start_time = time.time()
    answer = ai(query, proxy_str=proxy)
    total_time = time.time() - start_time

    # если проверяем работу напрямую то нужен ответ - True/False
    if not proxy:
        if answer:
            return True
        else:
            return False
    # если с прокси то ответ не нужен
    else:
        if answer and answer not in PROXY_POOL_REMOVED:
            if total_time < 5:
                PROXY_POOL.append(proxy)
                PROXY_POLL_SPEED[proxy] = total_time
                save_proxy_pool()


def get_proxies():
    """
        Retrieves a list of proxies and tests them for usability.

        Returns:
            None
    """
    try:
        scrapper = Scrapper(category='ALL', print_err_trace=False)
        data = scrapper.getProxies()
        proxies = [f'http://{x.ip}:{x.port}' for x in data.proxies]

        p_socks5h = 'https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/socks5.txt'
        p_socks4 = 'https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/socks4.txt'
        p_http = 'https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/http.txt'

        try:
            p_socks5h = requests.get(p_socks5h, timeout=60).text.split('\n')
            p_socks5h = [f'socks5h://{x}' for x in p_socks5h if x]
            p_socks4 = requests.get(p_socks4, timeout=60).text.split('\n')
            p_socks4 = [f'socks4://{x}' for x in p_socks4 if x]
            p_http = requests.get(p_http, timeout=60).text.split('\n')
            p_http = [f'http://{x}' for x in p_http if x]
            proxies += p_socks5h + p_socks4 + p_http
            random.shuffle(proxies)
        except Exception as error:
            my_log.log2(f'my_gemini:get_proxies: {error}')

        n = 0
        maxn = len(proxies)
        step = POOL_MAX_WORKERS

        while n < maxn:
            if len(PROXY_POOL) > MAX_PROXY_POOL:
                break
            if len(PROXY_POOL) == 0:
                step = 500
            else:
                step = POOL_MAX_WORKERS
            chunk = proxies[n:n+step]
            n += step
            print(f'Proxies found: {len(PROXY_POOL)} (processing {n} of {maxn})')
            with concurrent.futures.ThreadPoolExecutor(max_workers=step) as executor:
                futures = [executor.submit(test_proxy_for_gemini, proxy) for proxy in chunk]
                for future in futures:
                    future.result()
    except Exception as error:
        my_log.log2(f'my_gemini:get_proxies: {error}')


def update_proxy_pool_daemon():
    """
        Update the proxy pool daemon.

        This function continuously updates the global `PROXY_POOL` list with new proxies.
        It ensures that the number of proxies in the pool is maintained below the maximum
        limit specified by the `MAX_PROXY_POOL` constant.

        Parameters:
        None

        Returns:
        None
    """
    global PROXY_POOL
    while 1:
        if len(PROXY_POOL) < MAX_PROXY_POOL_LOW_MARGIN:
                get_proxies()
                PROXY_POOL = list(set(PROXY_POOL))
                save_proxy_pool()
                time.sleep(60*60)
        else:
            time.sleep(60)


def run_proxy_pool_daemon():
    """
    Runs a daemon to manage the proxy pool.

    This function initializes the necessary variables and starts a background thread to update the proxy pool.
    If no Gemini proxies are configured, it checks if a direct connection to Gemini is available.
    If Gemini proxies are configured, it sets the `PROXY_POOL` global variable to the configured proxies.

    If the `PROXY_POOL` is empty and a direct connection to Gemini is not available,
    it attempts to load the proxy pool from a file. If the loading fails,
    it continues without a proxy pool. It then starts a background thread to
    update the proxy pool and waits until at least one proxy is available in the pool.

    This function does not take any parameters and does not return anything.
    """
    global PROXY_POOL, PROXY_POOL_REMOVED, PROXY_POLL_SPEED
    try:
        proxies = cfg.gemini_proxies
    except AttributeError:
        proxies = []

    # если проксей нет то проверяем возможна ли работа напрямую
    if not proxies:
        direct_connect_available = test_proxy_for_gemini()
        # вторая попытка
        if not direct_connect_available:
            time.sleep(2)
            direct_connect_available = test_proxy_for_gemini()
            if not direct_connect_available:
                my_log.log2('proxy:run_proxy_pool_daemon: direct connect unavailable')
    else:
        PROXY_POOL = proxies

    if not PROXY_POOL and not direct_connect_available:
        try:
            with open(PROXY_POOL_DB_FILE, 'rb') as f:
                PROXY_POOL = pickle.load(f)
            with open(PROXY_POLL_SPEED_DB_FILE, 'rb') as f:
                PROXY_POLL_SPEED = pickle.load(f)
            # with open(PROXY_POOL_REMOVED_DB_FILE, 'rb') as f:
            #     PROXY_POOL_REMOVED = pickle.load(f)
        except:
            pass
        thread = threading.Thread(target=update_proxy_pool_daemon)
        thread.start()
        # Waiting until at least 1 proxy is found
        # while len(PROXY_POOL) < 1:
        #     time.sleep(1)


def chat_cli():
    """
    Function to run a command line interface for chatting.

    This function takes no parameters.

    Returns:
        None
    """
    style = ''
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(f'{style} {q}', 'test')
        print(r)


if __name__ == '__main__':
    run_proxy_pool_daemon()
    # test cli chat
    chat_cli()
