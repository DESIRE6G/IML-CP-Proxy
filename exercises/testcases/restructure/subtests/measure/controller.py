#!/usr/bin/env python3
import multiprocessing
import queue
import time
import numpy as np

from concurrent import futures
from dataclasses import dataclass
from typing import List, Tuple, Dict

import grpc
from p4.v1.p4runtime_pb2 import SetForwardingPipelineConfigResponse, ReadResponse, WriteResponse
from pydantic import BaseModel

from common.controller_helper import ControllerExceptionHandling, get_now_ts_us_int32, diff_ts_us_int32
from common.high_level_switch_connection import HighLevelSwitchConnection
from p4.v1 import p4runtime_pb2
from p4.v1.p4runtime_pb2_grpc import P4RuntimeServicer, add_P4RuntimeServicer_to_server

from common.rates import TickOutputJSON


class TickCounter:
    def __init__(self) -> None:
        self.counter = 0
        self.last_reset = time.time()
        self.last_tick_count = None

    def tick(self, counter_increment: int = 1) -> bool:
        self.counter += counter_increment
        now_time = time.time()
        if now_time - self.last_reset > 1:
            self.last_tick_count = self.counter
            self.counter = 0
            self.last_reset = now_time
            return True

        return False

    def get_last_tick_count(self) -> int:
        return self.last_tick_count


class DataCollector:
    def __init__(self) -> None:
        self.data : Dict[str, List] = {}

    def add(self, key: str, value: float) -> None:
        self.guarantee_key_existence(key)

        self.data[key].append(value)

    def guarantee_key_existence(self, key):
        if key not in self.data:
            self.data[key] = []

    def get_center_avg_stdev(self, key: str) -> Tuple[float, float]:
        return self._find_center_average_and_stdev(self.data[key])

    def _find_center_average_and_stdev(self, l: List) -> Tuple[float, float]:
        if len(l) == 1:
            return l[0], 0
        if len(l) == 2:
            return (l[0] + l[1])/2, 0
        if len(l) == 3:
            return sorted(l)[1], 0

        sorted_list = sorted(l)
        start = len(l) // 4
        end = len(l) // 4 * 3

        return sum(sorted_list[start:end]) / (end - start), np.std(sorted_list[start:end])

    def get_list(self, key: str) -> List[float]:
        return self.data[key]



class ContiniousAverageCalculator:
    def __init__(self) -> None:
        self.actual_average = None
        self.latency_divisor = None

    def add_value(self, value: float) -> None:
        if self.actual_average is None:
            self.actual_average = value
            self.latency_divisor = 1
        else:
            self.actual_average = (self.actual_average * self.latency_divisor) / (self.latency_divisor + 1) + value / (self.latency_divisor + 1)
            self.latency_divisor += 1

    def get_average(self) -> float:
        return self.actual_average

    def reset(self) -> None:
        self.actual_average = None
        self.latency_divisor = None


class ProxyP4RuntimeServicer(P4RuntimeServicer):
    def __init__(self, to_controller_queue: multiprocessing.Queue, servicer_id: str) -> None:
        self.write_counter = 0
        self.servicer_id = servicer_id
        self.tick_counter = TickCounter()
        self.to_controller_queue = to_controller_queue
        self.average_calculator = ContiniousAverageCalculator()
        self.data_collector = DataCollector()

    def Write(self, request, context) -> None:
        for update in request.updates:
            send_ts_us_int32 = int.from_bytes(update.entity.table_entry.action.action.params[0].value, 'big')
            now_ts_us_int32 = get_now_ts_us_int32()
            self.average_calculator.add_value(diff_ts_us_int32(send_ts_us_int32, now_ts_us_int32) / 1e6)

        if self.tick_counter.tick(len(request.updates)):
            self.data_collector.add('ticks', self.tick_counter.get_last_tick_count())
            average, stdev = self.data_collector.get_center_avg_stdev('ticks')
            self.data_collector.add('delay', self.average_calculator.get_average())
            delay_average, delay_stdev = self.data_collector.get_center_avg_stdev('delay')
            output = TickOutputJSON(
                tick_per_sec_list=self.data_collector.get_list('ticks'),
                average=average,
                stdev=stdev,
                delay_list=self.data_collector.get_list('delay'),
                delay_average=delay_average,
                delay_stdev=delay_stdev
            )
            with open('ticks.json', 'w') as f:
                f.write(output.model_dump_json(indent=4))
            self.to_controller_queue.put({
                'servicer_id': self.servicer_id,
                'ticks':self.data_collector.get_list('ticks'),
                'delay_average':delay_average
            })
            self.average_calculator.reset()

        return WriteResponse()

    def Read(self, original_request: p4runtime_pb2.ReadRequest, context):
        result = ReadResponse()
        yield result

    def SetForwardingPipelineConfig(self, request: p4runtime_pb2.SetForwardingPipelineConfigRequest, context):
        return SetForwardingPipelineConfigResponse()

    def GetForwardingPipelineConfig(self, request: p4runtime_pb2.GetForwardingPipelineConfigRequest, context):
        response = p4runtime_pb2.GetForwardingPipelineConfigResponse()
        return response


    def StreamChannel(self, request_iterator, context):
        for request in request_iterator:
            which_one = request.WhichOneof('update')
            if which_one == 'arbitration':
                response = p4runtime_pb2.StreamMessageResponse()
                response.arbitration.device_id = request.arbitration.device_id
                response.arbitration.election_id.high = 0
                response.arbitration.election_id.low = 1
                yield response
            else:
                raise Exception(f'Unhandled Stream field type {request.WhichOneof}')

    def Capabilities(self, request: p4runtime_pb2.CapabilitiesRequest, context):
        pass


def start_dataplane_simulator(port: int, to_controller_queue: multiprocessing.Queue, stop_event: multiprocessing.Event) -> None:
    servicer = ProxyP4RuntimeServicer(to_controller_queue, str(port))
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    add_P4RuntimeServicer_to_server(servicer, server)
    server.add_insecure_port(f'[::]:{port}')
    server.start()

    print(f'Opened GRPC: [::]:{port}')

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.stop(grace=True)


@dataclass
class DataplaneInfoObject:
    to_controller_queue: multiprocessing.Queue
    process: multiprocessing.Process
    stop_event : multiprocessing.Event


with ControllerExceptionHandling():
    dataplanes: List[DataplaneInfoObject] = []

    to_controller_queue = multiprocessing.Queue()
    for i in range(2):
        stop_event = multiprocessing.Event()
        process = multiprocessing.Process(target=start_dataplane_simulator, args=(50051 + i, to_controller_queue, stop_event, ))
        dataplanes.append(
            DataplaneInfoObject(
                to_controller_queue=to_controller_queue,
                process=process,
                stop_event=stop_event
            )
        )
        process.start()

    try:
        while True:
            ticks = to_controller_queue.get()
            print(ticks)
    except KeyboardInterrupt:
        for dataplane in dataplanes:
            dataplane.stop_event.set()
        for dataplane in dataplanes:
            dataplane.process.join()