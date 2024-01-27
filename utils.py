#!/usr/bin/env python3


import html
import random
import re
import string

import prettytable
import requests
import telebot
from bs4 import BeautifulSoup
from pylatexenc.latex2text import LatexNodes2Text
from lingua import Language, LanguageDetectorBuilder

import my_log


def bot_markdown_to_html(text: str) -> str:
    # переделывает маркдаун от чатботов в хтмл для телеграма
    # сначала делается полное экранирование
    # затем меняются маркдаун теги и оформление на аналогичное в хтмл
    # при этом не затрагивается то что внутри тегов код, там только экранирование
    # латекс код в тегах $ и $$ меняется на юникод текст

    # экранируем весь текст для html
    text = html.escape(text)
    
    # найти все куски кода между ``` и заменить на хеши
    # спрятать код на время преобразований
    matches = re.findall('```(.*?)```', text, flags=re.DOTALL)
    list_of_code_blocks = []
    for match in matches:
        random_string = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        list_of_code_blocks.append([match, random_string])
        text = text.replace(f'```{match}```', random_string)

    # тут могут быть одиночные поворяющиеся `, меняем их на '
    text = text.replace('```', "'''")

    matches = re.findall('`(.*?)`', text, flags=re.DOTALL)
    list_of_code_blocks2 = []
    for match in matches:
        random_string = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        list_of_code_blocks2.append([match, random_string])
        text = text.replace(f'`{match}`', random_string)

    # переделываем списки на более красивые
    new_text = ''
    for i in text.split('\n'):
        ii = i.strip()
        if ii.startswith('* '):
            i = i.replace('* ', '• ', 1)
        if ii.startswith('- '):
            i = i.replace('- ', '• ', 1)
        new_text += i + '\n'
    text = new_text.strip()

    # 1 или 2 * в <b></b>
    text = re.sub('\*\*(.+?)\*\*', '<b>\\1</b>', text)

    # tex в unicode
    matches = re.findall("\$\$?(.*?)\$\$?", text, flags=re.DOTALL)
    for match in matches:
        new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
        text = text.replace(f'$${match}$$', new_match)
        text = text.replace(f'${match}$', new_match)

    # меняем маркдаун ссылки на хтмл
    text = re.sub(r'\[([^\]]*)\]\(([^\)]*)\)', r'<a href="\2">\1</a>', text)
    # меняем все ссылки на ссылки в хтмл теге кроме тех кто уже так оформлен
    text = re.sub(r'(?<!<a href=")(https?://\S+)(?!">[^<]*</a>)', r'<a href="\1">\1</a>', text)

    # меняем таблицы до возвращения кода
    text = replace_tables(text)

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks2:
        # new_match = html.escape(match)
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks:
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    text = replace_code_lang(text)

    # text = replace_tables(text)

    return text


def replace_code_lang(t: str) -> str:
    """
    Replaces the code language in the given string with appropriate HTML tags.

    Parameters:
        t (str): The input string containing code snippets.

    Returns:
        str: The modified string with code snippets wrapped in HTML tags.
    """
    result = ''
    state = 0
    for i in t.split('\n'):
        if i.startswith('<code>') and len(i) > 7:
            result += f'<pre><code class = "language-{i[6:]}">'
            state = 1
        else:
            if state == 1:
                if i == '</code>':
                    result += '</code></pre>'
                    state = 0
                else:
                    result += i + '\n'
            else:
                result += i + '\n'
    return result


def split_text(text: str, chunk_limit: int = 1500):
    """ Splits one string into multiple strings, with a maximum amount of chars_per_string
        characters per string. This is very useful for splitting one giant message into multiples.
        If chars_per_string > 4096: chars_per_string = 4096. Splits by '\n', '. ' or ' ' in exactly
        this priority.

        :param text: The text to split
        :type text: str

        :param chars_per_string: The number of maximum characters per part the text is split to.
        :type chars_per_string: int

        :return: The splitted text as a list of strings.
        :rtype: list of str
    """
    return telebot.util.smart_split(text, chunk_limit)


def replace_tables(text: str) -> str:
    text += '\n'
    state = 0
    table = ''
    results = []
    for line in text.split('\n'):
        if line.count('|') > 2 and len(line) > 4:
            if state == 0:
                state = 1
            table += line + '\n'
        else:
            if state == 1:
                results.append(table[:-1])
                table = ''
                state = 0

    for table in results:
        x = prettytable.PrettyTable(align = "l",
                                    set_style = prettytable.MSWORD_FRIENDLY,
                                    hrules = prettytable.HEADER,
                                    junction_char = '|')

        lines = table.split('\n')
        header = [x.strip().replace('<b>', '').replace('</b>', '') for x in lines[0].split('|') if x]
        header = [split_long_string(x, header = True) for x in header]
        try:
            x.field_names = header
        except Exception as error:
            my_log.log2(f'tb:replace_tables: {error}')
            continue
        for line in lines[2:]:
            row = [x.strip().replace('<b>', '').replace('</b>', '') for x in line.split('|') if x]
            row = [split_long_string(x) for x in row]
            try:
                x.add_row(row)
            except Exception as error2:
                my_log.log2(f'tb:replace_tables: {error2}')
                continue
        new_table = x.get_string()
        text = text.replace(table, f'<pre><code>{new_table}\n</code></pre>')

    return text


