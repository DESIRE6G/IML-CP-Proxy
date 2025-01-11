import glob
import itertools
import json
import os
import shutil
import signal
import sys
import time
import subprocess
from typing import TypedDict, List, Optional, Any
import redis
from pydantic import BaseModel

from common.colors import COLOR_GREEN, COLOR_ORANGE, COLOR_CYAN, COLOR_END, COLOR_RED_BG, COLOR_YELLOW_BG
from common.model.test_output import TestOutput
from common.redis_helper import save_redis_to_json_file
from common.sync import wait_for_condition_blocking
from common.tmuxing import tmux, tmux_shell, wait_for_output, clear_folder, link_file_with_override, link_all_files_from_folder, assert_folder_existence, link_into_folder, create_tmux_window_with_retry

redis = redis.Redis()
class TestCase(TypedDict):
    name: str
    subtest: Optional[str]

test_cases : List[TestCase] = [
    {'name': 'l3fwd','subtest': None},
    {'name': 'l3fwd','subtest': 'load_from_redis'},
    {'name': 'l3fwd','subtest': 'simple_forward'},
    {'name': 'l3fwd','subtest': 'delete_entry'},
    {'name': 'l3fwd','subtest': 'multiple_update'},
    {'name': 'l3fwd','subtest': 'meta_functions'},
    {'name': 'counter','subtest': None},
    {'name': 'counter','subtest': 'load_from_redis'},
    {'name': 'counter','subtest': 'simple_forward'},
    {'name': 'counter','subtest': 'write_to_redis'},
    {'name': 'counter','subtest': 'preload'},
    {'name': 'counter','subtest': 'disaggregate'},
    {'name': 'counter','subtest': 'disaggregate_load_from_redis'},
    {'name': 'restructure','subtest': None},
    {'name': 'restructure','subtest': 'aggregate1_2_34'},
    {'name': 'restructure','subtest': 'aggregate1_234'},
    {'name': 'restructure','subtest': 'aggregate12_34'},
    {'name': 'restructure','subtest': 'aggregate_all'},
    {'name': 'restructure','subtest': 'aggregate_all_from_redis'},
    {'name': 'restructure','subtest': 'aggregate_all_from_redis_and_modify'},
    {'name': 'restructure','subtest': 'direct_entry_set'},
    {'name': 'restructure','subtest': 'preload'},
    {'name': 'restructure','subtest': 'disaggregate'},
    {'name': 'restructure','subtest': 'disaggregate1_2_34'},
    {'name': 'restructure','subtest': 'disaggregate1_234'},
    {'name': 'restructure','subtest': 'disaggregate12_34'},
    {'name': 'meter','subtest': None},
    {'name': 'meter','subtest': 'load_from_redis'},
    {'name': 'meter','subtest': 'preload'},
    {'name': 'direct_meter','subtest': None},
    {'name': 'direct_meter','subtest': 'load_from_redis'},
    {'name': 'direct_meter','subtest': 'preload'},
    {'name': 'digest','subtest': None},
    {'name': 'digest','subtest': 'disaggregate'},
    {'name': 'l2fwd_disaggregation','subtest': None},
    {'name': 'balancer','subtest': 'fixed_traffic'},
    {'name': 'balancer','subtest': 'changing_traffic'},
    {'name': 'balancer','subtest': 'changing_traffic_with_counter'},
]

TARGET_TEST_FOLDER = '__temporary_test_folder'
TESTCASE_COMMON_FOLDER = 'testcase_common'
BUILD_CACHE_FOLDER = '__build_cache'
TESTCASE_FOLDER = 'testcases'
TMUX_WINDOW_NAME = 'proxy_tester'
TESTCASE_JSON_FILENAME = 'testcase.json'
TESTCASE_JSON_FILE_PATH = os.path.join(TARGET_TEST_FOLDER, TESTCASE_JSON_FILENAME)

class TestcaseDescriptor(BaseModel):
    test_case: str
    subtest: Optional[str] = None

necessary_files = ['*.p4', '*.py', '*.json', '*.pcap', 'Makefile']


def copy_prebuilt_files() -> None:
    os.makedirs(f'{TARGET_TEST_FOLDER}/build', exist_ok=True)
    for filepath in glob.glob(f'{TARGET_TEST_FOLDER}/*.p4'):
        filename_without_extension = os.path.splitext(os.path.basename(filepath))[0]
        link_into_folder(f'{BUILD_CACHE_FOLDER}/build/{filename_without_extension}.json', f'{TARGET_TEST_FOLDER}/build')
        link_into_folder(f'{BUILD_CACHE_FOLDER}/build/{filename_without_extension}.p4.p4info.txt', f'{TARGET_TEST_FOLDER}/build')

