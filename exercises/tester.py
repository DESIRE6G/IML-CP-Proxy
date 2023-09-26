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
    {'name': 'l2fwd','subtest': None},
    {'name': 'l2fwd','subtest': 'load_from_redis'},
    {'name': 'l2fwd','subtest': 'simple_forward'},
    {'name': 'counter','subtest': None},
    {'name': 'counter','subtest': 'simple_forward'},
]

TARGET_TEST_FOLDER = '__temporary_test_folder'
TESTCASE_FOLDER = 'testcases'
TMUX_WINDOW_NAME = 'proxy_tester'
necessary_files = ['*.p4', '*.py', '*.json', '*.pcap', 'Makefile']

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

def wait_for_output(regexp_to_wait_for: str, pane_name: str, try_interval=1, max_time=10) -> None:
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



def clear_folder(folder_path):
    if not os.path.isdir(folder_path):
        os.mkdir(folder_path)

    for entry in os.scandir(folder_path):
        if entry.is_file() or entry.is_symlink():
            os.unlink(entry.path)
        else:
            shutil.rmtree(entry.path, ignore_errors = True)

def link_all_files_from_folder(from_path, to_path):
    for entry in os.scandir(from_path):
        target_path = f'{to_path}/{os.path.basename(entry.path)}'
        if os.path.isfile(target_path) or os.path.islink(target_path):
            os.unlink(target_path)
        else:
            shutil.rmtree(target_path, ignore_errors=True)

        os.link(f'{entry.path}', f'{target_path}')


def prepare_test_folder(test_case, subtest=None):
    clear_folder(TARGET_TEST_FOLDER)
    link_all_files_from_folder('base', TARGET_TEST_FOLDER)
    os.symlink(os.path.realpath('common'), os.path.realpath(f'{TARGET_TEST_FOLDER}/common'))

    for necessary_file_pattern in necessary_files:
        for filepath in glob.glob(f'{TESTCASE_FOLDER}/{test_case}/{necessary_file_pattern}'):
            print('Copying ',filepath)
            if os.path.islink(filepath):
                filename = os.path.basename(filepath)
                os.link(f'{filepath}', f'{TARGET_TEST_FOLDER}/{filename}')
            else:
                os.link(f'{filepath}', f'{TARGET_TEST_FOLDER}/{os.path.basename(filepath)}')

    if subtest is not None:
        link_all_files_from_folder(f'{TESTCASE_FOLDER}/{test_case}/subtests/{subtest}', TARGET_TEST_FOLDER)


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
    success_counter = 0
    for test_case_object in test_cases:
        print('============================================================================')
        print(f'Run test {test_case_object}')
        print('============================================================================')
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
            tmux_shell(f'mkdir -p logs')
            tmux_shell(f'make stop')
            tmux_shell(f'make run')
            wait_for_output('^mininet>', mininet_pane_name, max_time=30)

            active_test_modes = {
                'pcap': os.path.exists(f'{TARGET_TEST_FOLDER}/test_h1_input.pcap'),
                'validator': os.path.exists(f'{TARGET_TEST_FOLDER}/validator.py')
            }
            active_test_modes['ping'] = not any([active_test_modes[test_mode] for test_mode in active_test_modes])


            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.0 -v -p60')
            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.1 -v -p50')

            # Start Proxy
            tmux_shell(f'cd {TARGET_TEST_FOLDER}', proxy_pane_name)
            tmux_shell('python3 proxy.py',proxy_pane_name)

            wait_for_output('^Proxy is ready', proxy_pane_name)
            # Start Controller
            if config.get('start_controller', default = True):
                tmux_shell(f'cd {TARGET_TEST_FOLDER}', controller_pane_name)
                tmux_shell('python3 controller.py',controller_pane_name)

            if active_test_modes['ping']:
                tmux_shell(f'h1 ping h2', mininet_pane_name)
                wait_for_output('^64 bytes from', mininet_pane_name)

            if active_test_modes['pcap']:
                time.sleep(5)
                tmux_shell('h2 python receive.py test_h2_expected.pcap &', mininet_pane_name)
                tmux_shell('h1 python send.py test_h1_input.pcap', mininet_pane_name)
                time.sleep(5)
                with open(f'{TARGET_TEST_FOLDER}/test_output.json','r') as f:
                    test_output = json.load(f)
                    if not test_output['success']:
                        raise Exception(f'Pcap test failed, check test_output.json for more details')

            if active_test_modes['validator']:
                tmux_shell(f'h1 ping h2', mininet_pane_name)
                wait_for_output('^64 bytes from', mininet_pane_name)

                print('------------- RUN VALIDATION -----------')
                exit_code = subprocess.call(f'{os.path.realpath(TARGET_TEST_FOLDER)}/validator.py', shell=True,
                                            cwd=os.path.realpath(TARGET_TEST_FOLDER))
                print('------------- VALIDATION FINISHED -----------')

                if exit_code != 0:
                    raise Exception(f'Validation failed')

            test_case_printable_name = test_case
            if subtest is not None:
                test_case_printable_name += f' / {subtest}'

            print(f'\033[92m{test_case_printable_name} test successfully finished!\033[0m')
            print('')

            clear_folder(TARGET_TEST_FOLDER)
            success_counter += 1
        finally:
            time.sleep(4)
            tmux(f'capture-pane -S - -pt {mininet_pane_name} > {TARGET_TEST_FOLDER}/logs/mininet.log')
            tmux(f'capture-pane -S - -pt {controller_pane_name} > {TARGET_TEST_FOLDER}/logs/controller.log')
            tmux(f'capture-pane -S - -pt {proxy_pane_name} > {TARGET_TEST_FOLDER}/logs/proxy.log')
            tmux_shell(f'C-c',proxy_pane_name)
            tmux_shell(f'C-c',proxy_pane_name)
            tmux_shell(f'C-c',controller_pane_name)
            tmux_shell(f'C-c', mininet_pane_name)
            tmux_shell(f'quit',mininet_pane_name)
            tmux_shell(f'make stop',mininet_pane_name)
            wait_for_output('^mininet@mininet-vm',mininet_pane_name)
            tmux_shell(f'tmux kill-session -t {TMUX_WINDOW_NAME}')

    if success_counter == len(test_cases):
        print(f'\033[92m----------------------------------\033[0m')
        print(f'\033[92mAll tests were passed successfully\033[0m')
        print(f'\033[92m----------------------------------\033[0m')


else:
    prepare_test_folder(sys.argv[1])
