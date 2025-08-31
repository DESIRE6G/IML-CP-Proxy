import time
from typing import Callable


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
