import glob
import json
import os
import shutil
import re
import sys
import time
from os import system
import subprocess
from typing import TypedDict, List, Optional
import redis



redis = redis.Redis()
class TestCase(TypedDict):
    name: str
    subtest: Optional[str]

test_cases : List[TestCase] = [
    {'name': 'aggregation','subtest': None},
    #{'name': 'aggregation','subtest': 'redis'},
]

#test_cases = ['mate-example-not-aggregated']
TARGET_TEST_FOLDER = '__temporary_test_folder'
TESTCASE_FOLDER = 'testcases'
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


def prepare_test_folder(test_case, subtest=None):
    shutil.rmtree(TARGET_TEST_FOLDER, ignore_errors=True)
    #os.mkdir(TEST_FOLDER_NAME)
    shutil.copytree('base', TARGET_TEST_FOLDER)
    for necessary_file_pattern in necessary_files:
        for filepath in glob.glob(f'{TESTCASE_FOLDER}/{test_case}/{necessary_file_pattern}'):
            print(f'Copying {filepath}')
            if os.path.islink(filepath):
                linkto = os.readlink(filepath)
                filename = os.path.basename(filepath)
                os.symlink(f'../{filepath}', f'{TARGET_TEST_FOLDER}/{filename}')
            else:
                shutil.copy(filepath, TARGET_TEST_FOLDER)

    if subtest is not None:
        shutil.copytree(f'{TESTCASE_FOLDER}/{test_case}/subtests/{subtest}', TARGET_TEST_FOLDER, dirs_exist_ok=True)


def prepare_enviroment():
    redis_file_path = f"{TARGET_TEST_FOLDER}/redis.json"
    redis.flushdb()
    if os.path.isfile(redis_file_path):
        with open(redis_file_path) as f:
            redis_data = json.load(f)
            for table_obj in redis_data:
                redis_key = table_obj['key']
                if "list" in table_obj:
                    for data_one_record in table_obj["list"]:
                       redis.rpush(redis_key, data_one_record)
                if "string" in table_obj:
                    redis.set(redis_key, table_obj['string'])


class Config():
    def __init__(self, config_file, ignore_missing_file = False):
        self.config = {}
        try:
            with open(config_file) as f:
                self.config = json.load(f)
        except FileNotFoundError as e:
            if not ignore_missing_file:
                raise e

    def get(self, key, default = None):
        if key in self.config:
            return self.config[key]

        return default

if len(sys.argv) == 1:
    for test_case_object in test_cases:
        test_case = test_case_object['name']
        subtest = test_case_object['subtest']
        try:
            # Copy test case files
            prepare_test_folder(test_case, subtest)
            prepare_enviroment()

            config = Config(f"{TARGET_TEST_FOLDER}/test_config.json", ignore_missing_file = True)

            # Initialize mininet
            tmux(f'new -d -s {TMUX_WINDOW_NAME}')

            tmux(f'select-window -t {TMUX_WINDOW_NAME}')
            tmux_shell(f'cd {TARGET_TEST_FOLDER}')
            tmux_shell(f'make run')
            tmux_shell(f'h1 ping h2')

            wait_for_output('^PING', mininet_pane_name)
            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.0 -v -p60')
            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.1 -v -p50')




            # Start Proxy
            tmux_shell(f'cd {TARGET_TEST_FOLDER}', proxy_pane_name)
            tmux_shell('python3 proxy.py',proxy_pane_name)

            # TODO: PROXY HAS TO WRITE SOME MESSAGE IF READY
            time.sleep(1)
            # Start Controller
            if config.get('start_controller', default = True):
                tmux_shell(f'cd {TARGET_TEST_FOLDER}', controller_pane_name)
                tmux_shell('python3 controller.py',controller_pane_name)

            wait_for_output('^64 bytes from', mininet_pane_name, max_time=40)

            test_case_printable_name = test_case
            if subtest is not None:
                test_case_printable_name += f' / {subtest}'

            print(f'\033[92m{test_case_printable_name} test successfully finished!\033[0m')
            print('')

            shutil.rmtree(TARGET_TEST_FOLDER, ignore_errors = True)

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
