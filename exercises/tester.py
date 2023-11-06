import glob
import itertools
import json
import os
import shutil
import re
import signal
import sys
import time
import subprocess
from typing import TypedDict, List, Optional, Callable
import redis

from common.redis_helper import save_redis_to_json_file

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
    {'name': 'l2fwd','subtest': 'simple_forward'},
    {'name': 'l2fwd','subtest': 'delete_entry'},
    {'name': 'counter','subtest': None},
    {'name': 'counter','subtest': 'simple_forward'},
    {'name': 'counter','subtest': 'write_to_redis'},
    {'name': 'restructure','subtest': None},
    {'name': 'restructure','subtest': 'aggregate1'},
    {'name': 'restructure','subtest': 'aggregate_all'},
    {'name': 'restructure','subtest': 'aggregate_all_from_redis'},
]

TARGET_TEST_FOLDER = '__temporary_test_folder'
BUILD_CACHE_FOLDER = '__build_cache'
TESTCASE_FOLDER = 'testcases'
TMUX_WINDOW_NAME = 'proxy_tester'
necessary_files = ['*.p4', '*.py', '*.json', '*.pcap', 'Makefile']

def tmux(command):
    print(f'{COLOR_YELLOW}COMMAND{COLOR_END}: {command}')
    return subprocess.call(f'tmux {command}', shell=True)

def tmux_shell(command, pane_name = None, wait_command_appear=False):
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

    return rows[-1] if len(rows) > 0 else ''

def wait_for_condition_blocking(callback_function: Callable[[], bool], timeout_message: str = None, try_interval=0.5, max_time=10) -> None:
    start_time = time.time()
    while time.time() - start_time < max_time:
        if callback_function():
            return
        time.sleep(try_interval)

    if timeout_message is not None:
        raise TimeoutError(timeout_message)
    else:
        raise TimeoutError(f'wait_for_condition failed to wait try_interval={try_interval}, max_time={max_time}')


def wait_for_output_anywhere(regexp_to_wait_for: str, pane_name: str, try_interval=0.5, max_time=10):
    wait_for_condition_blocking(lambda: re.search(regexp_to_wait_for, get_pane_output(pane_name)) is not None, try_interval, max_time)

def wait_for_output(regexp_to_wait_for: str, pane_name: str, try_interval=0.5, max_time=10) -> None:
    print(f'Waiting for {regexp_to_wait_for} on {pane_name}')

    def inner_function() -> bool:
        last_row = get_last_pane_row(pane_name)
        if re.search(regexp_to_wait_for, last_row) is not None:
            return True
        print(f'Waiting... last_row="{last_row}"')
        return False

    wait_for_condition_blocking(inner_function, f'Not found {regexp_to_wait_for} on {pane_name}', try_interval, max_time)


mininet_pane_name = f'{TMUX_WINDOW_NAME}:0.0'
proxy_pane_name = f'{TMUX_WINDOW_NAME}:0.1'
controller_pane_name = f'{TMUX_WINDOW_NAME}:0.2'



def clear_folder(folder_path):
    os.makedirs(folder_path, exist_ok=True)

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


def link_into_folder(path, dst_folder):
    os.link(f'{path}', f'{dst_folder}/{os.path.basename(path)}')

def copy_prebuilt_files():
    os.makedirs(f'{TARGET_TEST_FOLDER}/build', exist_ok=True)
    for filepath in glob.glob(f'{TARGET_TEST_FOLDER}/*.p4'):
        filename_without_extension = os.path.splitext(os.path.basename(filepath))[0]
        link_into_folder(f'{BUILD_CACHE_FOLDER}/build/{filename_without_extension}.json',f'{TARGET_TEST_FOLDER}/build')
        link_into_folder(f'{BUILD_CACHE_FOLDER}/build/{filename_without_extension}.p4.p4info.txt',f'{TARGET_TEST_FOLDER}/build')

