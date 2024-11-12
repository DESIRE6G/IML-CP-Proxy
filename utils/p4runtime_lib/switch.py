# Copyright 2017-present Open Networking Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import functools
import os
import threading
import time
from abc import abstractmethod
from collections import deque
from datetime import datetime
from enum import Enum
from queue import Queue
from typing import Optional

import grpc
from p4.v1 import p4runtime_pb2, p4runtime_pb2_grpc

# List of all active connections
connections = []

def ShutdownAllSwitchConnections():
    for c in connections:
        c.shutdown()



class RateLimiter:
    def __init__(self, max_per_sec: int):
        self.last_tick = time.time()
        self.max_per_sec = max_per_sec
        self.bucket = 0

    def _decrease_bucket_base_on_time(self) -> None:
        self.bucket -= (time.time() - self.last_tick) * self.max_per_sec
        if self.bucket < 0:
            self.bucket = 0

        self.last_tick = time.time()

    def is_fit_in_the_rate_limit(self) -> bool:
        self._decrease_bucket_base_on_time()

        if self.bucket + 1 < self.max_per_sec:
            self.bucket += 1
            return True

        return False



class RateLimitedP4RuntimeStub:
    def __init__(self, channel, max_per_sec: int, buffer_size: Optional[int] = None) -> None:
        self.real_stub = p4runtime_pb2_grpc.P4RuntimeStub(channel)
        self.rate_limiter = RateLimiter(max_per_sec)

        self.buffer_size = 5 * max_per_sec if buffer_size is None else buffer_size

        self.buffered_commands = deque(maxlen=self.buffer_size)
        self.lock = threading.Lock()
        self.heartbeat_thread = threading.Thread(target=self.heartbeat)
        self.heartbeat_thread.start()

        commands = [x for x in dir(self.real_stub) if callable(getattr(self.real_stub, x)) and not x.startswith('_')]
        for command_name in commands:
            setattr(self, command_name, self.command_generate(command_name))

    def heartbeat(self) -> None:
        while True:
            with self.lock:
                self._flush_buffered_commands()
            time.sleep(1)

    def _flush_buffered_commands(self):
        while len(self.buffered_commands) > 0 and self.rate_limiter.is_fit_in_the_rate_limit():
            command = self.buffered_commands.popleft()
            getattr(self.real_stub, command[0])(*command[1], **command[2])

    def command_generate(self, command_name):
        def _inner(*args, **kwargs):
            with self.lock:
                if len(self.buffered_commands) == 0 and self.rate_limiter.is_fit_in_the_rate_limit():
                    return getattr(self.real_stub, command_name)(*args, **kwargs)
                else:
                    self.buffered_commands.append((command_name, args, kwargs))
                self._flush_buffered_commands()
        return _inner