def prepare_test_folder(test_case: str, subtest:Optional[str]=None):
    clear_folder(TARGET_TEST_FOLDER)
    with open(TESTCASE_JSON_FILE_PATH, 'wt') as f:
        descriptor = TestcaseDescriptor(test_case=test_case, subtest=subtest)
        f.write(descriptor.model_dump_json(indent=4))
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

    config = ExtendableConfig(f'{TARGET_TEST_FOLDER}/test_config.json', ignore_missing_file=True)
    for override_target, override_source in config.get('file_overrides', {}).items():
        target_path = f'{TARGET_TEST_FOLDER}/{override_target}'
        if os.path.exists(path := f'{TESTCASE_FOLDER}/{test_case}/{override_source}'):
            link_file_with_override(path, target_path)
        elif os.path.exists(path := f'{TESTCASE_COMMON_FOLDER}/{override_source}'):
            link_file_with_override(path, target_path)
        else:
            raise Exception(f'Cannot found any file for "{override_source} -> {override_target}" override')

mininet_pane_name = f'{TMUX_WINDOW_NAME}:0.0'
proxy_pane_name = f'{TMUX_WINDOW_NAME}:0.1'
controller_pane_name = f'{TMUX_WINDOW_NAME}:0.2'




def prepare_environment() -> None:
    config = ExtendableConfig(f"{TARGET_TEST_FOLDER}/test_config.json", ignore_missing_file=True)
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


class ExtendableConfig:
    def __init__(self, config_file_path: str, ignore_missing_file: bool = False) -> None:
        self.config = {}

        def add_postfix_to_filename(path: str, postfix: str) -> str:
            folder, filename = os.path.split(path)
            filename_without_ext, ext = os.path.splitext(filename)
            new_filename = f"{filename_without_ext}{postfix}{ext}"
            return os.path.join(folder, new_filename)

        try:
            with open(config_file_path) as f:
                self.config = json.load(f)
        except FileNotFoundError as e:
            if not ignore_missing_file:
                raise e
        #print('BEFORE EXTEND')
        #pprint(self.config)

        override_file_path = add_postfix_to_filename(config_file_path, '_extend')
        if os.path.exists(override_file_path):
            with open(override_file_path) as f:
                override_config = json.load(f)
                #print('OVERRIDE_CONFIG')
                #pprint(override_config)
                self.config.update(override_config)

        #print('--- CONFIG ---- ')
        #pprint(self.config)

    def get(self, key: str, default = None) -> Any:
        if key in self.config:
            return self.config[key]

        return default


