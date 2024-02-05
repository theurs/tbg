# tbg
Gemini Pro AI telegram bot [python]

## Features

• Responds to text, voice, photo, and video messages

• Uses speech recognition and text-to-speech to handle voice messages

• Answers questions about images when users send photos

![example1](imgs/1.png) ![example2](imgs/2.png) ![example3](imgs/3.png) ![example4](imgs/4.png)

# Install

git clone https://github.com/theurs/tbg.git

python -m venv .tb1

source ~/.tb1/bin/activate

cd tbg

pip install -r requirements.txt

sudo apt install ffmpeg


# Preparation steps:

1. Get free Gemini Pro API token(s) at https://ai.google.dev/ use VPN and multiple accounts if needed.
2. Get telegram bot token from @BotFather.
3. Set up cfg.py, see example.
4. Run bot ./tb.py or with systemd service (see example)
5. [Optional] Get api token key from https://huggingface.co/

In windows download and install ffmpeg from https://ffmpeg.org/download.html
1. Download and run EXE file with telegram bot token as argument https://disk.yandex.ru/d/Y2UsesubYWNxFA
2. Set keys with /key command
3. Set users with /users command
4. [Optional] Set hugging face keys with /hfkey command

# Report issues

https://t.me/theurs

