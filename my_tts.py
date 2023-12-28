#!/usr/bin/env python3


import io

import gtts


def tts_google(text: str, lang: str = 'ru') -> bytes:
    """
    Converts the given text to speech using the Google Text-to-Speech (gTTS) API.

    Parameters:
        text (str): The text to be converted to speech.
        lang (str, optional): The language of the text. Defaults to 'ru'.

    Returns:
        bytes: The generated audio as a bytes object.
    """
    mp3_fp = io.BytesIO()
    result = gtts.gTTS(text, lang=lang)
    result.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    data = mp3_fp.read()
    return data


def tts(text: str, lang: str = 'ru') -> bytes:
    """
    Generates text-to-speech audio from the given input text using the specified voice, 
    speech rate, and gender.

    Args:
        text (str): The input text to convert to speech.
        lang (str, optional): The lang to use for the speech. Defaults to 'ru'.

    Returns:
        bytes: The generated audio as a bytes object.
    """
    text = text.replace('\r','')
    text = text.replace('\n\n','\n')

    data = tts_google(text, lang)

    return data


if __name__ == "__main__":
    pass