def run_test_cases(test_cases_to_run: list):
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
            prepare_environment()

            config = ExtendableConfig(f"{TARGET_TEST_FOLDER}/test_config.json", ignore_missing_file=True)

            # Initialize mininet
            create_tmux_window_with_retry(TMUX_WINDOW_NAME)

            tmux_shell(f'cd {TARGET_TEST_FOLDER}', mininet_pane_name)
            tmux_shell(f'mkdir -p logs', mininet_pane_name)
            if config.get('start_mininet', True):
                tmux_shell(f'make stop', mininet_pane_name)
                tmux_shell(f'make run', mininet_pane_name)
                try:
                    wait_for_output('^mininet>', mininet_pane_name, max_time=30)
                except Exception as e:
                    tmux(f'capture-pane -S - -pt {mininet_pane_name}')
                    raise e

            check_controller_exit_code =  config.get('ongoing_controller', False)
            active_test_modes = {
                'pcap': os.path.exists(f'{TARGET_TEST_FOLDER}/test_h1_input.pcap'),
                'pcap_generator': os.path.exists(f'{TARGET_TEST_FOLDER}/test_send.py'),
                'validator': os.path.exists(f'{TARGET_TEST_FOLDER}/validator.py') and config.get('run_validator', default=True)
            }
            active_test_modes['ping'] = not any([active_test_modes[test_mode] for test_mode in active_test_modes])

            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.0 -v -p60')
            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.1 -v -p50')

            # Start Proxy
            tmux_shell(f'cd {TARGET_TEST_FOLDER}', proxy_pane_name)
            tmux_shell('python3 proxy.py', proxy_pane_name)

            try:
                wait_for_output('^Proxy is ready', proxy_pane_name)
            except TimeoutError:
                print(f'{COLOR_RED_BG}Proxy is failed to startup{COLOR_END}')
                dump_proxy_output()

            # Start Controller
            if config.get('start_controller', default=True):
                tmux_shell(f'cd {TARGET_TEST_FOLDER}', controller_pane_name)
                tmux_shell('./run_controller.sh', controller_pane_name)

                if config.get('ongoing_controller', False):
                    try:
                        wait_for_condition_blocking(lambda : os.path.exists(f'{TARGET_TEST_FOLDER}/.controller_ready'))
                    except TimeoutError:
                        dump_controller_output()
                        raise
                else:
                    wait_and_assert_controller_exit_code()

            if active_test_modes['ping']:
                tmux_shell(f'h1 ping h2', mininet_pane_name)
                print('Waiting for PING response')
                wait_for_output('^64 bytes from', mininet_pane_name)
                print(f'{COLOR_GREEN}PING response arrived, ping test succeed{COLOR_END}')

            if active_test_modes['pcap'] or active_test_modes['pcap_generator']:
                receive_started_by_host = {}
                for host in ['h1', 'h2']:
                    postfix = f'_{host}' if host != 'h2' else ''

                    try:
                        if os.path.exists(f'{TARGET_TEST_FOLDER}/test_{host}_expected.pcap'):
                            tmux_shell(f'{host} python receive.py test_{host}_expected.pcap {postfix} > receive{postfix}.log 2>&1 &', mininet_pane_name, wait_command_appear=True)
                            receive_started_by_host[host] = True
                        elif os.path.exists(f'{TARGET_TEST_FOLDER}/test_receive{postfix}.py'):
                            tmux_shell(f'{host} python test_receive{postfix}.py > receive{postfix}.log 2>&1 &', mininet_pane_name, wait_command_appear=True)
                            receive_started_by_host[host] = True

                        if host in receive_started_by_host:
                            wait_for_output('^mininet>', mininet_pane_name)
                            print(f'Waiting for .pcap_receive_started{postfix}')
                            wait_for_condition_blocking(lambda : os.path.exists(f'{TARGET_TEST_FOLDER}/.pcap_receive_started{postfix}'))
                    except TimeoutError:
                        with open(f'{TARGET_TEST_FOLDER}/receive{postfix}.log') as f:
                            print(f'{COLOR_RED_BG}PCAP {host} Receive not started correctly{COLOR_END}')
                            print(f.read())
                            print('-------------------------')
                        raise

                if len(receive_started_by_host) == 0:
                    raise Exception('There is no test_h*_expected.pcap or test_receive.py, do not know how to validate pcap test.')

                if active_test_modes['pcap']:
                    tmux_shell('h1 python send.py test_h1_input.pcap > send_h1.log 2>&1 &', mininet_pane_name)
                elif active_test_modes['pcap_generator']:
                    tmux_shell('h1 python test_send.py > send_h1.log 2>&1 &', mininet_pane_name)
                else:
                    raise Exception('I do not know what to send.')
                wait_for_output('^mininet>', mininet_pane_name)

                wait_for_condition_blocking(lambda: os.path.exists(f'{TARGET_TEST_FOLDER}/.pcap_receive_finished'), max_time=60)
                for host in ['h1', 'h2']:
                    postfix = f'_{host}' if host != 'h2' else ''
                    test_output_filename = f'{TARGET_TEST_FOLDER}/test_output{postfix}.json'
                    if os.path.exists(test_output_filename):
                        with open(test_output_filename, 'r') as f:
                            test_output = TestOutput.model_validate_json(f.read())
                            if not test_output.success:
                                if test_output.ordered_compare is not None:
                                    print(f'{COLOR_RED_BG}PCAP {host} Test failed{COLOR_END}')
                                    for i, compare in enumerate(test_output.ordered_compare):
                                        print(f'--- [Packet {i}] ---')
                                        print(f'Expected: {compare.expected}')
                                        print(f'Arrived:  {compare.arrived_colored}')
                                        if compare['ok']:
                                            print(f'{COLOR_GREEN}OK{COLOR_END}')
                                        else:
                                            print(f'          {compare.diff_string}')
                                            print(f'Dump Expected: {compare.dump_expected}')
                                            print(f'Dump Arrived:  {compare.dump_arrived_colored}')
                                            print(f'               {compare.dump_diff_string}')

                                if test_output is not None:
                                    print(test_output.message)

                                raise Exception(f'Pcap test failed, check the logs above or the test_output.json for more details')

                print(f'{COLOR_GREEN}PCAP Test successful{COLOR_END}')
            if active_test_modes['validator']:
                if not active_test_modes['pcap'] and not active_test_modes['ping']:
                    exact_ping_packet_num = config.get("exact_ping_packet_num",None)
                    if exact_ping_packet_num is not None:
                        tmux_shell(f'h1 ping -c {exact_ping_packet_num} h2', mininet_pane_name)
                        print('Waiting for PING response')
                        wait_for_output('^64 bytes from', mininet_pane_name)
                        print(f'{COLOR_GREEN}PING response arrived, ping test succeed{COLOR_END} waiting for ping finish')
                        wait_for_output('^mininet>', mininet_pane_name)
                    else:
                        tmux_shell(f'h1 ping h2', mininet_pane_name)
                        print('Waiting for PING response')
                        wait_for_output('^64 bytes from', mininet_pane_name)


                print('------------- RUN VALIDATION -----------')
                exit_code = subprocess.call(f'{os.path.realpath(TARGET_TEST_FOLDER)}/validator.py', shell=True, cwd=os.path.realpath(TARGET_TEST_FOLDER))
                print('------------- VALIDATION FINISHED -----------')

                if exit_code != 0:
                    raise Exception(f'Validation failed')

            if check_controller_exit_code:
                wait_and_assert_controller_exit_code()


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


