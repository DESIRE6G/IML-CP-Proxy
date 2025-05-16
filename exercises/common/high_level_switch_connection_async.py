import asyncio
import socket
import time
from abc import abstractmethod
from dataclasses import dataclass
from queue import Queue
from typing import Any, Optional, List, Union

from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2
from pydantic import BaseModel

import common.p4runtime_lib.bmv2
import common.p4runtime_lib.helper

import os
from datetime import datetime
from queue import Queue
from typing import Optional, List, Union

import grpc
from p4.v1 import p4runtime_pb2, p4runtime_pb2_grpc



# List of all active connections
connections = []

def ShutdownAllSwitchConnections():
    for c in connections:
        c.shutdown()

class IterableAsyncQueue(asyncio.Queue):
    _sentinel = object()

    def __iter__(self):
        return iter(self.get, self._sentinel)

    def close(self):
        self.put(self._sentinel)

    async def __aiter__(self):
        try:
            while True:
                yield await self.get()
        except Exception:
            return


class SwitchConnection(object):

    def __init__(self, name=None, address='127.0.0.1:50051', device_id=0,
                 proto_dump_file=None, rate_limit=None, rate_limiter_buffer_size=None,
                 production_mode=True, p4_config_support=True,
                 batch_delay: Optional[float] = None):
        self.name = name
        self.address = address
        self.device_id = device_id
        self.p4info = None
        self.p4_config_support = p4_config_support
        self.channel = grpc.aio.insecure_channel(self.address)

        self.rate_limit = rate_limit

        self.client_stub = p4runtime_pb2_grpc.P4RuntimeStub(self.channel)
        self.proto_dump_file = proto_dump_file
        connections.append(self)

        self.requests_stream = IterableAsyncQueue()
        self.stream_msg_resp = self.client_stub.StreamChannel(self.requests_stream.__aiter__())

        if batch_delay is None:
            self.WriteUpdates_batcher = None
        else:
            self.WriteUpdates_batcher = Batcher(self.WriteUpdates_inner, batch_delay)

    def purge_rate_limiter_buffer(self) -> None:
        pass


    async def MasterArbitrationUpdate(self, election_id_low):
        request = p4runtime_pb2.StreamMessageRequest()
        request.arbitration.device_id = self.device_id
        request.arbitration.election_id.high = 0
        request.arbitration.election_id.low = election_id_low

        await self.requests_stream.put(request)
        async for item in self.stream_msg_resp:
            return item # just one

    async def SetForwardingPipelineConfig(self, p4info, **kwargs):
        device_config = self.buildDeviceConfig(**kwargs)
        request = p4runtime_pb2.SetForwardingPipelineConfigRequest()
        request.election_id.low = 1
        request.device_id = self.device_id
        config = request.config

        config.p4info.CopyFrom(p4info)
        if device_config is not None:
            config.p4_device_config = device_config.SerializeToString()

        request.action = p4runtime_pb2.SetForwardingPipelineConfigRequest.VERIFY_AND_COMMIT
        await self.client_stub.SetForwardingPipelineConfig(request)

    async def WriteTableEntry(self, table_entry, update_type = 'INSERT'):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        if table_entry.is_default_action or update_type == 'MODIFY':
            update.type = p4runtime_pb2.Update.MODIFY
        elif update_type == 'DELETE':
            update.type = p4runtime_pb2.Update.DELETE
        else:
            update.type = p4runtime_pb2.Update.INSERT
        update.entity.table_entry.CopyFrom(table_entry)
        await self.client_stub.Write(request)


    async def ReadTableEntries(self, table_id=None):
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.device_id
        entity = request.entities.add()
        table_entry = entity.table_entry
        if table_id is not None:
            table_entry.table_id = table_id
        else:
            table_entry.table_id = 0

        async for response in self.client_stub.Read(request):
            yield response

    async def ReadCounters(self, counter_id=None, index=None):
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.device_id
        entity = request.entities.add()
        counter_entry = entity.counter_entry
        if counter_id is not None:
            counter_entry.counter_id = counter_id
        else:
            counter_entry.counter_id = 0
        if index is not None:
            counter_entry.index.index = index
        async for response in self.client_stub.Read(request):
            yield response

    async def WriteCountersEntry(self, counter_entry):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.MODIFY
        update.entity.counter_entry.CopyFrom(counter_entry)
        self.client_stub.Write(request)

    async def WriteDirectCounterEntry(self, direct_counter_entry):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.MODIFY
        update.entity.direct_counter_entry.CopyFrom(direct_counter_entry)
        await self.client_stub.Write(request)

    async def ReadDirectCounters(self, table_id=None):
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.device_id
        entity = request.entities.add()
        direct_counter_entry = entity.direct_counter_entry
        if table_id is not None:
            direct_counter_entry.table_entry.table_id = table_id
        else:
            direct_counter_entry.table_entry.table_id = 0
        async for response in self.client_stub.Read(request):
            yield response

    async def ReadRegisterEntries(self, register_id=None):
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.device_id
        entity = request.entities.add()
        register_entry = entity.register_entry
        if register_id is not None:
            register_entry.register_id = register_id
        else:
            register_entry.register_id = 0

        async for response in self.client_stub.Read(request):
            yield response

    async def ReadMeters(self, meter_id=None, index=None):
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.device_id
        entity = request.entities.add()
        meter_entry = entity.meter_entry
        if meter_entry is not None:
            meter_entry.meter_id = meter_id
        else:
            meter_entry.meter_id = 0

        if index is not None:
            meter_entry.index.index = index

        async for response in self.client_stub.Read(request):
            yield response

    async def WriteMeterEntry(self, meter_entry):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.MODIFY
        update.entity.meter_entry.CopyFrom(meter_entry)
        await self.client_stub.Write(request)

    async def ReadDirectMeters(self, table_id):
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.device_id
        entity = request.entities.add()
        direct_meter_entry = entity.direct_meter_entry
        direct_meter_entry.table_entry.table_id = table_id

        async for response in self.client_stub.Read(request):
            yield response

    async def WriteDirectMeterEntry(self, direct_meter_entry):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.MODIFY
        update.entity.direct_meter_entry.CopyFrom(direct_meter_entry)
        await self.client_stub.Write(request)

    async def WriteDigest(self, digest_id: int):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.INSERT
        digest_entry = update.entity.digest_entry
        digest_entry.digest_id = digest_id
        digest_entry.config.max_timeout_ns = 0
        digest_entry.config.max_list_size = 1
        digest_entry.config.ack_timeout_ns = 0
        await self.client_stub.Write(request)

    async def WriteUpdates(self, updates):
        if self.WriteUpdates_batcher is None:
            await self.WriteUpdates_inner(updates)
        else:
            self.WriteUpdates_batcher.add_elements(updates)

    async def WriteUpdates_inner(self, updates: List[p4runtime_pb2.Entity]):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        for update in updates:
            update_in_request = request.updates.add()
            update_in_request.CopyFrom(update)

        await self.client_stub.Write(request)

    @abstractmethod
    def buildDeviceConfig(self, **kwargs):
        if self.p4_config_support:
            from p4.tmp import p4config_pb2
            return p4config_pb2.P4DeviceConfig()
        else:
            return None

