#!/usr/bin/env python3
import multiprocessing
import queue
import time
import numpy as np
from p4.v1 import p4runtime_pb2, p4runtime_pb2_grpc

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


class ProxyP4RuntimeServicer(P4RuntimeServicer):
    def __init__(self, target_client_stub) -> None:
        self.target_client_stub = target_client_stub

    def Write(self, request, context) -> None:
        self.target_client_stub.Write(request)
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


def start_dataplane_simulator(index: int, queue: multiprocessing.Queue, stop_event: multiprocessing.Event) -> None:
    port = 60051 + index
    target_port = 50051 + index
    target_address = f'127.0.0.1:{target_port}'

    channel = grpc.insecure_channel(target_address)
    target_client_stub = p4runtime_pb2_grpc.P4RuntimeStub(channel)
    servicer = ProxyP4RuntimeServicer(target_client_stub)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    add_P4RuntimeServicer_to_server(servicer, server)
    server.add_insecure_port(f'[::]:{port}')
    server.start()

    print(f'Opened GRPC: [::]:{port}')
    queue.put('ready')
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.stop(grace=True)


@dataclass
class DataplaneInfoObject:
    process: multiprocessing.Process
    queue: multiprocessing.Queue
    stop_event : multiprocessing.Event


with ControllerExceptionHandling():
    dataplanes: List[DataplaneInfoObject] = []

    for i in range(2):
        stop_event = multiprocessing.Event()
        queue = multiprocessing.Queue()
        process = multiprocessing.Process(target=start_dataplane_simulator, args=(i, queue, stop_event, ))
        dataplanes.append(
            DataplaneInfoObject(
                process=process,
                queue=queue,
                stop_event=stop_event
            )
        )
        process.start()

    for i in range(2):
        print(i, dataplanes[i].queue.get())
    print('Proxy is ready')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for dataplane in dataplanes:
            dataplane.stop_event.set()
        for dataplane in dataplanes:
            dataplane.process.join()