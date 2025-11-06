#!/usr/bin/env python3
import argparse
import multiprocessing
import time
from p4.v1 import p4runtime_pb2_grpc

from concurrent import futures
from dataclasses import dataclass
from typing import List

import grpc
from p4.v1.p4runtime_pb2 import WriteResponse

from common.controller_helper import ControllerExceptionHandling
from p4.v1 import p4runtime_pb2
from p4.v1.p4runtime_pb2_grpc import P4RuntimeServicer, add_P4RuntimeServicer_to_server

from common.p4runtime_lib.switch import IterableQueue


class ProxyP4RuntimeServicer(P4RuntimeServicer):
    def __init__(self, target_client_stub) -> None:
        self.target_client_stub = target_client_stub
        self.futures_pit = []

    def Write(self, request, context) -> None:
        self.futures_pit.append(self.target_client_stub.Write.future(request))

        done_fut = []
        for fut in self.futures_pit:
            if fut.done():
                fut.result()
                done_fut.append(fut)
        self.futures_pit = [fut for fut in self.futures_pit if fut not in done_fut]
        return WriteResponse()

    def Read(self, original_request: p4runtime_pb2.ReadRequest, context):
        for res in self.target_client_stub.Read(original_request):
            yield res

    def SetForwardingPipelineConfig(self, request: p4runtime_pb2.SetForwardingPipelineConfigRequest, context):
        return self.target_client_stub.SetForwardingPipelineConfig(request)

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

    requests_stream = IterableQueue()
    stream_msg_resp = target_client_stub.StreamChannel(iter(requests_stream))

    request = p4runtime_pb2.StreamMessageRequest()
    request.arbitration.device_id = 0
    request.arbitration.election_id.high = 0
    request.arbitration.election_id.low = 1

    requests_stream.put(request)
    print(request)

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

parser = argparse.ArgumentParser(prog='Fake Proxy')
parser.add_argument('--proxy_size', default=2, type=int)
args = parser.parse_args()


with ControllerExceptionHandling():
    dataplanes: List[DataplaneInfoObject] = []

    for i in range(args.proxy_size):
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

    for i in range(args.proxy_size):
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