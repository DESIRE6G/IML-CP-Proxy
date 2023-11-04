import glob
import json
import os
import shutil
import re
import signal
import sys
import time
import subprocess
from typing import TypedDict, List, Optional
import redis

COLOR_YELLOW = '\033[33m'
COLOR_RED = '\033[91m'
COLOR_GREEN = '\033[92m'
COLOR_ORANGE = '\033[93m'
COLOR_BLUE = '\033[94m'
COLOR_CYAN = '\033[96m'
COLOR_END = '\033[0m'

COLOR_GRAY_BG = '\033[100m'
COLOR_RED_BG = '\033[101m'
COLOR_GREEN_BG = '\033[102m'
COLOR_YELLOW_BG = '\033[103m'
COLOR_BLUE_BG = '\033[104m'
COLOR_PURPLE_BG = '\033[105m'
COLOR_CYAN_BG = '\033[106m'

redis = redis.Redis()
class TestCase(TypedDict):
    name: str
    subtest: Optional[str]

test_cases : List[TestCase] = [
    {'name': 'l2fwd','subtest': None},
    {'name': 'l2fwd','subtest': 'load_from_redis'},
    {'name': 'l2fwd','subtest': 'write_to_redis'},
    {'name': 'l2fwd','subtest': 'simple_forward'},
    {'name': 'counter','subtest': None},
    {'name': 'counter','subtest': 'simple_forward'},
    {'name': 'counter','subtest': 'write_to_redis'},
    {'name': 'restructure','subtest': None},
    {'name': 'restructure','subtest': 'aggregate1'},
    {'name': 'restructure','subtest': 'aggregate_all'},
]

TARGET_TEST_FOLDER = '__temporary_test_folder'
TESTCASE_FOLDER = 'testcases'
TMUX_WINDOW_NAME = 'proxy_tester'
necessary_files = ['*.p4', '*.py', '*.json', '*.pcap', 'Makefile']

def tmux(command):
    print(f'{COLOR_YELLOW}COMMAND{COLOR_END}: {command}')
    return subprocess.call(f'tmux {command}', shell=True)

def tmux_shell(command, pane_name = None):
    cmd = f'send-keys'
    if pane_name is not None:
       cmd += f' -t {pane_name}'

    cmd += f' "{command}" "C-m"'
    return tmux(cmd)

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


def assert_folder_existence(path):
    if not os.path.exists(path):
        raise Exception(f'{path} has to exist')

def prepare_test_folder(test_case, subtest=None, avoid_symlinks=False):
    clear_folder(TARGET_TEST_FOLDER)
    link_all_files_from_folder('base', TARGET_TEST_FOLDER)
    os.symlink(os.path.realpath('common'), os.path.realpath(f'{TARGET_TEST_FOLDER}/common'))

    assert_folder_existence(f'{TESTCASE_FOLDER}/{test_case}')

    for necessary_file_pattern in necessary_files:
        for filepath in glob.glob(f'{TESTCASE_FOLDER}/{test_case}/{necessary_file_pattern}'):
            print('Copying ',filepath)
            if os.path.islink(filepath):
                filename = os.path.basename(filepath)
                os.link(f'{filepath}', f'{TARGET_TEST_FOLDER}/{filename}')
            else:
                os.link(f'{filepath}', f'{TARGET_TEST_FOLDER}/{os.path.basename(filepath)}')

    if subtest is not None:
        subtest_folder_path = f'{TESTCASE_FOLDER}/{test_case}/subtests/{subtest}'
        assert_folder_existence(subtest_folder_path)
        link_all_files_from_folder(subtest_folder_path, TARGET_TEST_FOLDER)


def prepare_enviroment():
    config = Config(f"{TARGET_TEST_FOLDER}/test_config.json", ignore_missing_file=True)
    redis_file_path = f"{TARGET_TEST_FOLDER}/redis.json"
    redis.flushdb()
    if os.path.isfile(redis_file_path) and config.get('load_redis_json',True):
        print(f'{COLOR_YELLOW_BG}REDIS FILLING from redis.json{COLOR_END}')
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


