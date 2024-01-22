#!/usr/bin/env python3


import json
import pickle
import random
import time
from multiprocessing.pool import ThreadPool

import langdetect
import requests

import cfg
import my_gemini
import my_log


DEBUG = False


def translate_prompt_to_en(prompt: str) -> str:
    """
    Translates a given prompt to English if it is not already in English.

    Args:
        prompt (str): The input prompt to be translated.

    Returns:
        str: The translated prompt in English.
    """
    detected_lang = langdetect.detect(prompt)
    if detected_lang != 'en':
        prompt_translated = my_gemini.translate(prompt, to_lang='en', help='This is a prompt for image generation. Users can write it in their own language, but only English is supported.')
        if prompt_translated:
            prompt = prompt_translated
    return prompt


def rewrite_prompt_for_open_dalle(prompt: str) -> str:
    """
    Generate a new prompt for OpenDalle image generation by rewriting the given prompt.
    
    Args:
        prompt (str): The original prompt for image generation.
        
    Returns:
        str: The rewritten prompt in English.
    """
    prompt_translated = my_gemini.ai(f'This is a prompt for image generation. Rewrite it in english, in one long sentance, make it better:\n\n{prompt}', temperature=1)
    if not prompt_translated:
        return translate_prompt_to_en(prompt)
    return translate_prompt_to_en(prompt_translated)


def huggin_face_api(prompt: str) -> bytes:
    """
    Calls the Hugging Face API to generate text based on a given prompt.
    
    Args:
        prompt (str): The prompt to generate text from.
    
    Returns:
        bytes: The generated text as bytes.
    """
    if not hasattr(cfg, 'huggin_face_api') or not cfg.huggin_face_api:
        return []

    API_URL = [
                "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
                "https://api-inference.huggingface.co/models/dataautogpt3/OpenDalleV1.1",
                "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2-1",
                "https://api-inference.huggingface.co/models/openskyml/dalle-3-xl",
                "https://api-inference.huggingface.co/models/prompthero/openjourney",
                "https://api-inference.huggingface.co/models/cagliostrolab/animagine-xl-3.0",
                "https://api-inference.huggingface.co/models/thibaud/sdxl_dpo_turbo",
               ]

    # prompt = translate_prompt_to_en(prompt)
    prompt = rewrite_prompt_for_open_dalle(prompt)
    payload = json.dumps({"inputs": prompt})

    def request_img(prompt, url, p):
        n = 10
        result = []
        while n > 0:
            n -= 1

            if hasattr(cfg, 'bing_proxy'):
                proxy = {'http': random.choice(cfg.bing_proxy), 'https': random.choice(cfg.bing_proxy)}
            else:
                proxy = None
            api_key = random.choice(cfg.huggin_face_api)
            headers = {"Authorization": f"Bearer {api_key}"}

            try:
                response = requests.post(url, headers=headers, json=p, timeout=120, proxies=proxy)
            except Exception as error:
                my_log.log2(f'my_genimg:huggin_face_api: {error}\nPrompt: {prompt}\nAPI key: {api_key}\nProxy: {proxy}\nURL: {url}')
                continue

            resp_text = str(response.content)[:300]
            # print(resp_text[:60])
            if 'read timeout=' in resp_text: # и так долго ждали
                return []
            if response.content and '{"error"' not in resp_text:
                result.append(response.content)
                return result

            if 'is currently loading","estimated_time":' in str(resp_text) or \
                '"error":"Internal Server Error"' in str(resp_text) or \
                '"CUDA out of memory' in str(resp_text) or \
                '"error":"Service Unavailable"' in str(resp_text):
                if DEBUG:
                    my_log.log2(f'my_genimg:huggin_face_api: {resp_text} | {proxy} | {url}')
            else: # unknown error
                my_log.log2(f'my_genimg:huggin_face_api: {resp_text} | {proxy} | {url}')
            time.sleep(10)

        return result

    pool = ThreadPool(processes=6)
    async_result1 = pool.apply_async(request_img, (prompt, API_URL[6], payload,))
    async_result2 = pool.apply_async(request_img, (prompt, API_URL[6], payload,))
    async_result3 = pool.apply_async(request_img, (prompt, API_URL[3], payload,))
    async_result4 = pool.apply_async(request_img, (prompt, API_URL[3], payload,))
    async_result5 = pool.apply_async(request_img, (prompt, API_URL[0], payload,))
    async_result6 = pool.apply_async(request_img, (prompt, API_URL[2], payload,))
    result = async_result1.get() + async_result2.get() + async_result3.get() + async_result4.get() + async_result5.get() + async_result6.get()

    result = list(set(result))

    return result


def gen_images(prompt: str):
    return huggin_face_api(prompt)


if __name__ == '__main__':
    HFKEYS_DB_FILE = 'db/hugginface_keys.pkl'
    try:
        with open(HFKEYS_DB_FILE, 'rb') as f:
            cfg.huggin_face_api = pickle.load(f)
    except Exception as load_keys_error:
        my_log.log2(f'tb:load_keys_error: {load_keys_error} {HFKEYS_DB_FILE}')

    n=0
    t = my_gemini.ai('Напиши промпт для рисования красивой картинки, сделай одно предложение.', temperature=1)
    starttime=time.time()
    print(t)
    for x in huggin_face_api(t):
        n+=1
        open(f'{n}.jpg','wb').write(x)
    endtime=time.time()
    print(round(endtime - starttime, 2))
