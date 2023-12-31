#!/usr/bin/env python3

import io
import os
import pickle
import re
import sys
import tempfile
import datetime
import threading
import time

import telebot

import cfg
import my_gemini
import my_log
import my_stt
import my_tts
import utils


# Setting the working directory to the directory where the script is located
# print(sys.argv)
if os.name == 'nt':
    if not cfg.token:
        if not sys.argv[1]:
            print('Usage: tb.py <telegram token>')
            sys.exit(1)
        cfg.token = sys.argv[1]
        print(f'Telegram token: {cfg.token[:5]}xxxxx')
    else:
        pass

    settings_path = f'{os.environ["APPDATA"]}/gemini_telegram_tob'
    print(f'Settings path: {settings_path}')
    if not os.path.exists(settings_path):
        os.mkdir(settings_path)
    os.chdir(settings_path)
else:
    os.chdir(os.path.abspath(os.path.dirname(__file__)))


if not os.path.exists('db'):
    os.mkdir('db')
if not os.path.exists('logs'):
    os.mkdir('logs')

KEYS_DB_FILE = 'db/gemini_keys.pkl'
USERS_DB_FILE = 'db/gemini_users.pkl'

bot = telebot.TeleBot(cfg.token, skip_pending=True)
_bot_name = bot.get_me().username
BOT_ID = bot.get_me().id


# Saving incoming messages, if they are too long and
# were sent by the client in pieces {id:[messages]}
# Catching the message and waiting half a second to see if another piece arrives
MESSAGE_QUEUE = {}


class ShowAction(threading.Thread):
    """A thread that can be stopped. Continuously sends a notification of activity to the chat.
    Telegram automatically turns off the notification after 5 seconds, so it needs to be repeated.

    To use in the code, you need to do something like this:
    with ShowAction(message, 'typing'):
        do something and while you do the notification does not go out
    """
    def __init__(self, message, action):
        """_summary_

        Args:
            chat_id (_type_): id of the chat where the notification will be sent
            action (_type_):  "typing", "upload_photo", "record_video", "upload_video", "record_audio", 
                              "upload_audio", "upload_document", "find_location", "record_video_note", "upload_video_note"
        """
        super().__init__()
        self.actions = [  "typing", "upload_photo", "record_video", "upload_video", "record_audio",
                         "upload_audio", "upload_document", "find_location", "record_video_note", "upload_video_note"]
        assert action in self.actions, f'Allowed actions = {self.actions}'
        self.chat_id = message.chat.id
        self.thread_id = message.message_thread_id
        self.is_topic = message.is_topic_message
        self.action = action
        self.is_running = True
        self.timerseconds = 1

    def run(self):
        while self.is_running:
            try:
                if self.is_topic:
                    bot.send_chat_action(self.chat_id, self.action, message_thread_id = self.thread_id)
                else:
                    bot.send_chat_action(self.chat_id, self.action)
            except Exception as error:
                my_log.log2(f'tb:show_action:run: {error}')
            n = 50
            while n > 0:
                time.sleep(0.1)
                n = n - self.timerseconds

    def stop(self):
        self.timerseconds = 50
        self.is_running = False
        try:
            bot.send_chat_action(self.chat_id, 'cancel', message_thread_id = self.thread_id)
        except Exception as error:
            my_log.log2(f'tb:show_action: {error}')

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def get_kbd(text: str) -> telebot.types.ReplyKeyboardMarkup:
    """
    Creates a keyboard with a single button.

    Args:
        text (str): The text of the button.

    Returns:
        telebot.types.ReplyKeyboardMarkup: The keyboard.
    """
    if text:
        markup  = telebot.types.InlineKeyboardMarkup(row_width=5)
        button1 = telebot.types.InlineKeyboardButton("TTS", callback_data='tts')
        button2 = telebot.types.InlineKeyboardButton("Reset", callback_data='reset')
        markup.add(button1, button2)
        return markup
    else:
        return None


@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call: telebot.types.CallbackQuery):
    if authorized(call.message):
        thread = threading.Thread(target=callback_inline_thread, args=(call,))
        thread.start()
def callback_inline_thread(call: telebot.types.CallbackQuery):
        message = call.message
        lang = message.from_user.language_code or 'en'

        if call.data == 'tts':
            lang = utils.detect_lang(message.text) or lang
            message.text = f'/tts {lang} {message.text}'
            tts(message)
        elif call.data == 'reset':
            reset(message)