def wait_and_assert_controller_exit_code() -> None:
    wait_for_output(f'{TARGET_TEST_FOLDER}\$\s*$', controller_pane_name)
    with open(f'{TARGET_TEST_FOLDER}/.controller_exit_code') as f:
        exit_code = f.read().strip()
        if exit_code != '0':
            print(f'{COLOR_RED_BG}Controller exited with non-zero code!{COLOR_END}')
            dump_controller_output()
            raise Exception('Controller exited with non-zero code')


def dump_proxy_output() -> None:
    tmux(f'capture-pane -S - -pt {proxy_pane_name} > {TARGET_TEST_FOLDER}/logs/proxy.log')
    with open(f'{TARGET_TEST_FOLDER}/logs/proxy.log') as log_f:
        print(f'{COLOR_RED_BG} --- Proxy output --- {COLOR_END}')
        print(log_f.read())
        print(f'{COLOR_RED_BG} --- Proxy output end --- {COLOR_END}')
        raise Exception('Proxy is failed to startup')


def dump_controller_output() -> None:
    tmux(f'capture-pane -S - -pt {controller_pane_name} > {TARGET_TEST_FOLDER}/logs/controller.log')
    with open(f'{TARGET_TEST_FOLDER}/logs/controller.log') as log_f:
        print(f'{COLOR_RED_BG} --- Controller output --- {COLOR_END}')
        print(log_f.read())
        print(f'{COLOR_RED_BG} --- Controller output end --- {COLOR_END}')


def close_everything_and_save_logs() -> None:
    if os.path.exists(f'{TARGET_TEST_FOLDER}/logs'):
        tmux(f'capture-pane -S - -pt {mininet_pane_name} > {TARGET_TEST_FOLDER}/logs/mininet.log')
        tmux(f'capture-pane -S - -pt {controller_pane_name} > {TARGET_TEST_FOLDER}/logs/controller.log')
        tmux(f'capture-pane -S - -pt {proxy_pane_name} > {TARGET_TEST_FOLDER}/logs/proxy.log')
    tmux_shell(f'C-c', proxy_pane_name)
    tmux_shell(f'C-c', proxy_pane_name)
    tmux_shell(f'C-c', controller_pane_name)
    tmux_shell(f'C-c', mininet_pane_name)
    wait_for_output('^mininet>', mininet_pane_name)
    tmux_shell(f'quit', mininet_pane_name)
    wait_for_output('^mininet@mininet-vm', mininet_pane_name)
    tmux_shell(f'make stop', mininet_pane_name)
    wait_for_output('^mininet@mininet-vm', mininet_pane_name)
    tmux_shell(f'tmux kill-session -t {TMUX_WINDOW_NAME}')



def process_cmdline_testcase_name(cmdline_input: str) -> List[TestCase]:
    splitted_input = cmdline_input.split('/')

    if len(splitted_input) > 1 and splitted_input[1].strip() == '*':
        assert_folder_existence(f'testcases/{splitted_input[0]}')
        return [test_case for test_case in test_cases if test_case['name'] == splitted_input[0]]
    if len(splitted_input) > 1 and splitted_input[0].strip() == '*':
        return [test_case for test_case in test_cases if test_case['subtest'] == splitted_input[1]]
    else:
        ret = [{
            'name': splitted_input[0],
            'subtest': splitted_input[1] if len(splitted_input) > 1 else None
        }]

        if len(splitted_input) == 1:
            assert_folder_existence(f'testcases/{splitted_input[0]}')

        if len(splitted_input) > 1:
            assert_folder_existence(f'testcases/{splitted_input[0]}/subtests/{splitted_input[1]}')

        return ret


