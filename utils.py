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

import my_log


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


def bot_markdown_to_html(text: str) -> str:
    text = html.escape(text)
    
    matches = re.findall('```(.*?)```', text, flags=re.DOTALL)
    list_of_code_blocks = []
    for match in matches:
        random_string = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        list_of_code_blocks.append([match, random_string])
        text = text.replace(f'```{match}```', random_string)
    matches = re.findall('`(.*?)`', text, flags=re.DOTALL)
    list_of_code_blocks2 = []
    for match in matches:
        random_string = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        list_of_code_blocks2.append([match, random_string])
        text = text.replace(f'`{match}`', random_string)

    new_text = ''
    for i in text.split('\n'):
        ii = i.strip()
        if ii.startswith('* '):
            i = i.replace('* ', '• ', 1)
        if ii.startswith('- '):
            i = i.replace('- ', '• ', 1)
        new_text += i + '\n'
    text = new_text.strip()

    text = re.sub('\*\*(.+?)\*\*', '<b>\\1</b>', text)

    matches = re.findall("\$\$?(.*?)\$\$?", text, flags=re.DOTALL)
    for match in matches:
        new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
        text = text.replace(f'$${match}$$', new_match)
        text = text.replace(f'${match}$', new_match)

    text = re.sub(r'\[([^\]]*)\]\(([^\)]*)\)', r'<a href="\2">\1</a>', text)

    text = re.sub(r'(?<!<a href=")(https?://\S+)(?!">[^<]*</a>)', r'<a href="\1">\1</a>', text)


    for match, random_string in list_of_code_blocks2:
        # new_match = html.escape(match)
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')


    for match, random_string in list_of_code_blocks:
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    text = replace_code_lang(text)

    text = replace_tables(text)

    return text


def split_html(text: str, max_length: int = 1500) -> list:
    """
    Split the given HTML text into chunks of maximum length, while preserving the integrity
    of HTML tags. The function takes two arguments:
    
    Parameters:
        - text (str): The HTML text to be split.
        - max_length (int): The maximum length of each chunk. Default is 1500.
        
    Returns:
        - list: A list of chunks, where each chunk is a part of the original text.
        
    Raises:
        - AssertionError: If the length of the text is less than or equal to 299.
    """

    if len(text) < 300:
        return [text,]

    # Find and replace all links (tag <a>) with random words of the same length
    links = []
    soup = BeautifulSoup(text, 'html.parser')
    a_tags = soup.find_all('a')
    for tag in a_tags:
        tag = str(tag)
        random_string = ''.join(random.choice(string.ascii_uppercase+string.ascii_lowercase) for _ in range(len(tag)))
        links.append((random_string, tag))
        text = text.replace(tag, random_string)

    # split text
    chunks = telebot.util.smart_split(text, max_length)
    chunks2 = []
    next_chunk_is_b = False
    next_chunk_is_code = False
    # In each piece, check the coincidence of the number of opening and closing tags <b> <code>
    # and replace the random words back to links
    for chunk in chunks:
        for random_string, tag in links:
            chunk = chunk.replace(random_string, tag)

        b_tags = chunk.count('<b>')
        b_close_tags = chunk.count('</b>')
        code_tags = chunk.count('<pre>')
        code_close_tags = chunk.count('</pre>')

        if b_tags > b_close_tags:
            chunk += '</b>'
            next_chunk_is_b = True
        elif b_tags < b_close_tags:
            chunk = '<b>' + chunk
            next_chunk_is_b = False

        if code_tags > code_close_tags:
            chunk += '</pre>'
            next_chunk_is_code = True
        elif code_tags < code_close_tags:
            chunk = '<pre>' + chunk
            next_chunk_is_code = False

        # If there are no opening and closing tags <code> and in the previous chunk
        # a closing tag was added, then this chunk is entirely code
        if code_close_tags == 0 and code_tags == 0 and next_chunk_is_code:
            chunk = '<pre>' + chunk
            chunk += '</pre>'

        # If there are no opening and closing tags <b> and in the previous chunk
        # a closing tag was added, then this chunk is entirely <b>
        if b_close_tags == 0 and b_tags == 0 and next_chunk_is_b:
            chunk = '<b>' + chunk
            chunk += '</b>'

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
        text = text.replace(table, f'<pre><code>{new_table}</code></pre>')

    return text


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


if __name__ == '__main__':
    pass