def img2txt(text, lang: str, chat_id_full: str, query: str = '') -> str:
    """
    Generate the text description of an image.

    Args:
        text (str): The image file URL or downloaded data(bytes).
        lang (str): The language code for the image description.
        chat_id_full (str): The full chat ID.

    Returns:
        str: The text description of the image.
    """
    if isinstance(text, bytes):
        data = text
    else:
        data = utils.download_image_as_bytes(text)
    if not query:
        query = 'What is depicted in the image? Give me a detailed description, and explain in detail what this could mean.'

    text = ''

    try:
        text = my_gemini.img2txt(data, query)
    except Exception as img_from_link_error2:
        my_log.log2(f'tb:img2txt: {img_from_link_error2}')

    if text:
        my_gemini.update_mem('User asked about a picture:' + ' ' + query, text, chat_id_full)

    return text


def gemini_reset(chat_id: str):
    """
    Resets the Gemini state for the given chat ID.

    Parameters:
    - chat_id (str): The ID of the chat for which the Gemini state should be reset.
    """
    my_gemini.reset(chat_id)


def get_lang(id: str, message: telebot.types.Message = None) -> str:
    """
    Get the language code of a user based on their Telegram ID.

    Parameters:
        id (str): The Telegram ID of the user.
        message (telebot.types.Message, optional): The Telegram message object. Defaults to None.

    Returns:
        str: The language code of the user. If the language code is not available, 'en' is returned.
    """
    return message.from_user.language_code or 'en'


def get_topic_id(message: telebot.types.Message) -> str:
    """
    Get the topic ID from a Telegram message.

    Parameters:
        message (telebot.types.Message): The Telegram message object.

    Returns:
        str: '[chat.id] [topic.id]'
    """

    chat_id = message.chat.id
    topic_id = 0

    if message.reply_to_message and message.reply_to_message.is_topic_message:
        topic_id = message.reply_to_message.message_thread_id
    elif message.is_topic_message:
        topic_id = message.message_thread_id

    return f'[{chat_id}] [{topic_id}]'


def authorized(message: telebot.types.Message) -> bool:
    """
    Check if the user is authorized to use the bot.

    Parameters:
        message (telebot.types.Message): The Telegram message object.

    Returns:
        bool: True if the user is authorized, False otherwise.
    """
    if message.from_user.id == BOT_ID:
        return True
    if cfg.users:
        if message.from_user.id in cfg.users:
            return True
        else:
            bot.reply_to(message, 'You are not authorized to use this bot.')
        return False
    else:
        return True


@bot.message_handler(content_types = ['voice', 'audio'])
def handle_voice(message: telebot.types.Message):
    if authorized(message):
        thread = threading.Thread(target=handle_voice_thread, args=(message,))
        thread.start()