def prepare_test_folder(test_case, subtest=None):
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
    copy_prebuilt_files()

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

                print('Waiting for retry 1 sec')
                time.sleep(1)
                print(f'{COLOR_ORANGE} Retry server init {COLOR_END}')
            else:
                raise Exception('Cannot create tmux session!')

            tmux_shell(f'cd {TARGET_TEST_FOLDER}',mininet_pane_name)
            tmux_shell(f'mkdir -p logs',mininet_pane_name)
            tmux_shell(f'make stop',mininet_pane_name)
            tmux_shell(f'make run',mininet_pane_name)
            try:
                wait_for_output('^mininet>', mininet_pane_name, max_time=30)
            except Exception as e:
                tmux(f'capture-pane -S - -pt {mininet_pane_name}')
                raise e

            active_test_modes = {
                'pcap': os.path.exists(f'{TARGET_TEST_FOLDER}/test_h1_input.pcap'),
                'validator': os.path.exists(f'{TARGET_TEST_FOLDER}/validator.py') and config.get('run_validator', default=True)
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
                wait_for_output(f'{TARGET_TEST_FOLDER}\$\s*$', controller_pane_name)

            if active_test_modes['ping']:
                tmux_shell(f'h1 ping h2', mininet_pane_name)
                print('Waiting for PING response')
                wait_for_output('^64 bytes from', mininet_pane_name)
                print(f'{COLOR_GREEN}PING response arrived, ping test succeed{COLOR_END}')

            if active_test_modes['pcap']:
                tmux_shell('h2 python receive.py test_h2_expected.pcap &', mininet_pane_name, wait_command_appear=True)
                wait_for_output('^mininet>', mininet_pane_name)
                tmux_shell('h1 python send.py test_h1_input.pcap', mininet_pane_name)
                wait_for_output('^mininet>', mininet_pane_name)

                wait_for_condition_blocking(lambda: os.path.exists(f'{TARGET_TEST_FOLDER}/.pcap_receive_finished'))

                with open(f'{TARGET_TEST_FOLDER}/test_output.json', 'r') as f:
                    test_output = json.load(f)
                    if not test_output['success']:
                        if 'ordered_compare' in test_output:
                            print(f'{COLOR_RED_BG}PCAP Test failed{COLOR_END}')
                            for i, compare in enumerate(test_output['ordered_compare']):
                                print(f'--- [Packet {i}] ---')
                                print(f'Expected: {compare["expected"]}')
                                print(f'Arrived:  {compare["arrived_colored"]}')
                                print(f'          {compare["diff_string"]}')
                        raise Exception(f'Pcap test failed, check the logs above or the test_output.json for more details')

            if active_test_modes['validator']:
                if not active_test_modes['pcap'] and not active_test_modes['ping']:
                    tmux_shell(f'h1 ping h2', mininet_pane_name)
                    print('Waiting for PING response')
                    wait_for_output('^64 bytes from', mininet_pane_name)
                    print(f'{COLOR_GREEN}PING response arrived, ping test succeed{COLOR_END}')

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


def process_cmdline_testcase_name(cmdline_input: str):
    splitted_testcase = cmdline_input.split('/')

    if len(splitted_testcase) > 1 and splitted_testcase[1].strip() == '*':
        ret = []

        for test_case in test_cases:
            if test_case['name'] == splitted_testcase[0]:
                ret.append(test_case)

        return ret
    else:
        return [{
            'name': splitted_testcase[0],
            'subtest': splitted_testcase[1] if len(splitted_testcase) > 1 else None
        }]


def sigint_handler(signum, frame):
    print(f'{COLOR_ORANGE}Ctrl-c was pressed! Cleaning up...{COLOR_END}')
    sys.exit(0)

signal.signal(signal.SIGINT, sigint_handler)


def build_up_p4_cache():
    print(f'{COLOR_CYAN}--- Building up P4 cache{COLOR_END} --- ')
    os.makedirs(BUILD_CACHE_FOLDER, exist_ok=True)

    def link_with_override(src, dst):
        if os.path.exists(dst):
            os.remove(dst)
        os.link(src, dst)

    link_with_override('base/Makefile', f'{BUILD_CACHE_FOLDER}/Makefile')
    p4files = []
    success = True
    for root, dirs, files in itertools.chain(os.walk('testcases'), os.walk('base')):
        for file in files:
            if file.endswith('.p4'):
                filepath = f'{root}/{file}'
                print(filepath)
                link_with_override(filepath, f'{BUILD_CACHE_FOLDER}/{file}')
                if file in p4files:
                    print(f'{COLOR_RED_BG}P4File caching does not support multiple files{COLOR_END} skipping cache use')
                    success = False
                    break
                p4files.append(file)

    if success:
        exit_code = subprocess.call(f'make build', shell=True, cwd=os.path.realpath(BUILD_CACHE_FOLDER))
        if exit_code > 0:
            print(f'{COLOR_RED_BG}Build failed{COLOR_END}')
            sys.exit()

if len(sys.argv) == 1:
    build_up_p4_cache()
    run_test_cases(test_cases)
else:
    if sys.argv[1] == 'help':
        print('python tester.py - run all the test cases')
        print('python tester.py [testcase] - run one test case ([test_name] or [test_name]/[subtest] form, e.g. l2fwd/simple_forward)')
        print('                              you can use wildcard for subtest to run all of the subtests for a test case e.g.: l2fwd/*')
        print('python tester.py build [testcase] - prepares the test folder with a testcase')
        print('python tester.py prepare - run the preparations for the actual content of the test folder (e.g. redis fill)')
        print('python tester.py release - create a release folder that contains all the necessary files to run the proxy without symlinks')
    elif sys.argv[1] == 'build':
        if len(sys.argv) < 3:
            raise Exception('For build a testcase you need to add 3 parameters')
        test_cases_to_build = process_cmdline_testcase_name(sys.argv[2])
        if len(test_cases_to_build) == 1:
            splitted_testcase = test_cases_to_build[0]
            prepare_test_folder(splitted_testcase['name'], splitted_testcase['subtest'])
        else:
            raise Exception('You cannot use wildcard for building a test case.')
    elif sys.argv[1] == 'prepare':
        prepare_enviroment()
    elif sys.argv[1] == 'release':
        clear_folder('release')
        shutil.copyfile('base/proxy.py', 'release/proxy.py')
        shutil.copyfile('testcases/l2fwd/proxy_config.json', 'release/proxy_config.json')
        shutil.copytree('common','release/common')
    elif sys.argv[1] == 'saveredis':
        if len(sys.argv) < 3:
            raise Exception('For saveredis you have to pass a filename as well')
        redis_file = sys.argv[2]
        save_redis_to_json_file(redis_file)
    else:
        build_up_p4_cache()
        run_test_cases(process_cmdline_testcase_name(sys.argv[1]))