class SwitchConnection(object):

    def __init__(self, name=None, address='127.0.0.1:50051', device_id=0,
                 proto_dump_file=None, rate_limit=None, rate_limiter_buffer_size=None, production_mode=False, p4_config_support=True):
        self.name = name
        self.address = address
        self.device_id = device_id
        self.p4info = None
        self.p4_config_support = p4_config_support
        self.channel = grpc.insecure_channel(self.address)
        if proto_dump_file is not None and not production_mode:
            interceptor = GrpcRequestLogger(proto_dump_file)
            self.channel = grpc.intercept_channel(self.channel, interceptor)

        self.rate_limit = rate_limit
        if rate_limit is None:
            self.client_stub = p4runtime_pb2_grpc.P4RuntimeStub(self.channel)
        else:
            self.client_stub = RateLimitedP4RuntimeStub(self.channel, max_per_sec=rate_limit, buffer_size=rate_limiter_buffer_size)
        self.requests_stream = IterableQueue()
        self.stream_msg_resp = self.client_stub.StreamChannel(iter(self.requests_stream))
        self.proto_dump_file = proto_dump_file
        connections.append(self)
        self.futures_pit = []

    @abstractmethod
    def buildDeviceConfig(self, **kwargs):
        if self.p4_config_support:
            from p4.tmp import p4config_pb2
            return p4config_pb2.P4DeviceConfig()
        else:
            return None

    def shutdown(self):
        self.requests_stream.close()
        self.stream_msg_resp.cancel()

    def MasterArbitrationUpdate(self, dry_run=False, election_id_low=1, **kwargs):
        request = p4runtime_pb2.StreamMessageRequest()
        request.arbitration.device_id = self.device_id
        request.arbitration.election_id.high = 0
        request.arbitration.election_id.low = election_id_low

        if dry_run:
            print("P4Runtime MasterArbitrationUpdate: ", request)
        else:
            self.requests_stream.put(request)
            for item in self.stream_msg_resp:
                return item # just one

    def SetForwardingPipelineConfig(self, p4info, dry_run=False, **kwargs):
        device_config = self.buildDeviceConfig(**kwargs)
        request = p4runtime_pb2.SetForwardingPipelineConfigRequest()
        request.election_id.low = 1
        request.device_id = self.device_id
        config = request.config

        config.p4info.CopyFrom(p4info)
        if device_config is not None:
            config.p4_device_config = device_config.SerializeToString()

        request.action = p4runtime_pb2.SetForwardingPipelineConfigRequest.VERIFY_AND_COMMIT
        if dry_run:
            print("P4Runtime SetForwardingPipelineConfig:", request)
        else:
            self.client_stub.SetForwardingPipelineConfig(request)

    def WriteTableEntry(self, table_entry, dry_run=False, update_type = 'INSERT'):
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
        if dry_run:
            print("P4Runtime Write:", request)
        else:
            self.client_stub.Write(request)


    def ReadTableEntries(self, table_id=None, dry_run=False):
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.device_id
        entity = request.entities.add()
        table_entry = entity.table_entry
        if table_id is not None:
            table_entry.table_id = table_id
        else:
            table_entry.table_id = 0
        if dry_run:
            print("P4Runtime Read:", request)
        else:
            for response in self.client_stub.Read(request):
                yield response

    def ReadCounters(self, counter_id=None, index=None, dry_run=False):
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
        if dry_run:
            print("P4Runtime Read:", request)
        else:
            for response in self.client_stub.Read(request):
                yield response

    def WriteCountersEntry(self, counter_entry, dry_run = False, verbose = False):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.MODIFY
        update.entity.counter_entry.CopyFrom(counter_entry)
        if dry_run:
            print("P4Runtime Write:", request)
        else:
            if verbose:
                print(request)
            self.client_stub.Write(request)

    def WriteDirectCounterEntry(self, direct_counter_entry, dry_run = False, verbose = False):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.MODIFY
        update.entity.direct_counter_entry.CopyFrom(direct_counter_entry)
        if dry_run:
            print("P4Runtime Write:", request)
        else:
            if verbose:
                print(request)
            self.client_stub.Write(request)

    def ReadDirectCounters(self, table_id=None, dry_run=False):
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.device_id
        entity = request.entities.add()
        direct_counter_entry = entity.direct_counter_entry
        if table_id is not None:
            direct_counter_entry.table_entry.table_id = table_id
        else:
            direct_counter_entry.table_entry.table_id = 0
        if dry_run:
            print("P4Runtime Read:", request)
        else:
            for response in self.client_stub.Read(request):
                yield response

    def ReadRegisterEntries(self, register_id=None, dry_run=False):
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.device_id
        entity = request.entities.add()
        register_entry = entity.register_entry
        if register_id is not None:
            register_entry.register_id = register_id
        else:
            register_entry.register_id = 0

        if dry_run:
            print("P4Runtime Read:", request)
        else:
            for response in self.client_stub.Read(request):
                yield response

    def ReadMeters(self, meter_id=None, index=None, dry_run=False):
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

        if dry_run:
            print("P4Runtime Read:", request)
        else:
            for response in self.client_stub.Read(request):
                yield response

    def WriteMeterEntry(self, meter_entry, dry_run = False):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.MODIFY
        update.entity.meter_entry.CopyFrom(meter_entry)
        if dry_run:
            print("P4Runtime Write:", request)
        else:
            self.client_stub.Write(request)

    def ReadDirectMeters(self, table_id, dry_run=False):
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.device_id
        entity = request.entities.add()
        direct_meter_entry = entity.direct_meter_entry
        direct_meter_entry.table_entry.table_id = table_id

        if dry_run:
            print("P4Runtime Read:", request)
        else:
            for response in self.client_stub.Read(request):
                yield response

    def WriteDirectMeterEntry(self, direct_meter_entry, dry_run = False):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.MODIFY
        update.entity.direct_meter_entry.CopyFrom(direct_meter_entry)
        if dry_run:
            print("P4Runtime Write:", request)
        else:
            print(request)
            self.client_stub.Write(request)

    def WriteDigest(self, digest_id: int):
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
        self.client_stub.Write(request)


    def WritePREEntry(self, pre_entry, dry_run=False):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.INSERT
        update.entity.packet_replication_engine_entry.CopyFrom(pre_entry)
        if dry_run:
            print("P4Runtime Write:", request)
        else:
            self.client_stub.Write(request)

    def WriteUpdates(self, updates, dry_run=False):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.device_id
        request.election_id.low = 1
        for update in updates:
            update_in_request = request.updates.add()
            update_in_request.CopyFrom(update)

        if dry_run:
            print("P4Runtime Write:", request)
        else:
            if self.rate_limit is None:
                self.futures_pit.append(self.client_stub.Write.future(request))

                for fut in self.futures_pit:
                    if fut.done():
                        fut.result()
                self.futures_pit = [fut for fut in self.futures_pit if not fut.done()]
            else:
                self.client_stub.Write(request)



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

class IterableQueue(Queue):
    _sentinel = object()

    def __iter__(self):
        return iter(self.get, self._sentinel)

    def close(self):
        self.put(self._sentinel)
