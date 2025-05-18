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
        new_request = p4runtime_pb2.WriteRequest()
        new_request.device_id = 0
        new_request.election_id.low = 1
        for update in request.updates:
            update_in_request = new_request.updates.add()
            update_in_request.CopyFrom(update)
        asyncio.ensure_future(self.target_client_stub.Write(new_request))
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


async def dataplane_simulator_async_main(index: int) -> asyncio.Task:
    port = 60051 + index
    target_port = 50051 + index
    target_address = f'127.0.0.1:{target_port}'

    channel = grpc.aio.insecure_channel(target_address)
    target_client_stub = p4runtime_pb2_grpc.P4RuntimeStub(channel)

    servicer = ProxyP4RuntimeServicer(target_client_stub)
    server = grpc.aio.server()
    add_P4RuntimeServicer_to_server(servicer, server)
    server.add_insecure_port(f'[::]:{port}')
    await server.start()
    print(f'Opened GRPC: [::]:{port}')

    async def terminate_async():
        try:
            await server.wait_for_termination()
        finally:
            await server.stop(10)

    return asyncio.create_task(terminate_async())

parser = argparse.ArgumentParser(prog='Fake Proxy')
parser.add_argument('--proxy_size', default=2, type=int)
args = parser.parse_args()

with ControllerExceptionHandling():
    async def async_main():
        tasks = [await dataplane_simulator_async_main(i) for i in range(args.proxy_size)]
        print('Proxy is ready')

        await asyncio.gather(*tasks)

    asyncio.run(async_main())