def sigint_handler(_signum, _frame) -> None:
    print(f'{COLOR_ORANGE}Ctrl-c was pressed! Cleaning up...{COLOR_END}')
    sys.exit(0)

signal.signal(signal.SIGINT, sigint_handler)


def build_up_p4_cache() -> None:
    print(f'{COLOR_CYAN}--- Building up P4 cache{COLOR_END} --- ')
    os.makedirs(BUILD_CACHE_FOLDER, exist_ok=True)

    def link_with_override(src: str, dst: str) -> None:
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


def print_all_missing_test_folders_in_test_case_list() -> None:
    for folder in (f.path for f in os.scandir('testcases') if f.is_dir()):
        test_name = folder.split(os.sep)[1]
        if not any(x for x in test_cases if x['name'] == test_name):
            print(f'{COLOR_YELLOW_BG}{test_name} is missing from test list{COLOR_END}')

        subtest_folder_path = f'{folder}{os.sep}subtests'
        if os.path.isdir(subtest_folder_path):
            for subtest_folder in (f.path for f in os.scandir(subtest_folder_path) if f.is_dir()):
                subtest_name = subtest_folder.split(os.sep)[-1]
                if not any(x for x in test_cases if x['name'] == test_name and x['subtest'] == subtest_name):
                    print(f'{COLOR_YELLOW_BG}{test_name}/{subtest_name} is missing from test list{COLOR_END}')


if len(sys.argv) == 1:
    build_up_p4_cache()
    try:
        if os.path.exists(TESTCASE_JSON_FILE_PATH):
            with open(TESTCASE_JSON_FILE_PATH, 'r') as testcase_json_file:
                testcase_config = TestcaseDescriptor.model_validate_json(testcase_json_file.read())
            try:
                index_of_testcase = [tc_i for tc_i, tc_v in enumerate(test_cases) if testcase_config.test_case == tc_v['name'] and testcase_config.subtest == tc_v['subtest']][0]
                test_cases = test_cases[index_of_testcase:] + test_cases[:index_of_testcase]
            except IndexError:
                pass
    finally:
        run_test_cases(test_cases)
        print_all_missing_test_folders_in_test_case_list()
else:
    if sys.argv[1] == 'help':
        print('python tester.py - run all the test cases')
        print('python tester.py [testcase] - run one test case ([test_name] or [test_name]/[subtest] form, e.g. l3fwd/simple_forward)')
        print('                              you can use wildcard for subtest to run all of the subtests for a test case e.g.: l3fwd/*')
        print('python tester.py build [testcase] - prepares the test folder with a testcase')
        print('python tester.py prepare - run the preparations for the actual content of the test folder (e.g. redis fill)')
        print('python tester.py release - create a release folder that contains all the necessary files to run the proxy without symlinks')
    elif sys.argv[1] == 'build':
        build_up_p4_cache()
        if len(sys.argv) < 3:
            raise Exception('For build a testcase you need to add 3 parameters')
        test_cases_to_build = process_cmdline_testcase_name(sys.argv[2])
        if len(test_cases_to_build) == 1:
            splitted_testcase = test_cases_to_build[0]
            prepare_test_folder(splitted_testcase['name'], splitted_testcase['subtest'])
        else:
            raise Exception('You cannot use wildcard for building a test case.')
    elif sys.argv[1] == 'prepare':
        prepare_environment()
    elif sys.argv[1] == 'release':
        clear_folder('release')
        shutil.copyfile('base/proxy.py', 'release/proxy.py')
        shutil.copyfile('requirements.txt', 'release/requirements.txt')
        shutil.copyfile('testcases/l3fwd/proxy_config.json', 'release/proxy_config.json')
        shutil.copytree('common','release/common')
    elif sys.argv[1] == 'saveredis':
        if len(sys.argv) < 3:
            raise Exception('For saveredis you have to pass a filename as well')
        redis_file = sys.argv[2]
        save_redis_to_json_file(redis_file)
    else:
        build_up_p4_cache()
        run_test_cases(process_cmdline_testcase_name(sys.argv[1]))