class GrpcRequestLogger(grpc.UnaryUnaryClientInterceptor,
                        grpc.UnaryStreamClientInterceptor):
    """Implementation of a gRPC interceptor that logs request to a file"""

    def __init__(self, log_file):
        self.log_file = log_file
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        with open(self.log_file, 'w') as f:
            # Clear content if it exists.
            f.write("")

    def log_message(self, method_name, body):
        with open(self.log_file, 'a') as f:
            ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            msg = str(body)
            f.write("\n[%s] %s\n---\n" % (ts, method_name))
            f.write(str(body))
            f.write('---\n')

    def intercept_unary_unary(self, continuation, client_call_details, request):
        self.log_message(client_call_details.method, request)
        return continuation(client_call_details, request)

    def intercept_unary_stream(self, continuation, client_call_details, request):
        self.log_message(client_call_details.method, request)
        return continuation(client_call_details, request)


def buildDeviceConfig(bmv2_json_file_path=None):
    from p4.tmp import p4config_pb2
    "Builds the device config for BMv2"
    device_config = p4config_pb2.P4DeviceConfig()
    device_config.reassign = True
    with open(bmv2_json_file_path) as f:
        device_config.device_data = f.read().encode('utf-8')
    return device_config

class Bmv2SwitchConnection(SwitchConnection):
    def buildDeviceConfig(self, **kwargs):
        if self.p4_config_support:
            return buildDeviceConfig(**kwargs)
        else:
            return None



