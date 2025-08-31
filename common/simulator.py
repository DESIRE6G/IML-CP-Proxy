import inspect
import itertools
import sys
import time
from dataclasses import dataclass
from typing import Dict, Tuple, List, Callable, Any

import pandas as pd
import numpy as np
import os


@dataclass
class FunctionHolder:
    key: str
    function: Callable
    parameters: Dict[str, Any] = None


@dataclass
class ParameterHolder:
    key: str
    values: Dict[str, Any]


class SimulatorRerunCommand:
    def __init__(self, value):
        self.value = value

@dataclass
class SimulatorMultipleResult:
    results: Dict[str, Any]


class Simulator:
    """
    >>> from pandas.testing import assert_frame_equal
    >>> s = Simulator(add_runtimes=True)
    >>> s.add_parameter('x',[1,2,3])
    >>> s.add_function('test',lambda x: x*2)
    >>> df = s.run()
    >>> df['test'].to_list()
    [2, 4, 6]

    >>> s.add_function('test2',lambda x: str(x)+"hello")
    >>> df = s.run()
    >>> df['test2'].to_list()
    ['1hello', '2hello', '3hello']
    >>> s.add_parameter('y',[3,1,2])
    >>> df = s.run()
    >>> df['test'].to_list()
    [2, 2, 2, 4, 4, 4, 6, 6, 6]

    >>> s.add_function('test3',lambda x: str(x)+"hello")
    >>> s.add_function('test4',lambda test3: test3+" world")
    >>> df = s.run()
    >>> df['test3'].to_list()
    ['1hello', '1hello', '1hello', '2hello', '2hello', '2hello', '3hello', '3hello', '3hello']
    >>> df['test4'].to_list()
    ['1hello world', '1hello world', '1hello world', '2hello world', '2hello world', '2hello world', '3hello world', '3hello world', '3hello world']
    >>> list(df['test4'].index)
    [0, 1, 2, 3, 4, 5, 6, 7, 8]
    >>> list(df.columns)
    ['x', 'y', 'test', 'test2', 'test3', 'test4', 'test_runtime', 'test2_runtime', 'test3_runtime', 'test4_runtime']

    >>> def test5(x,y,random_parameter):
    ...     return x ** y + random_parameter
    >>> s.add_function('test5_5',test5,{'random_parameter':5})
    >>> s.add_function('test5_10',test5,{'random_parameter':10})
    >>> df = s.run()
    >>> df['test5_5'].to_list()
    [6, 6, 6, 13, 7, 9, 32, 8, 14]
    >>> df['test5_10'].to_list()
    [11, 11, 11, 18, 12, 14, 37, 13, 19]

    >>> s.add_condition('only_if_x_odd',lambda x: x % 2 == 1)
    >>> df = s.run()
    >>> df['test5_5'].to_list()
    [6, 6, 6, 32, 8, 14]
    >>> df['test3'].to_list()
    ['1hello', '1hello', '1hello', '3hello', '3hello', '3hello']
    """

    def __init__(self, auto_save_dataframe=True, max_core_num=1, verbose=False, max_rerun=2, add_runtimes=False, results_folder='results', results_filename='simulator_result'):
        self.parameters = []
        self.functions = []
        self.conditions = []
        self.functions_results = {}
        self.max_rerun = max_rerun
        self.auto_save_dataframe = auto_save_dataframe
        self.max_core_num = max_core_num
        self.verbose = verbose
        self.stop_flag = False
        self.add_runtimes = add_runtimes
        self.hidden_function_keys = []
        self.results_folder = results_folder
        self.results_filename = results_filename
        self.output_column_order = []

    def run(self, run_from=0):
        if self.auto_save_dataframe:
            self.archive_actual_result_csv()

        print('Parameters:')
        for parameter in self.parameters:
            print(f'\t{parameter.key}: {parameter.values}')

        table_data = []
        parameter_keys = [x.key for x in self.parameters]
        parameter_values = [x.values for x in self.parameters]
        all_case_count = np.prod([len(x) for x in parameter_values])
        case_counter = -1
        for actual_parameters_list in itertools.product(*parameter_values):
            case_counter += 1
            if case_counter < run_from:
                print("Skipping case", case_counter)
                continue
            actual_parameters, preprocessed_actual_parameters = self._prepare_parameters(parameter_keys, actual_parameters_list)

            if not self._check_condition_for_row(actual_parameters):
                continue

            function_results, runtime_array = self._execute_functions(actual_parameters)

            results_row = {}
            results_row.update(preprocessed_actual_parameters)
            results_row.update({k: None for k in self.output_column_order})
            results_row.update(function_results)
            if self.add_runtimes:
                results_row.update({f'{k}_runtime': v for k, v in runtime_array.items()})

            table_data.append(results_row)
            if self.verbose:
                print(case_counter, "of ", all_case_count, " done")
            self._save_to_csv_if_needed(table_data)

            if self.stop_flag:
                break

        if self.verbose:
            print(table_data)

        self._save_to_csv_if_needed(table_data)

        return pd.DataFrame.from_records(table_data)

    def _save_to_csv_if_needed(self, table_data):
        if self.auto_save_dataframe:
            pd.DataFrame.from_records(table_data).to_csv(f'{self.results_folder}/{self.results_filename}.csv')

    def archive_actual_result_csv(self):
        import shutil

        os.makedirs(self.results_folder, exist_ok=True)

        filename = self.results_filename
        if os.path.exists(f'{self.results_folder}/{self.results_filename}.csv'):
            i = 0
            while os.path.exists(f'{self.results_folder}/{filename}_{i}.csv'):
                i += 1
            filename += "_" + str(i)
            shutil.move(f'{self.results_folder}/{self.results_filename}.csv', f'{self.results_folder}/{filename}.csv')

    def _execute_functions(self, actual_parameters: Dict) -> Tuple[Dict, Dict]:
        actual_parameters_with_simulator = {'simulator': self}
        actual_parameters_with_simulator.update(actual_parameters)

        runtimes = {}
        functions_results = {}
        self.functions_results = {}
        for func_holder in self.functions:
            timer_start = time.time()
            actual_parameters_with_simulator_and_extra_parameters = {}
            actual_parameters_with_simulator_and_extra_parameters.update(actual_parameters_with_simulator)
            if func_holder.parameters is not None:
                actual_parameters_with_simulator_and_extra_parameters.update(func_holder.parameters)

            final_parameters = self.finalize_parameters("'" + str(func_holder.key) + "' func_holder",
                                                        actual_parameters_with_simulator_and_extra_parameters,
                                                        func_holder.function)
            result = None
            try:
                for run_try_counter in range(self.max_rerun+1):
                    result = func_holder.function(**final_parameters)

                    if not isinstance(result, SimulatorRerunCommand):
                        break
                    print(f"After {run_try_counter} try, received rerun command, so run again! (max rerun: {self.max_rerun})")
                if isinstance(result, SimulatorRerunCommand):
                    result = result.value

            except Exception as e:
                print("================", file=sys.stderr)
                print("Error!", file=sys.stderr)
                print("Actual parameters", final_parameters, file=sys.stderr)
                print("================", file=sys.stderr)
                raise e

            if isinstance(result, SimulatorMultipleResult):
                for subresult_key, subresult_value in result.results.items():
                    actual_parameters_with_simulator[subresult_key] = subresult_value
                    self.functions_results[subresult_key] = subresult_value

                    if func_holder.key not in self.hidden_function_keys:
                        functions_results[subresult_key] = subresult_value
            else:
                actual_parameters_with_simulator[func_holder.key] = result
                self.functions_results[func_holder.key] = result

                if func_holder.key not in self.hidden_function_keys:
                    functions_results[func_holder.key] = result
            runtimes[func_holder.key] = time.time() - timer_start

        return functions_results, runtimes

    def _prepare_parameters(self, parameter_keys: List, actual_parameters_list: List) -> Tuple[Dict, Dict]:
        actual_parameters = {}
        preprocessed_actual_parameter_list = {}
        for i in range(len(parameter_keys)):
            actual_parameter_key = parameter_keys[i]
            if callable(actual_parameters_list[i]):
                function = actual_parameters_list[i]
                final_parameters = self.finalize_parameters("'" + str(actual_parameter_key) + "' lambda parameter", actual_parameters, function)

                actual_parameters[actual_parameter_key] = actual_parameters_list[i](**final_parameters)
            else:
                actual_parameters[actual_parameter_key] = actual_parameters_list[i]

            preprocessed_actual_parameter_list[actual_parameter_key] = actual_parameters[actual_parameter_key]

        return actual_parameters, preprocessed_actual_parameter_list

    def stop(self):
        self.stop_flag = True

    @staticmethod
    def assert_parameters(function_identifier_name, actual_parameters, function):
        parameters_dict = inspect.signature(function).parameters
        arguments_of_the_function = [p for p in parameters_dict if parameters_dict[p].default == inspect.Parameter.empty]

        # print("Need: ",arguments_of_the_function)
        # print("Have: ",actual_parameters)

        extra_parameter_in_function = [element for element in arguments_of_the_function if
                                       element not in actual_parameters]
        if len(extra_parameter_in_function) > 0:
            raise Exception(
                "Extra argument of " + str(function_identifier_name) + ":" + ",".join(extra_parameter_in_function))

    def finalize_parameters(self, function_identifier_name, actual_parameters, function):
        self.assert_parameters(function_identifier_name, actual_parameters, function)
        arguments_of_the_function = [p for p in inspect.signature(function).parameters]

        missing_argument_of_function = [element for element in actual_parameters if
                                        element not in arguments_of_the_function]

        return {k: v for k, v in actual_parameters.items() if k not in missing_argument_of_function}

    def assert_callable_elements_parameters(self, key, values):
        for v in values:
            if callable(v):
                self.assert_parameters(key, [x.key for x in self.parameters], v)

    def add_parameter(self, key, values):
        self.assert_callable_elements_parameters(key, values)
        self.parameters.append(ParameterHolder(key, values))

    def add_function(self, key, func, parameters=None, hidden_function=False):
        all_previously_known_variable = self.get_known_parameters(parameters)
        if parameters is not None:
            all_previously_known_variable += list(parameters.keys())

        if self.verbose:
            print(all_previously_known_variable, self.parameters)

        # self.assert_parameters(key, all_previously_known_variable, func)
        self.functions.append(FunctionHolder(key, func, parameters))

        if hidden_function:
            self.hidden_function_keys.append(key)

    def get_known_parameters(self, parameters):
        return [x.key for x in self.parameters] + ['simulator'] + [x.key for x in self.functions]

    def get_function_result(self, func_name):
        if func_name in self.functions_results:
            return self.functions_results[func_name]
        else:
            raise Exception("Cannot find function '" + str(func_name) + "' result. Please consider the order how you pass to the simulator.")

    def add_condition(self, key, function):
        self.conditions.append(FunctionHolder(key, function))

    def _check_condition_for_row(self, actual_parameters):
        for c in self.conditions:
            final_parameters = self.finalize_parameters("'" + str(c.key) + "' function", actual_parameters, c.function)
            if not c.function(**final_parameters):
                return False
        return True

    def set_output_column_order(self, output_column_order):
        self.output_column_order = output_column_order
