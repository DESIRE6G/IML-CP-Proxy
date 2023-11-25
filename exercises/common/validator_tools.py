import traceback

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

    def __error(self, message) -> None:
        print(f'ERROR: {message} at:')
        print(f'   >>> {get_caller_line()}')
        self._success = False

    def was_successful(self) -> bool:
        return self._success

    def should_be_true(self, a):
        if not a:
            self.__error(f'{a} is not True')

