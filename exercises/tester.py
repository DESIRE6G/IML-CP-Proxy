import glob
import os
import shutil
import re
import sys
import time
from os import system
import subprocess

test_cases = ['aggregation']
TEST_FOLDER_NAME = '__temporary_test_folder'
TMUX_WINDOW_NAME = 'proxy_tester'
necessary_files = ['*.p4', '*.py', 'topology.json', 'Makefile']

def tmux(command):
    system('tmux %s' % command)

def tmux_shell(command, pane_name = None):
    cmd = f'send-keys'
    if pane_name is not None:
       cmd += f' -t {pane_name}'

    cmd += f' "{command}" "C-m"'

    print(f'COMMAND: {cmd}')
    tmux(cmd)

def get_pane_output(pane_name) -> str:
    output = subprocess.check_output(f'tmux capture-pane -pt {pane_name}', shell=True)
    return output.decode('utf8')

def get_last_pane_row(pane_name) -> str:
    output = get_pane_output(pane_name)
    return [row for row in output.split('\n') if len(row.strip('\n \t')) > 0][-1]

def wait_for_output(regexp_to_wait_for: str, pane_name: str, try_interval=1, max_time=30) -> None:
    print(f'Waiting for {regexp_to_wait_for} on {pane_name}')
    start_time = time.time()
    while time.time() - start_time < max_time:
        last_row = get_last_pane_row(pane_name)
        if re.search(regexp_to_wait_for, last_row) is not None:
            return
        time.sleep(try_interval)

    raise TimeoutError(f'Not found {regexp_to_wait_for} on {pane_name}')

mininet_pane_name = f'{TMUX_WINDOW_NAME}:0.0'
proxy_pane_name = f'{TMUX_WINDOW_NAME}:0.1'
controller_pane_name = f'{TMUX_WINDOW_NAME}:0.2'


def prepare_test_folder(test_case):
    shutil.rmtree(TEST_FOLDER_NAME, ignore_errors=True)
    #os.mkdir(TEST_FOLDER_NAME)
    shutil.copytree('base', TEST_FOLDER_NAME)
    for necessary_file_pattern in necessary_files:
        for filepath in glob.glob(f'{test_case}/{necessary_file_pattern}'):
            print(f'Copying {filepath}')
            if os.path.islink(filepath):
                linkto = os.readlink(filepath)
                filename = os.path.basename(filepath)
                os.symlink(f'../{filepath}', f'{TEST_FOLDER_NAME}/{filename}')
            else:
                shutil.copy(filepath, TEST_FOLDER_NAME)

if len(sys.argv) == 1:
    for test_case in test_cases:
        try:
            # Copy test case files
            prepare_test_folder(test_case)

            # Initialize mininet
            tmux(f'new -d -s {TMUX_WINDOW_NAME}')

            tmux(f'select-window -t {TMUX_WINDOW_NAME}')
            tmux_shell(f'cd {TEST_FOLDER_NAME}')
            tmux_shell(f'make run')
            tmux_shell(f'h1 ping h2')

            wait_for_output('^PING', mininet_pane_name)
            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.0 -v -p60')
            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.1 -v -p50')

            # Start Proxy
            tmux_shell(f'cd {TEST_FOLDER_NAME}',proxy_pane_name)
            tmux_shell('python3 proxy.py',proxy_pane_name)

            # TODO: PROXY HAS TO WRITE SOME MESSAGE IF READY
            time.sleep(1)
            # Start Controller
            tmux_shell(f'cd {TEST_FOLDER_NAME}',controller_pane_name)
            tmux_shell('python3 controller.py',controller_pane_name)

            wait_for_output('^64 bytes from', mininet_pane_name, max_time=40)

            print(f'{test_case} test successfully finished!')
            print('')

            shutil.rmtree(TEST_FOLDER_NAME, ignore_errors = True)

        finally:
            tmux_shell(f'C-c',proxy_pane_name)
            tmux_shell(f'C-c',controller_pane_name)
            tmux_shell(f'C-c', mininet_pane_name)
            tmux_shell(f'quit',mininet_pane_name)
            tmux_shell(f'make stop',mininet_pane_name)
            wait_for_output('^mininet@mininet-vm',mininet_pane_name)
            tmux_shell(f'tmux kill-session -t {TMUX_WINDOW_NAME}')

else:
    prepare_test_folder(sys.argv[1])
