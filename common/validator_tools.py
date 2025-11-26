import difflib
import traceback
from typing import Tuple

from common.colors import COLOR_RED, COLOR_END


def get_caller_line() -> str:
    stack = traceback.extract_stack(limit=4)
    return traceback.format_list(stack)[0].split('\n')[1].strip()

class Validator:
    def __init__(self):
        self._success = True

    def should_be_equal(self, a, b) -> None:
        if a != b:
            self.__error(f'{a} is not equal with {b}')

    def should_be_not_equal(self, a, b) -> None:
        if a == b:
            self.__error(f'{a} is equal with {b}')

    def should_be_greater(self, a, b) -> None:
        if a <= b:
            self.__error(f'{a} is lower or equal than {b}')

    def should_be_in_order(self, a, b, c) -> None:
        if not (a <= b <= c):
            self.__error(f'{a} {b} {c} is not in order')

    def __error(self, message) -> None:
        print(f'ERROR: {message} at:')
        print(f'   >>> {get_caller_line()}')
        self._success = False

    def was_successful(self) -> bool:
        return self._success

    def should_be_true(self, a):
        if not a:
            self.__error(f'{a} is not True')


def diff_strings(actual_rebuilt: str, expected_rebuilt: str) -> Tuple[str, str]:
    actual_packet_arrived_colored = ''
    color_active = False
    diff_flags = ''
    i = 0
    for s in difflib.ndiff(actual_rebuilt, expected_rebuilt):
        if s[0] == '-':
            continue

        if s[0] == '+':
            if not color_active:
                actual_packet_arrived_colored += COLOR_RED
                color_active = True
            diff_flags += '^'
        else:
            if color_active:
                actual_packet_arrived_colored += COLOR_END
                color_active = False
            diff_flags += ' '

        if i < len(actual_rebuilt):
            actual_packet_arrived_colored += actual_rebuilt[i]
        else:
            if not color_active:
                actual_packet_arrived_colored += COLOR_RED
                color_active = True
            actual_packet_arrived_colored += '#'
        i += 1

    while i < len(actual_rebuilt):
        if not color_active:
            actual_packet_arrived_colored += COLOR_RED
            color_active = True
        actual_packet_arrived_colored += actual_rebuilt[i]
        diff_flags += '^'
        i += 1
    while i < len(expected_rebuilt):
        if not color_active:
            actual_packet_arrived_colored += COLOR_RED
            color_active = True
        actual_packet_arrived_colored += '#'
        diff_flags += '^'
        i += 1

    if color_active:
        actual_packet_arrived_colored += COLOR_END

    return actual_packet_arrived_colored, diff_flags