def split_html(text: str, max_length: int = 1500) -> list:
    """
    Split the given HTML text into chunks of maximum length specified by `max_length`.

    Parameters:
        text (str): The HTML text to be split into chunks.
        max_length (int, optional): The maximum length of each chunk. Defaults to 1500.

    Returns:
        list: A list of chunks, where each chunk is a string.
    """
    code_tag = ''
    in_code_mode = 0

    chunks = []
    chunk = ''

    for line in text.split('\n'):
        if line.startswith('<pre><code') and line.find('</code></pre>') == -1:
            in_code_mode = 1
            code_tag = line[:line.find('>', 10) + 1]

        elif line.startswith('<code>') and line.find('</code>') == -1:
            in_code_mode = 2
            code_tag = '<code>'

        elif line.startswith('<b>') and line.find('</b>') == -1:
            in_code_mode = 3
            code_tag = '<b>'

        elif line == '</code></pre>' or line == '</code>' or line == '</b>':
            code_tag = ''
            in_code_mode = 0

        else:
            if len(chunk) + len(line) + 20 > max_length:

                if in_code_mode == 1:
                    chunk += '</code></pre>\n'
                    chunks.append(chunk)
                    chunk = code_tag

                if in_code_mode == 2:
                    chunk += '</code>\n'
                    chunks.append(chunk)
                    chunk = code_tag

                if in_code_mode == 3:
                    chunk += '</b>\n'
                    chunks.append(chunk)
                    chunk = code_tag

                elif in_code_mode == 0:
                    chunks.append(chunk)
                    chunk = ''

        chunk += line + '\n'

    chunks.append(chunk)

    chunks2 = []
    for chunk in chunks:
        if len(chunk) > max_length:
            chunks2 += split_text(chunk, max_length)
        else:
            chunks2.append(chunk)

    return chunks2


def split_long_string(long_string: str, header = False, MAX_LENGTH = 24) -> str:
    if len(long_string) <= MAX_LENGTH:
        return long_string
    if header:
        return long_string[:MAX_LENGTH-2] + '..'
    split_strings = []
    while len(long_string) > MAX_LENGTH:
        split_strings.append(long_string[:MAX_LENGTH])
        long_string = long_string[MAX_LENGTH:]

    if long_string:
        split_strings.append(long_string)

    result = "\n".join(split_strings) 
    return result


def download_image_as_bytes(url: str) -> bytes:
  """
  Downloads an image from the given URL and returns it as bytes.

  Parameters:
      url (str): The URL of the image to be downloaded.

  Returns:
      bytes: The content of the downloaded image.
  """
  response = requests.get(url)
  return response.content


language_attributes = dir(Language)
language_names = [f'Language.{attr}' for attr in language_attributes if isinstance(attr, str) and attr.isupper()]
languages = [eval(attr) for attr in language_names]
def detect_lang(text: str) -> str:
    """
    Detects the language of the given text.

    Parameters:
        text (str): The text to be analyzed.

    Returns:
        str: The detected language code.
    """
    # create a list of all languages
    # languages = [Language.AFRIKAANS, Language.ALBANIAN, Language.ARABIC, Language.ARMENIAN,
    #              Language.AZERBAIJANI, Language.BASQUE, Language.BELARUSIAN, Language.BENGALI,
    #              Language.BOKMAL, Language.BOSNIAN, Language.BULGARIAN, Language.CATALAN,
    #              Language.CHINESE, Language.CROATIAN, Language.CZECH, Language.DANISH,
    #              Language.DUTCH, Language.ENGLISH, Language.ESPERANTO, Language.ESTONIAN,
    #              Language.FINNISH, Language.FRENCH, Language.GANDA, Language.GEORGIAN,
    #              Language.GERMAN, Language.GREEK, Language.GUJARATI, Language.HEBREW,
    #              Language.HINDI, Language.HUNGARIAN, Language.ICELANDIC, Language.INDONESIAN,
    #              Language.IRISH, Language.ITALIAN, Language.JAPANESE, Language.KAZAKH,
    #              Language.KOREAN, Language.LATIN, Language.LATVIAN, Language.LITHUANIAN,
    #              Language.MACEDONIAN, Language.MALAY, Language.MAORI, Language.MARATHI,
    #              Language.MONGOLIAN, Language.NYNORSK, Language.PERSIAN, Language.POLISH,
    #              Language.PORTUGUESE, Language.PUNJABI, Language.ROMANIAN, Language.RUSSIAN,
    #              Language.SERBIAN, Language.SHONA, Language.SLOVAK, Language.SLOVENE,
    #              Language.SOMALI, Language.SOTHO, Language.SPANISH, Language.SWAHILI,
    #              Language.SWEDISH, Language.TAGALOG, Language.TAMIL, Language.TELUGU,
    #              Language.THAI, Language.TSONGA, Language.TSWANA, Language.TURKISH,
    #              Language.UKRAINIAN, Language.URDU, Language.VIETNAMESE, Language.WELSH,
    #              Language.XHOSA, Language.YORUBA, Language.ZULU]
    
    # language_attributes = dir(Language)
    # language_names = [f'Language.{attr}' for attr in language_attributes if isinstance(attr, str) and attr.isupper()]
    # languages = [eval(attr) for attr in language_names]
    
    detector = LanguageDetectorBuilder.from_languages(*languages).build()
    language = detector.detect_language_of(text)
    if language:
        return language.iso_code_639_1.name.lower()
    else:
        return None


if __name__ == '__main__':
    print(detect_lang('привет'))