class EnviromentSettins(BaseModel):
    production_mode: bool = False
    p4_config_support: bool = True

if socket.gethostname() == 'dpdk-switch':
    enviroment_settings = EnviromentSettins(
        production_mode = True,
        p4_config_support = False
    )
else:
    enviroment_settings = EnviromentSettins()

class HighLevelSwitchConnection:
    def __init__(self,
                 device_id: int,
                 filename: str,
                 port: Optional[Union[int, str]] = None,
                 send_p4info: bool = True,
                 reset_dataplane: bool = True,
                 election_id_low: int=1,
                 p4info_path: Optional[str] = None,
                 bmv2_file_path: Optional[str] = None,
                 rate_limit: Optional[int] = None,
                 rate_limiter_buffer_size: Optional[int] = None,
                 production_mode: Optional[bool] = None,
                 p4_config_support: Optional[bool] = None,
                 batch_delay: Optional[float] = None
                 ):
        self.device_id = device_id
        self.filename = filename
        self.election_id_low = election_id_low
        self.send_p4info = send_p4info
        self.reset_dataplane = reset_dataplane

        if p4info_path is not None:
            self.p4info_path = p4info_path
        else:
            self.p4info_path = f'./build/{self.filename}.p4.p4info.txt'

        if bmv2_file_path is not None:
            self.bmv2_file_path = bmv2_file_path
        else:
            self.bmv2_file_path = f'./build/{self.filename}.json'
        self.p4info_helper = common.p4runtime_lib.helper.P4InfoHelper(self.p4info_path)

        self.port = f'5005{device_id+1}' if port is None else port

        self.connection = Bmv2SwitchConnection(
            name=f's{device_id+1}',
            address=f'127.0.0.1:{self.port}',
            device_id=device_id,
            proto_dump_file=f'logs/port{self.port}-p4runtime-requests.txt',
            rate_limit=rate_limit,
            rate_limiter_buffer_size=rate_limiter_buffer_size,
            production_mode=enviroment_settings.production_mode if production_mode is None else production_mode,
            p4_config_support=enviroment_settings.p4_config_support if p4_config_support is None else p4_config_support,
            batch_delay=batch_delay
        )

    async def init(self):
        await self.connection.MasterArbitrationUpdate(election_id_low=self.election_id_low)

        if self.send_p4info:
            send_p4info_second_level = True
            try:
                if not self.reset_dataplane:
                    request = p4runtime_pb2.GetForwardingPipelineConfigRequest()
                    request.device_id = self.device_id
                    actual_p4info_raw = self.connection.client_stub.GetForwardingPipelineConfig(request)
                    actual_p4info = MessageToString(actual_p4info_raw.config.p4info)

                    if actual_p4info == MessageToString(self.p4info_helper.p4info):
                        send_p4info_second_level = False
            except:
                pass

            if send_p4info_second_level:
                await self.connection.SetForwardingPipelineConfig(p4info=self.p4info_helper.p4info,
                                               bmv2_json_file_path=self.bmv2_file_path)

    def stop(self) -> None:
        pass

    def subscribe_to_stream_with_queue(self, queue: Queue, extra_information: Optional[Any] = None) -> None:
        pass

    def unsubscribe_from_stream_with_queue(self, queue: Queue) -> None:
        pass
