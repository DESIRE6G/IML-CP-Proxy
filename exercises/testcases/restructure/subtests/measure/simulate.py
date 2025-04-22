import os
import shutil
import time
from functools import partial

import numpy as np
import pandas as pd

from common.colors import COLOR_RED_BG, COLOR_END
from common.proxy_config import ProxyConfig
from common.rates import TickOutputJSON
from common.simulator import Simulator, SimulatorMultipleResult
from common.tmuxing import tmux, tmux_shell, wait_for_output, close_everything_and_save_logs, create_tmux_window_with_retry

iter_num = 1
#for case in ['sending_rate_changing', 'batch_size_changing', 'sending_rate_changing_multi_sender', 'batch_delay_test', 'unbalanced_flow', 'multi_sender']:
for case in ['test']:
    simulator = Simulator(results_folder='../results', results_filename=case)
    PROXY_CONFIG_FILENAME = 'proxy_config.json'
    BACKUP_PROXY_CONFIG_FILENAME = f'{PROXY_CONFIG_FILENAME}.original'
    TMUX_WINDOW_NAME = 'simulate'
    controller_pane_name = f'{TMUX_WINDOW_NAME}:0.0'
    proxy_pane_name = f'{TMUX_WINDOW_NAME}:0.1'
    validator_pane_name = f'{TMUX_WINDOW_NAME}:0.2'

    simulator.set_output_column_order([
            'message_per_sec_mean', 'delay_average',
            'average_by_table.part1', 'average_by_table.part2', 'average_by_table.part3', 'average_by_table.part4',
            'delay_average_by_table.part1','delay_average_by_table.part2','delay_average_by_table.part3','delay_average_by_table.part4'
    ])

    if case == 'sending_rate_changing':
        simulator.add_parameter('iteration', list(range(1,iter_num + 1)))
        simulator.add_parameter('sending_rate', [200 * (i + 1) for i in range(15)])
        simulator.add_parameter('mode', ['without_proxy', 'fake_proxy', 'real_proxy'])
        simulator.add_parameter('target_port', [lambda mode: 50051 if mode == 'without_proxy' else 60051])
        simulator.add_parameter('fake_proxy', [lambda mode: mode == 'fake_proxy'])
    elif case == 'batch_size_changing':
        simulator.add_parameter('iteration', list(range(1,iter_num + 1)))
        simulator.add_parameter('batch_size', [2 ** i  for i in range(18)])
        simulator.add_parameter('mode', ['without_proxy', 'fake_proxy', 'real_proxy'])
        simulator.add_parameter('target_port', [lambda mode: 50051 if mode == 'without_proxy' else 60051])
        simulator.add_parameter('fake_proxy', [lambda mode: mode == 'fake_proxy'])
    elif case == 'sending_rate_changing_multi_sender':
        simulator.add_parameter('iteration', list(range(1,iter_num + 1)))
        simulator.add_parameter('sending_rate', [200 * (i + 1) for i in range(15)])
        simulator.add_parameter('sender_num', [1, 2, 3, 4])
        simulator.add_parameter('batch_delay', [None, 0.0001] )
    elif case == 'test':
        simulator.add_parameter('iteration', list(range(1,iter_num + 1)))
        simulator.add_parameter('sending_rate', [None])
        simulator.add_parameter('sender_num', [1,2,3,4])
        simulator.add_parameter('fake_proxy', ['simple', 'async'])
        simulator.add_parameter('batch_delay', [None] )
    elif case == 'batch_delay_test':
        simulator.add_parameter('iteration', list(range(1,iter_num + 1)))
        simulator.add_parameter('sending_rate', [None])
        simulator.add_parameter('batch_delay', [None] + [0.0001 * (2 ** i) for i in range(16)])
        simulator.add_parameter('sender_num', [1, 2, 3, 4])
    elif case == 'unbalanced_flow':
        simulator.add_parameter('iteration', list(range(1,iter_num + 1)))
        simulator.add_parameter('sending_rate', [200])
        simulator.add_parameter('dominant_sender_rate_limit', list(range(100,1400,20)))
        simulator.add_parameter('sender_num', [3])
        simulator.add_parameter('batch_delay', [None, 0.0001] )
    elif case == 'multi_sender':
        simulator.add_parameter('iteration', list(range(1,iter_num + 1)))
        simulator.add_parameter('sending_rate', [None])
        simulator.add_parameter('sender_num', [1,2,3,4])
        simulator.add_parameter('rate_limit', [250, 500, 750, 1000, 1250, 1500, None])
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
            dominant_sender_rate_limit=None,
            proxy_source_worker_num=None
        ) -> SimulatorMultipleResult:
        try:
            with open(BACKUP_PROXY_CONFIG_FILENAME, 'r') as f:
                obj = ProxyConfig.model_validate_json(f.read())

            if rate_limit is not None:
                obj.mappings[0].target.rate_limit = rate_limit
            if rate_limiter_buffer_size is not None:
                obj.mappings[0].target.rate_limiter_buffer_size = rate_limiter_buffer_size
            if batch_delay is not None:
                obj.mappings[0].target.batch_delay = batch_delay
            if proxy_source_worker_num is not None:
                for i in range(4):
                    obj.mappings[0].sources[i].worker_num = proxy_source_worker_num

            with open(PROXY_CONFIG_FILENAME, 'w') as f:
                f.write(obj.model_dump_json(indent=2, exclude_none=True))

            create_tmux_window_with_retry(TMUX_WINDOW_NAME)
            if fake_proxy and sender_num > 1:
                tmux_shell(f'python controller.py --dataplane_num {sender_num}', controller_pane_name)
            else:
                tmux_shell(f'python controller.py', controller_pane_name)

            time.sleep(1)

            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.0 -v -p60')
            tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.1 -v -p50')

            if fake_proxy == 'async':
                tmux_shell('python fake_proxy_async.py', proxy_pane_name)
            elif fake_proxy == 'simple' or fake_proxy:
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

        results={
            'message_per_sec_mean': obj.average,
            'stdev': obj.stdev,
            'delay_average': obj.delay_average,
            'delay_stdev': obj.delay_stdev,
            'ticks': obj.tick_per_sec_list
        }

        for table_name in obj.average_by_table:
            results[f'average_by_table.{table_name}'] = obj.average_by_table[table_name]

        for table_name in obj.stdev_by_table:
            results[f'stdev_by_table.{table_name}'] = obj.stdev_by_table[table_name]

        for table_name in obj.delay_average_by_table:
            results[f'delay_average_by_table.{table_name}'] = obj.delay_average_by_table[table_name]

        for table_name in obj.delay_stdev_by_table:
            results[f'delay_stdev_by_table.{table_name}'] = obj.delay_stdev_by_table[table_name]

        return SimulatorMultipleResult(results=results)

    simulator.add_function('message_per_sec_mean', measure)

    try:
        shutil.move(PROXY_CONFIG_FILENAME, BACKUP_PROXY_CONFIG_FILENAME)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.max_rows', None)
        print(simulator.run())
    finally:
        shutil.move(BACKUP_PROXY_CONFIG_FILENAME, PROXY_CONFIG_FILENAME)