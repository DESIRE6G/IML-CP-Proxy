import os
import shutil
import time

import numpy as np
import pandas as pd

from common.colors import COLOR_RED_BG, COLOR_END
from common.proxy_config import ProxyConfig
from common.rates import TickOutputJSON
from common.simulator import Simulator
from common.sync import wait_for_condition_blocking
from common.tmuxing import tmux, tmux_shell, wait_for_output, close_everything_and_save_logs, create_tmux_window_with_retry
from common.tester_config import TestConfig

for case in ['sending_rate_changing', 'fake_proxy', 'batch_size_changing', 'buffer_size_changing', 'batch_delay_test']:
#for case in ['buffer_size_changing']:
    simulator = Simulator(results_folder='../results', results_filename=case)
    PROXY_CONFIG_FILENAME = 'proxy_config.json'
    BACKUP_PROXY_CONFIG_FILENAME = f'{PROXY_CONFIG_FILENAME}.original'
    TEST_CONFIG_FILENAME = 'test_config.json'
    BACKUP_TEST_CONFIG_FILENAME = f'{TEST_CONFIG_FILENAME}.original'
    TMUX_WINDOW_NAME = 'simulate'
    mininet_pane_name = f'{TMUX_WINDOW_NAME}:0.0'
    proxy_pane_name = f'{TMUX_WINDOW_NAME}:0.1'
    controller_pane_name = f'{TMUX_WINDOW_NAME}:0.2'
    validator_pane_name = f'{TMUX_WINDOW_NAME}:0.3'

    if case == 'sending_rate_changing':
        simulator.add_parameter('sending_rate', [200 * (i + 1) for i in range(15)])
        simulator.add_parameter('iteration', [1])
        simulator.add_parameter('rate_limiter_buffer_size', [None])
        simulator.add_parameter('batch_delay', [None])
        simulator.add_parameter('target_port', [50051, 60051])
    elif case == 'fake_proxy':
        simulator.add_parameter('iteration', [1])
        simulator.add_parameter('sending_rate', [200 * (i + 1) for i in range(15)])
        simulator.add_parameter('fake_proxy', [True, False])
    elif case == 'batch_size_changing':
        simulator.add_parameter('sending_rate', [None])
        simulator.add_parameter('rate_limit', [None])
        simulator.add_parameter('rate_limiter_buffer_size', [None])
        simulator.add_parameter('batch_size', [2 ** i  for i in range(18)])
        simulator.add_parameter('iteration', [1])
        simulator.add_parameter('target_port', [50051, 60051])
    elif case == 'buffer_size_changing':
        simulator.add_parameter('sending_rate', [200])
        simulator.add_parameter('iteration', [1])
        simulator.add_parameter('rate_limit', [100])
        simulator.add_parameter('rate_limiter_buffer_size', [0, 100, 500, 100000])
        simulator.add_parameter('batch_size', [1])
    elif case == 'batch_delay_test':
        simulator.add_parameter('sending_rate', [None])
        simulator.add_parameter('iteration', [1])
        simulator.add_parameter('batch_size', [1])
        simulator.add_parameter('batch_delay', [None] + [0.0001 * (2 ** i) for i in range(15)])
        simulator.add_parameter('sender_num', [1, 2, 3])
    else:
        raise Exception(f'unknown case "{case}"')

    def measure(
            rate_limit=None,
            batch_size=1,
            sending_rate=None,
            sender_num=1,
            rate_limiter_buffer_size=None,
            target_port=None,
            batch_delay=None,
            fake_proxy=False
        ) -> float:
        try:
            for filename in ['.controller_finished', '.controller_ready', '.pcap_receive_finished', '.pcap_receive_started', '.pcap_send_started'] + \
                ['ticks.json', 'send_h1.log', 'receive.log', 'test_output.json']:
                if os.path.exists(filename):
                    os.remove(filename)
            shutil.rmtree('logs', ignore_errors=True)

            with open(BACKUP_PROXY_CONFIG_FILENAME, 'r') as f:
                proxy_config = ProxyConfig.model_validate_json(f.read())
            with open(BACKUP_TEST_CONFIG_FILENAME, 'r') as f:
                test_config = TestConfig.model_validate_json(f.read())

            if rate_limit is not None:
                proxy_config.mappings[0].target.rate_limit = rate_limit
            if rate_limiter_buffer_size is not None:
                proxy_config.mappings[0].target.rate_limiter_buffer_size = rate_limiter_buffer_size
            if batch_delay is not None:
                proxy_config.mappings[0].target.batch_delay = batch_delay

            with open(PROXY_CONFIG_FILENAME, 'w') as f:
                f.write(proxy_config.model_dump_json(indent=2, exclude_none=True))

            with open(TEST_CONFIG_FILENAME, 'w') as f:
                f.write(test_config.model_dump_json(indent=2, exclude_none=True))

            create_tmux_window_with_retry(TMUX_WINDOW_NAME)

            tmux_shell(f'make run', mininet_pane_name)
            wait_for_output('^mininet>', mininet_pane_name, max_time=30)

            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.0 -v -p60')
            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.1 -v -p50')

            if target_port is None or int(target_port) > 60000:
                if fake_proxy:
                    tmux_shell('python fake_proxy.py', proxy_pane_name)
                else:
                    tmux_shell('python proxy.py', proxy_pane_name)
                try:
                    wait_for_output('^Proxy is ready', proxy_pane_name)
                except TimeoutError:
                    print(f'{COLOR_RED_BG}Proxy is failed to startup{COLOR_END}')
                time.sleep(1)



            controller_cmd = f'python controller.py --batch_size {batch_size} --sender_num {sender_num}'
            if sending_rate is not None:
                controller_cmd += f' --rate_limit {sending_rate}'
            if target_port is not None:
                controller_cmd += f' --target_port {target_port}'

            tmux_shell(controller_cmd, controller_pane_name)
            wait_for_condition_blocking(lambda: os.path.exists('.controller_ready'), max_time=30)
            tmux_shell(f'h2 python test_receive.py > receive.log 2>&1 &', mininet_pane_name, wait_command_appear=True)
            wait_for_output('^mininet>', mininet_pane_name)
            wait_for_condition_blocking(lambda : os.path.exists(f'.pcap_receive_started'))
            tmux_shell('h1 python test_send.py > send_h1.log 2>&1 &', mininet_pane_name)

            wait_for_condition_blocking(lambda: os.path.exists('.controller_finished'), max_time=30)

            os.remove(PROXY_CONFIG_FILENAME)
            os.remove(TEST_CONFIG_FILENAME)

        finally:
            close_everything_and_save_logs(TMUX_WINDOW_NAME, {
                'controller': controller_pane_name,
                'proxy': proxy_pane_name,
                'mininet': mininet_pane_name
            })



        with open('ticks.json', 'r') as f:
            proxy_config = TickOutputJSON.model_validate_json(f.read())
            print(proxy_config.average)

        return proxy_config.average

    simulator.add_function('message_per_sec_mean', measure)


    def stdev():
        with open('ticks.json', 'r') as f:
            obj = TickOutputJSON.model_validate_json(f.read())

        return obj.stdev
    simulator.add_function('stdev', stdev)

    def delay_average():
        with open('ticks.json', 'r') as f:
            obj = TickOutputJSON.model_validate_json(f.read())

        return obj.delay_average
    simulator.add_function('delay_average', delay_average)

    def delay_stdev():
        with open('ticks.json', 'r') as f:
            obj = TickOutputJSON.model_validate_json(f.read())

        return obj.delay_stdev
    simulator.add_function('delay_stdev', delay_stdev)

    def ticks():
        with open('ticks.json', 'r') as f:
            obj = TickOutputJSON.model_validate_json(f.read())
        return obj.tick_per_sec_list
    simulator.add_function('ticks', ticks)

    try:
        shutil.move(PROXY_CONFIG_FILENAME, BACKUP_PROXY_CONFIG_FILENAME)
        shutil.move(TEST_CONFIG_FILENAME, BACKUP_TEST_CONFIG_FILENAME)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.max_rows', None)
        print(simulator.run())
    finally:
        shutil.move(BACKUP_PROXY_CONFIG_FILENAME, PROXY_CONFIG_FILENAME)
        shutil.move(BACKUP_TEST_CONFIG_FILENAME, TEST_CONFIG_FILENAME)