def run_test_cases(test_cases_to_run):
    success_counter = 0
    for test_case_object in test_cases_to_run:
        print(f'{COLOR_CYAN}============================================================================')
        print(f'Run test {test_case_object}')
        print(f'============================================================================{COLOR_END}')
        test_case = test_case_object['name']
        subtest = test_case_object['subtest']
        try:
            # Copy test case files
            prepare_test_folder(test_case, subtest)
            prepare_enviroment()

            config = Config(f"{TARGET_TEST_FOLDER}/test_config.json", ignore_missing_file=True)

            # Initialize mininet
            for _ in range(3):
                exit_code1 = tmux(f'new -d -s {TMUX_WINDOW_NAME}')
                print(f'exit_code1={exit_code1}')
                if exit_code1 == 0:
                    exit_code2 = tmux(f'select-window -t {TMUX_WINDOW_NAME}')
                    print(f'exit_code2={exit_code2}')
                    if exit_code2 == 0:
                        break

                print('Waiting for retry 2 sec')
                time.sleep(2)
                print(f'{COLOR_ORANGE} Retry server init {COLOR_END}')
            else:
                raise Exception('Cannot create tmux session!')

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
            tmux_shell('python3 proxy.py', proxy_pane_name)

            wait_for_output('^Proxy is ready', proxy_pane_name)
            # Start Controller
            if config.get('start_controller', default=True):
                tmux_shell(f'cd {TARGET_TEST_FOLDER}', controller_pane_name)
                tmux_shell('python3 controller.py', controller_pane_name)

            if active_test_modes['ping']:
                tmux_shell(f'h1 ping h2', mininet_pane_name)
                wait_for_output('^64 bytes from', mininet_pane_name)

            if active_test_modes['pcap']:
                time.sleep(5)
                tmux_shell('h2 python receive.py test_h2_expected.pcap &', mininet_pane_name)
                tmux_shell('h1 python send.py test_h1_input.pcap', mininet_pane_name)
                time.sleep(5)
                with open(f'{TARGET_TEST_FOLDER}/test_output.json', 'r') as f:
                    test_output = json.load(f)
                    if not test_output['success']:
                        raise Exception(f'Pcap test failed, check test_output.json for more details')

            if active_test_modes['validator']:
                tmux_shell(f'h1 ping h2', mininet_pane_name)
                wait_for_output('^64 bytes from', mininet_pane_name)

                print('------------- RUN VALIDATION -----------')
                exit_code = subprocess.call(f'{os.path.realpath(TARGET_TEST_FOLDER)}/validator.py', shell=True, cwd=os.path.realpath(TARGET_TEST_FOLDER))
                print('------------- VALIDATION FINISHED -----------')

                if exit_code != 0:
                    raise Exception(f'Validation failed')

            test_case_printable_name = test_case
            if subtest is not None:
                test_case_printable_name += f' / {subtest}'
            print(f'{COLOR_GREEN}{test_case_printable_name} test successfully finished!{COLOR_END}')
            print('')


            if len(test_cases_to_run) != 1:
                clear_folder(TARGET_TEST_FOLDER)
            success_counter += 1
        finally:
            time.sleep(4)
            close_everything_and_save_logs()
    if success_counter == len(test_cases_to_run):
        print(f'{COLOR_GREEN}----------------------------------')
        print('All tests were passed successfully')
        print(f'----------------------------------{COLOR_END}')


def close_everything_and_save_logs():
    if (os.path.exists(f'{TARGET_TEST_FOLDER}/logs')):
        tmux(f'capture-pane -S - -pt {mininet_pane_name} > {TARGET_TEST_FOLDER}/logs/mininet.log')
        tmux(f'capture-pane -S - -pt {controller_pane_name} > {TARGET_TEST_FOLDER}/logs/controller.log')
        tmux(f'capture-pane -S - -pt {proxy_pane_name} > {TARGET_TEST_FOLDER}/logs/proxy.log')
    tmux_shell(f'C-c', proxy_pane_name)
    tmux_shell(f'C-c', proxy_pane_name)
    tmux_shell(f'C-c', controller_pane_name)
    tmux_shell(f'C-c', mininet_pane_name)
    tmux_shell(f'quit', mininet_pane_name)
    tmux_shell(f'make stop', mininet_pane_name)
    wait_for_output('^mininet@mininet-vm', mininet_pane_name)
    tmux_shell(f'tmux kill-session -t {TMUX_WINDOW_NAME}')


def process_cmdline_testcase_name(cmdline_input):
    splitted_testcase = cmdline_input.split('/')
    return {
        'name': splitted_testcase[0],
        'subtest': splitted_testcase[1] if len(splitted_testcase) > 1 else None
    }


def sigint_handler(signum, frame):
    print(f'{COLOR_ORANGE}Ctrl-c was pressed! Cleaning up...{COLOR_END}')
    sys.exit(0)

signal.signal(signal.SIGINT, sigint_handler)

if len(sys.argv) == 1:
    run_test_cases(test_cases)
else:
    if sys.argv[1] == 'help':
        print('python tester.py - run all the test cases')
        print('python tester.py [testcase] - run one test case ([test_name] or [test_name]/[subtest] form, e.g. l2fwd/simple_forward)')
        print('python tester.py build [testcase] - prepares the test folder with a testcase')
        print('python tester.py prepare - run the preparations for the actual content of the test folder (e.g. redis fill)')
        print('python tester.py release - create a release folder that contains all the necessary files to run the proxy without symlinks')
    elif sys.argv[1] == 'build':
        if len(sys.argv) < 3:
            print('For build a testcase you need to add 3 parameters')
        splitted_testcase = process_cmdline_testcase_name(sys.argv[2])
        prepare_test_folder(splitted_testcase['name'], splitted_testcase['subtest'])
    elif sys.argv[1] == 'prepare':
        prepare_enviroment()
    elif sys.argv[1] == 'release':
        clear_folder('release')
        shutil.copyfile('base/proxy.py', 'release/proxy.py')
        shutil.copyfile('testcases/l2fwd/proxy_config.json', 'release/proxy_config.json')
        shutil.copytree('common','release/common')
    else:
        run_test_cases([process_cmdline_testcase_name(sys.argv[1])])

