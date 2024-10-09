import os
import shutil
import time

from common.colors import COLOR_RED_BG, COLOR_END
from common.proxy_config import ProxyConfig
from common.rates import TickOutputJSON
from common.simulator import Simulator
from common.tmuxing import tmux, tmux_shell, wait_for_output, close_everything_and_save_logs

simulator = Simulator()
PROXY_CONFIG_FILENAME = 'proxy_config.json'
BACKUP_PROXY_CONFIG_FILENAME = f'{PROXY_CONFIG_FILENAME}.original'
TMUX_WINDOW_NAME = 'simulate'
controller_pane_name = f'{TMUX_WINDOW_NAME}:0.0'
proxy_pane_name = f'{TMUX_WINDOW_NAME}:0.1'
validator_pane_name = f'{TMUX_WINDOW_NAME}:0.2'

simulator.add_parameter('rate_limit', [50, None])

def measure(rate_limit) -> None:
    try:
        print(rate_limit)
        with open(BACKUP_PROXY_CONFIG_FILENAME, 'r') as f:
            obj = ProxyConfig.model_validate_json(f.read())

        obj.mappings[0].target.rate_limit = rate_limit

        with open(PROXY_CONFIG_FILENAME, 'w') as f:
            f.write(obj.model_dump_json(indent=4))

        tmux(f'new -d -s {TMUX_WINDOW_NAME} -x 150')
        tmux_shell(f'python controller.py', controller_pane_name)
        time.sleep(1)

        tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.0 -v -p60')
        tmux(f'split-window -P -t {TMUX_WINDOW_NAME}:0.1 -v -p50')

        tmux_shell('python proxy.py', proxy_pane_name)
        try:
            wait_for_output('^Proxy is ready', proxy_pane_name)
        except TimeoutError:
            print(f'{COLOR_RED_BG}Proxy is failed to startup{COLOR_END}')

        tmux_shell('python validator.py', validator_pane_name)

        time.sleep(10)

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

simulator.add_function('measure', measure)
try:
    shutil.move(PROXY_CONFIG_FILENAME, BACKUP_PROXY_CONFIG_FILENAME)
    simulator.run()
finally:
    shutil.move(BACKUP_PROXY_CONFIG_FILENAME, PROXY_CONFIG_FILENAME)