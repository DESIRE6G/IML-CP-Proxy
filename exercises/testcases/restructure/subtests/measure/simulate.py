import os
import shutil
import time
from functools import partial

import numpy as np
import pandas as pd

from common.colors import COLOR_RED_BG, COLOR_END
from common.proxy_config import ProxyConfig
from common.rates import TickOutputJSON
from common.simulator import Simulator
from common.tmuxing import tmux, tmux_shell, wait_for_output, close_everything_and_save_logs, create_tmux_window_with_retry

#for case in ['sending_rate_changing', 'fake_proxy', 'batch_size_changing', 'buffer_size_changing', 'batch_delay_test']:
for case in ['batch_delay_test']:
    simulator = Simulator(results_folder='../results', results_filename=case)
    PROXY_CONFIG_FILENAME = 'proxy_config.json'
    BACKUP_PROXY_CONFIG_FILENAME = f'{PROXY_CONFIG_FILENAME}.original'
    TMUX_WINDOW_NAME = 'simulate'
    controller_pane_name = f'{TMUX_WINDOW_NAME}:0.0'
    proxy_pane_name = f'{TMUX_WINDOW_NAME}:0.1'
    validator_pane_name = f'{TMUX_WINDOW_NAME}:0.2'

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
    elif case == 'unbalanced_flow':
        simulator.add_parameter('sending_rate', [200])
        simulator.add_parameter('dominant_sender_rate_limit', list(range(100,1400,20)))
        simulator.add_parameter('iteration', list(range(1,11)))
        simulator.add_parameter('batch_size', [1])
        simulator.add_parameter('sender_num', [3])
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
            fake_proxy=False,
            dominant_sender_rate_limit=None
        ) -> float:
        try:
            with open(BACKUP_PROXY_CONFIG_FILENAME, 'r') as f:
                obj = ProxyConfig.model_validate_json(f.read())

            if rate_limit is not None:
                obj.mappings[0].target.rate_limit = rate_limit
            if rate_limiter_buffer_size is not None:
                obj.mappings[0].target.rate_limiter_buffer_size = rate_limiter_buffer_size
            if batch_delay is not None:
                obj.mappings[0].target.batch_delay = batch_delay

            with open(PROXY_CONFIG_FILENAME, 'w') as f:
                f.write(obj.model_dump_json(indent=2, exclude_none=True))

            create_tmux_window_with_retry(TMUX_WINDOW_NAME)
            tmux_shell(f'python controller.py', controller_pane_name)
            time.sleep(1)

            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.0 -v -p60')
            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.1 -v -p50')

            if fake_proxy:
                tmux_shell('python fake_proxy.py', proxy_pane_name)
            else:
                tmux_shell('python proxy.py', proxy_pane_name)
            try:
                wait_for_output('^Proxy is ready', proxy_pane_name)
            except TimeoutError:
                print(f'{COLOR_RED_BG}Proxy is failed to startup{COLOR_END}')

            validator_cmd = f'python validator.py --batch_size {batch_size} --sender_num {sender_num}'
            if sending_rate is not None:
                validator_cmd += f' --rate_limit {sending_rate}'
            if target_port is not None:
                validator_cmd += f' --target_port {target_port}'
            if dominant_sender_rate_limit is not None:
                validator_cmd += f' --dominant_sender_rate_limit {dominant_sender_rate_limit}'

            tmux_shell(validator_cmd, validator_pane_name)

            time.sleep(30)

            os.remove(PROXY_CONFIG_FILENAME)
        finally:
            close_everything_and_save_logs(TMUX_WINDOW_NAME, {
                'controller': controller_pane_name,
                'proxy': proxy_pane_name,
                'validator': validator_pane_name
            })

        with open('ticks.json', 'r') as f:
            obj = TickOutputJSON.model_validate_json(f.read())
            print(obj.average)

        return obj.average

    simulator.add_function('message_per_sec_mean', measure)

    def extract_variable(field_name):
        with open('ticks.json', 'r') as f:
            obj = TickOutputJSON.model_validate_json(f.read())


        try:
            actual_obj = obj
            for field_name_element in field_name.split('.'):
                print(f'extract {field_name_element} from {actual_obj}')
                if isinstance(actual_obj, dict):
                    actual_obj = actual_obj[field_name_element]
                else:
                    actual_obj = getattr(actual_obj, field_name_element)

            print(f'result {actual_obj}')
            return actual_obj
        except KeyError:
            return None

    simulator.add_function('stdev', partial(extract_variable, 'stdev'))
    simulator.add_function('delay_average', partial(extract_variable, 'delay_average'))
    simulator.add_function('delay_stdev', partial(extract_variable, 'delay_stdev'))
    simulator.add_function('ticks', partial(extract_variable, 'tick_per_sec_list'))

    for i in range(1,4):
        simulator.add_function(f'average_by_table.part{i}', partial(extract_variable, f'average_by_table.part{i}'))
        simulator.add_function(f'stdev_by_table.part{i}', partial(extract_variable, f'stdev_by_table.part{i}'))
        simulator.add_function(f'delay_average_by_table.part{i}', partial(extract_variable, f'delay_average_by_table.part{i}'))
        simulator.add_function(f'delay_stdev_by_table.part{i}', partial(extract_variable, f'delay_stdev_by_table.part{i}'))

    try:
        shutil.move(PROXY_CONFIG_FILENAME, BACKUP_PROXY_CONFIG_FILENAME)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.max_rows', None)
        print(simulator.run())
    finally:
        shutil.move(BACKUP_PROXY_CONFIG_FILENAME, PROXY_CONFIG_FILENAME)