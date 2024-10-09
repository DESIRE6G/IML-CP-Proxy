import os
import re
import shutil
import subprocess
import time
from typing import Optional

from common.colors import COLOR_YELLOW, COLOR_END, COLOR_ORANGE
from common.sync import wait_for_condition_blocking


def tmux(command: str) -> int:
    print(f'{COLOR_YELLOW}COMMAND{COLOR_END}: {command}')
    return subprocess.call(f'tmux {command}', shell=True)


def tmux_shell(command: str, pane_name: str=None, wait_command_appear:bool=False) -> int:
    cmd = f'send-keys'
    if pane_name is not None:
       cmd += f' -t {pane_name}'

    cmd += f' "{command}" "C-m"'
    ret = tmux(cmd)
    if wait_command_appear and pane_name is not None and command.strip() not in ['C-c']:
        wait_for_output_anywhere(command, pane_name)
    return ret


def get_pane_output(pane_name: str) -> str:
    output = subprocess.check_output(f'tmux capture-pane -pt {pane_name}', shell=True)
    return output.decode('utf8')


def get_last_pane_row(pane_name: str) -> str:
    output = get_pane_output(pane_name)
    rows = [row for row in output.split('\n') if len(row.strip('\n \t')) > 0]
    for i in range(1, len(rows)):
        row = rows[-i]
        if row.strip() != '':
            return row

    return ''


def wait_for_output_anywhere(regexp_to_wait_for: str, pane_name: str, try_interval=0.5, max_time=10):
    wait_for_condition_blocking(lambda: re.search(regexp_to_wait_for, get_pane_output(pane_name)) is not None, f'Cannot find {regexp_to_wait_for} on {pane_name}', try_interval, max_time)


def wait_for_output(regexp_to_wait_for: str, pane_name: str, try_interval=0.5, max_time=10) -> None:
    print(f'Waiting for {regexp_to_wait_for} on {pane_name}')

    def inner_function() -> bool:
        last_row = get_last_pane_row(pane_name)
        if re.search(regexp_to_wait_for, last_row) is not None:
            return True
        print(f'Waiting... last_row="{last_row}"')
        return False

    wait_for_condition_blocking(inner_function, f'Not found {regexp_to_wait_for} on {pane_name}', try_interval, max_time)


def clear_folder(folder_path: str) -> None:
    os.makedirs(folder_path, exist_ok=True)

    for entry in os.scandir(folder_path):
        if entry.is_file() or entry.is_symlink():
            os.unlink(entry.path)
        else:
            shutil.rmtree(entry.path, ignore_errors = True)


def link_file_with_override(source_path: str, target_path: str):
    if os.path.isfile(target_path) or os.path.islink(target_path):
        os.unlink(target_path)
    else:
        shutil.rmtree(target_path, ignore_errors=True)
    os.link(source_path, target_path)


def link_all_files_from_folder(from_path: str, to_path: str) -> None:
    for entry in os.scandir(from_path):
        target_path = f'{to_path}/{os.path.basename(entry.path)}'
        source_path = entry.path
        link_file_with_override(source_path, target_path)


def assert_folder_existence(path: str) -> None:
    if not os.path.isdir(path):
        raise Exception(f'Cannot find a "{path}" folder')


def link_into_folder(path: str, dst_folder: str) -> None:
    os.link(f'{path}', f'{dst_folder}/{os.path.basename(path)}')


def close_everything_and_save_logs(window_name: str, panes_dict: dict, folder: Optional[str] = None) -> None:
    if folder is None:
        logs_folder = 'logs'
    else:
        logs_folder = f'{folder}/logs'

    os.makedirs(logs_folder, exist_ok=True)
    for pane_name, pane_tmux_name in panes_dict.items():
        tmux(f'capture-pane -S - -pt {pane_tmux_name} > {logs_folder}/{pane_name}.log')

    for pane_name, pane_tmux_name in panes_dict.items():
        tmux_shell(f'C-c', pane_tmux_name)
        tmux_shell(f'C-c', pane_tmux_name)

    tmux_shell(f'tmux kill-session -t {window_name}')


def create_tmux_window_with_retry(window_name):
    for _ in range(3):
        exit_code1 = tmux(f'new -d -s {window_name} -x 150')
        print(f'exit_code1={exit_code1}')
        if exit_code1 == 0:
            exit_code2 = tmux(f'select-window -t {window_name}')
            print(f'exit_code2={exit_code2}')
            if exit_code2 == 0:
                break

        print('Waiting for retry 1 sec')
        time.sleep(1)
        print(f'{COLOR_ORANGE} Retry server init {COLOR_END}')
    else:
        raise Exception('Cannot create tmux session!')