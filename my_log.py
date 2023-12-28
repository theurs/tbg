#!/usr/bin/env python3


import datetime
import threading


lock = threading.Lock()


def log2(text: str) -> None:
    global lock
    with lock:
        time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
        log_file_path = 'logs/debug.log'
        open(log_file_path, 'a', encoding="utf-8").write(f'{time_now}\n\n{text}\n{"=" * 80}\n')


if __name__ == '__main__':
    log2('test')