def handle_voice_thread(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        file_path = temp_file.name + '.ogg'

    try:
        file_info = bot.get_file(message.voice.file_id)
    except AttributeError:
        try:
            file_info = bot.get_file(message.audio.file_id)
        except AttributeError:
            file_info = bot.get_file(message.document.file_id)

    downloaded_file = bot.download_file(file_info.file_path)
    with open(file_path, 'wb') as new_file:
        new_file.write(downloaded_file)

    with ShowAction(message, 'typing'):
        text = my_stt.stt(file_path, lang, chat_id_full)

        try:
            os.unlink(file_path)
        except Exception as remove_file_error:
            my_log.log2(f'tb:handle_voice_thread:remove_file_error: {remove_file_error}\n\nfile_path')

        text = text.strip()
        if text:
            reply_to_long_message(message, text)
            message.text = text
            echo_all(message)
        else:
            bot.reply_to(message, 'Failed to recognize text')


@bot.message_handler(content_types = ['photo'])
def handle_photo(message: telebot.types.Message):
    if authorized(message):
        thread = threading.Thread(target=handle_photo_thread, args=(message,))
        thread.start()
def handle_photo_thread(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    is_private = message.chat.type == 'private'
    if cfg.tts_button:
        tts_button = get_kbd('tts')
    else:
        tts_button = None

    msglower = message.caption.lower() if message.caption else ''

    if msglower.startswith('?') or is_private:
        state = 'describe'
        if message.caption and message.caption[0] == '?':
            message.caption = message.caption[1:]
    else:
        state = ''

    if state == 'describe':
        with ShowAction(message, 'typing'):
            photo = message.photo[-1]
            file_info = bot.get_file(photo.file_id)
            image = bot.download_file(file_info.file_path)
            
            text = img2txt(image, lang, chat_id_full, message.caption)
            if text:
                text = utils.bot_markdown_to_html(text)
                reply_to_long_message(message, text, parse_mode='HTML', reply_markup=tts_button)


@bot.message_handler(content_types = ['video', 'video_note'])
def handle_video(message: telebot.types.Message):
    if authorized(message):
        thread = threading.Thread(target=handle_video_thread, args=(message,))
        thread.start()
def handle_video_thread(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    with ShowAction(message, 'typing'):
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            file_path = temp_file.name
        try:
            file_info = bot.get_file(message.video.file_id)
        except AttributeError:
            file_info = bot.get_file(message.video_note.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        text = my_stt.stt(file_path, lang, chat_id_full)

        try:
            os.unlink(file_path)
        except Exception as remove_file_error:
            my_log.log2(f'tb:handle_video_thread:remove_file_error: {remove_file_error}\n\nfile_path')

        text = text.strip()
        if text:
            reply_to_long_message(message, text)
            message.text = text
            echo_all(message)
        else:
            bot.reply_to(message, 'Failed to recognize text')


def is_for_me(cmd: str):
    """Checks who the command is addressed to, this bot or another one.
    
    /cmd@botname args
    
    Returns (True/False, 'the same command but without the bot name').
    If there is no bot name at all, assumes that the command is addressed to this bot.
    """
    command_parts = cmd.split()
    first_arg = command_parts[0]

    if '@' in first_arg:
        message_cmd = first_arg.split('@', maxsplit=1)[0]
        message_bot = first_arg.split('@', maxsplit=1)[1] if len(first_arg.split('@', maxsplit=1)) > 1 else ''
        message_args = cmd.split(maxsplit=1)[1] if len(command_parts) > 1 else ''
        return (message_bot == _bot_name, f'{message_cmd} {message_args}'.strip())
    else:
        return (True, cmd)


@bot.message_handler(commands=['mem'])
def send_debug_history(message: telebot.types.Message):
    if not authorized(message):
        return

    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_id_full = get_topic_id(message)

    prompt = my_gemini.get_mem_as_string(chat_id_full) or 'Empty'

    reply_to_long_message(message, prompt, parse_mode = '', disable_web_page_preview = True)


@bot.message_handler(commands=['tts'])
def tts(message: telebot.types.Message, caption = None):
    if authorized(message):
        thread = threading.Thread(target=tts_thread, args=(message,))
        thread.start()
def tts_thread(message: telebot.types.Message):
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    # Usage: /tts <language code> <test to say>
    # Example: /tts en Hello all!
    try:
        lang = message.text.split(maxsplit=2)[1]
        text = message.text.split(maxsplit=2)[2]
    except:
        bot.reply_to(message, 'Usage: /tts <language code> <test to say>')
        return

    with ShowAction(message, 'record_audio'):
        audio = my_tts.tts(text, lang)
        if audio:
            bot.send_voice(message.chat.id, audio, reply_to_message_id = message.message_id)
        else:
            bot.reply_to(message, 'Failed to record audio')


@bot.message_handler(commands=['reset'])
def reset(message: telebot.types.Message):
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    if not authorized(message):
        return
    chat_id_full = get_topic_id(message)
    gemini_reset(chat_id_full)
    bot.reply_to(message, 'History cleared')


@bot.message_handler(commands=['start'])
def send_welcome_start(message: telebot.types.Message) -> None:
    help = '''You can send voice messages to this bot.

You can send pictures with questions to the bot, start question with "?" in group to ask the bot about picture.

Commands:
/reset - clear history
/tts <lang> <text to say>
/mem - show your history

/proxy - show found proxies
/key <keys> - set gemini keys
/users <whitespace separated users id> - set authorized users
'''
    if cfg.tts_button:
        tts_button = get_kbd('tts')
    else:
        tts_button = None
    bot.reply_to(message, f'Hello [{message.chat.id}]!\n\n{help}', reply_markup=tts_button)


@bot.message_handler(commands=['key'])
def gemini_keys(message: telebot.types.Message):
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    if not authorized(message):
        return

    try:
        keys = re.findall("[A-Za-z0-9\-_]{39}", message.text)
        cfg.gemini_keys = keys
        with open(KEYS_DB_FILE, 'wb') as f:
            pickle.dump(cfg.gemini_keys, f)
        bot.reply_to(message, f'Saved {len(keys)} keys')
    except Exception as error:
        my_log.log2(f'{error}\n\n{message.text}')
        bot.reply_to(message, 'Usage: /key <gemini keys>')


@bot.message_handler(commands=['users'])
def set_users(message: telebot.types.Message):
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    if not authorized(message):
        return

    try:
        users = message.text.split()[1:]
        users = [int(x) for x in users]
        cfg.users = users
        with open(USERS_DB_FILE, 'wb') as f:
            pickle.dump(cfg.users, f)
        bot.reply_to(message, f'Saved {len(users)} users')
    except Exception as error:
        my_log.log2(f'{error}\n\n{message.text}')
        bot.reply_to(message, 'Usage: /users <users whitespace separated>')


@bot.message_handler(commands=['proxy'])
def proxy(message: telebot.types.Message):
    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    if not authorized(message):
        return

    proxies = my_gemini.PROXY_POOL[:]
    my_gemini.sort_proxies_by_speed(proxies)

    msg = ''

    n = 0
    for x in proxies:
        n += 1
        p1 = f'{int(my_gemini.PROXY_POLL_SPEED[x]):02}'
        p2 = f'{round(my_gemini.PROXY_POLL_SPEED[x], 2):.2f}'.split('.')[1]
        msg += f'[{n:02}] [{p1}.{p2}] {[x]}\n'

    if not msg:
        msg = 'No proxies found'

    bot.reply_to(message, f'Try this proxy to access https://ai.google.dev/\n\n<code>{msg}</code>',
                 parse_mode='HTML', disable_web_page_preview=True)


def send_long_message(message: telebot.types.Message, resp: str, parse_mode:str = None, disable_web_page_preview: bool = None,
                      reply_markup: telebot.types.InlineKeyboardMarkup = None):
    reply_to_long_message(message=message, resp=resp, parse_mode=parse_mode,
                          disable_web_page_preview=disable_web_page_preview,
                          reply_markup=reply_markup, send_message = True)


def reply_to_long_message(message: telebot.types.Message, resp: str, parse_mode: str = None,
                          disable_web_page_preview: bool = None,
                          reply_markup: telebot.types.InlineKeyboardMarkup = None, send_message: bool = False):
    # We send the message, if it is too long then it is split into 2 parts or we send it as a text file

    if not resp:
        return

    chat_id_full = get_topic_id(message)

    if len(resp) < 20000:
        if parse_mode == 'HTML':
            chunks = utils.split_html(resp, 4000)
        else:
            chunks = utils.split_text(resp, 4000)
        counter = len(chunks)
        for chunk in chunks:
            try:
                if send_message:
                    bot.send_message(message.chat.id, chunk, message_thread_id=message.message_thread_id, parse_mode=parse_mode,
                                        disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
                else:
                    bot.reply_to(message, chunk, parse_mode=parse_mode,
                            disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
            except Exception as error:
                my_log.log2(f'tb:reply_to_long_message: {error}')
                my_log.log2(chunk)
                if send_message:
                    bot.send_message(message.chat.id, chunk, message_thread_id=message.message_thread_id, parse_mode='',
                                        disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
                else:
                    bot.reply_to(message, chunk, parse_mode='', disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)
            counter -= 1
            if counter < 0:
                break
            time.sleep(2)
    else:
        buf = io.BytesIO()
        buf.write(resp.encode())
        buf.seek(0)
        bot.send_document(message.chat.id, document=buf, caption='resp.txt', visible_file_name = 'resp.txt')


@bot.message_handler(func=lambda message: True)
def echo_all(message: telebot.types.Message) -> None:
    if authorized(message):
        thread = threading.Thread(target=do_task, args=(message,))
        thread.start()
def do_task(message: telebot.types.Message):
    chat_id_full = get_topic_id(message)
    lang = get_lang(chat_id_full, message)

    # Catching messages that are too long
    if chat_id_full not in MESSAGE_QUEUE:
        MESSAGE_QUEUE[chat_id_full] = message.text
        last_state = MESSAGE_QUEUE[chat_id_full]
        n = 5
        while n > 0:
            n -= 1
            time.sleep(0.1)
            new_state = MESSAGE_QUEUE[chat_id_full]
            if last_state != new_state:
                last_state = new_state
                n = 5
        message.text = last_state
        del MESSAGE_QUEUE[chat_id_full]
    else:
        MESSAGE_QUEUE[chat_id_full] += message.text + '\n\n'
        return

    # unknown command
    if message.text.startswith('/'): return

    if cfg.tts_button:
        tts_button = get_kbd('tts')
    else:
        tts_button = None
    is_topic = message.is_topic_message or (message.reply_to_message and message.reply_to_message.is_topic_message)
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID
    is_private = message.chat.type == 'private'

    # Do not reply if this is a user's response to another user
    try:
        _ = message.dont_check_topic
    except AttributeError:
        message.dont_check_topic = False
    if not message.dont_check_topic:
        if is_topic: # In topics, everything is not the same as in regular chats
            # If the response is not to me or a request to all
            # (in a topic it looks like a response with content_type == 'forum_topic_created')
            if not (is_reply or message.reply_to_message.content_type == 'forum_topic_created'):
                return
        else:
            # If this is a response in a regular chat but the response is not to me, then exit
            if message.reply_to_message and not is_reply:
                return

    # Removing spaces at the end of each line
    message.text = "\n".join([line.rstrip() for line in message.text.split("\n")])

    msg = message.text.lower()

    bot_name_used = False

    if msg.startswith((f'{cfg.bot_name} ', f'{cfg.bot_name},', f'{cfg.bot_name}\n')):
        bot_name_used = True
        message.text = message.text[len(f'{cfg.bot_name} '):].strip()

    bot_name2 = f'@{_bot_name}'
    # remove the name of the bot in the telegram in the request
    if msg.startswith((f'{bot_name2} ', f'{bot_name2},', f'{bot_name2}\n')):
        bot_name_used = True
        message.text = message.text[len(f'{bot_name2} '):].strip()



    if is_reply or is_private or bot_name_used:

        if len(msg) > my_gemini.MAX_REQUEST:
            bot.reply_to(message, f'Too long message" {len(msg)} / {my_gemini.MAX_REQUEST}', reply_markup=tts_button)
            return

        formatted_date = datetime.datetime.now().strftime('%d, %b %Y %H:%M:%S')
        if message.chat.title:
            lang_of_user = lang
            hidden_text = f'[Info to help you answer. You are a telegram chatbot named "{cfg.bot_name}", you are working in chat named "{message.chat.title}", user name is "{message.from_user.full_name}", user language code is "{lang_of_user}", your current date is "{formatted_date}".]'
        else:
            hidden_text = f'[Info to help you answer. You are a telegram chatbot named "{cfg.bot_name}", you are working in private for user named "{message.from_user.full_name}", user language code is "{lang}", your current date is "{formatted_date}".]'
        helped_query = f'{hidden_text} {message.text}'


        with ShowAction(message, 'typing'):
            try:
                answer = my_gemini.chat(helped_query, chat_id_full).strip()
                if answer:
                    answer = utils.bot_markdown_to_html(answer)
                    try:
                        reply_to_long_message(message, answer, parse_mode='HTML',
                                            disable_web_page_preview = True, reply_markup=tts_button)
                    except Exception as error:
                        my_log.log2(f'tb:do_task: {error}')
                        reply_to_long_message(message, answer, parse_mode='', disable_web_page_preview = True, reply_markup=tts_button)
                else:
                    bot.reply_to(message, 'No answer')
            except Exception as error3:
                my_log.log2(str(error3))
            return


if __name__ == '__main__':
    try:
        with open(KEYS_DB_FILE, 'rb') as f:
            cfg.gemini_keys = pickle.load(f)
        with open(USERS_DB_FILE, 'rb') as f:
            cfg.users = pickle.load(f)
    except Exception as load_keys_error:
        my_log.log2(f'tb:load_keys_error: {load_keys_error} {KEYS_DB_FILE}')
    my_gemini.run_proxy_pool_daemon()
    bot.polling(timeout=90, long_polling_timeout=90)
