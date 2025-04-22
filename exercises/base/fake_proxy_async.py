#!/usr/bin/env python3
import argparse
import asyncio
import logging
import multiprocessing
import time
import traceback

from p4.v1 import p4runtime_pb2, p4runtime_pb2_grpc

from concurrent import futures
from dataclasses import dataclass
from typing import List, Tuple, Dict, Iterable, AsyncIterable

import grpc
import grpc.aio
from p4.v1.p4runtime_pb2 import SetForwardingPipelineConfigResponse

from common.controller_helper import ControllerExceptionHandling
from p4.v1 import p4runtime_pb2
from p4.v1.p4runtime_pb2_grpc import P4RuntimeServicer, add_P4RuntimeServicer_to_server

from common.p4runtime_lib.switch import IterableQueue


class ProxyP4RuntimeServicer(P4RuntimeServicer):
    def __init__(self, target_client_stub) -> None:
        self.target_client_stub = target_client_stub

    async def Write(self, request, context) -> None:
        asyncio.ensure_future(self.target_client_stub.Write(request))
        return p4runtime_pb2.WriteResponse()

    async def Read(self, original_request: p4runtime_pb2.ReadRequest, context):
        print('Read')
        # for res in self.target_client_stub.Read(original_request):
        #     yield res

    async def SetForwardingPipelineConfig(self, request: p4runtime_pb2.SetForwardingPipelineConfigRequest, context):
        print('SetForwardingPipelineConfig')
        return SetForwardingPipelineConfigResponse()
        # return await self.target_client_stub.SetForwardingPipelineConfig(request)

    async def GetForwardingPipelineConfig(self, request: p4runtime_pb2.GetForwardingPipelineConfigRequest, context):
        print('GetForwardingPipelineConfig')
        # response = p4runtime_pb2.GetForwardingPipelineConfigResponse()
        # return response


    async def StreamChannel(
            self,
            request_iterator: AsyncIterable[p4runtime_pb2.StreamMessageRequest],
            context: grpc.ServicerContext
        ) -> AsyncIterable[p4runtime_pb2.StreamMessageResponse]:
        try:
            print('StreamChannel')

            async for request in request_iterator:
                print('ARRIVED')
                print(request)
                which_one = request.WhichOneof('update')
                if which_one == 'arbitration':
                    response = p4runtime_pb2.StreamMessageResponse()
                    response.arbitration.device_id = request.arbitration.device_id
                    response.arbitration.election_id.high = 0
                    response.arbitration.election_id.low = 1
                    yield response
                else:
                    raise Exception(f'Unhandled Stream field type {request.WhichOneof}')
        except Exception as e:
            print(traceback.format_exc())
            print(e)

    async def Capabilities(self, request: p4runtime_pb2.CapabilitiesRequest, context):
        pass





def start_dataplane_simulator(index: int, queue: multiprocessing.Queue, stop_event: multiprocessing.Event) -> None:
    async def dataplane_simulator_async_main():
        port = 60051 + index
        target_port = 50051 + index
        target_address = f'127.0.0.1:{target_port}'

        channel = grpc.aio.insecure_channel(target_address)
        target_client_stub = p4runtime_pb2_grpc.P4RuntimeStub(channel)
        #
        # requests_stream = IterableQueue()
        # stream_msg_resp = target_client_stub.StreamChannel(iter(requests_stream))
        #
        # request = p4runtime_pb2.StreamMessageRequest()
        # request.arbitration.device_id = 0
        # request.arbitration.election_id.high = 0
        # request.arbitration.election_id.low = 1
        #
        # requests_stream.put(request)
        # print(request)

        servicer = ProxyP4RuntimeServicer(target_client_stub)
        server = grpc.aio.server()
        add_P4RuntimeServicer_to_server(servicer, server)
        server.add_insecure_port(f'[::]:{port}')
        await server.start()

        print(f'Opened GRPC: [::]:{port}')
        queue.put('ready')
        try:
            await server.wait_for_termination()
        finally:
            await server.stop(10)

    asyncio.run(dataplane_simulator_async_main())



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

