#!/usr/bin/env python3


import datetime
import threading
import os


lock = threading.Lock()


def log2(text: str) -> None:
    global lock
    with lock:
        time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
        log_file_path = 'logs/debug.log'
        # if no log file then create one
        if not os.path.exists(log_file_path):
            open(log_file_path, 'w', encoding="utf-8").write('NEW LOG FILE\n\n')
        # if log file too big then create new one
        if os.path.getsize(log_file_path) > 10000000:
            open(log_file_path, 'w', encoding="utf-8").write(f'{time_now}\n\n{text}\n{"=" * 80}\n')
        else:
            open(log_file_path, 'a', encoding="utf-8").write(f'{time_now}\n\n{text}\n{"=" * 80}\n')


def log3(text: str) -> None:
    global lock
    with lock:
        time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
        log_file_path = 'logs/debug_why_remove_proxy.log'
        if not os.path.exists(log_file_path):
            open(log_file_path, 'w', encoding="utf-8").write('NEW LOG FILE\n\n')
        # if log file too big then create new one
        if os.path.getsize(log_file_path) > 10000000:
            open(log_file_path, 'w', encoding="utf-8").write(f'{time_now}\n\n{text}\n{"=" * 80}\n')
        else:
            open(log_file_path, 'a', encoding="utf-8").write(f'{time_now}\n\n{text}\n{"=" * 80}\n')



if __name__ == '__main__':
    log2('test')
