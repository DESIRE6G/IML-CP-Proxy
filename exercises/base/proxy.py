import itertools
import json
import logging
import os.path
import signal
import sys
import time
from concurrent import futures
from enum import Enum
from threading import Thread, Event
from typing import Union

import grpc
from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2
from p4.v1.p4runtime_pb2 import SetForwardingPipelineConfigResponse, Update, WriteResponse, ReadResponse
from p4.v1.p4runtime_pb2_grpc import P4RuntimeServicer, add_P4RuntimeServicer_to_server
from google.protobuf.json_format import MessageToJson, Parse
from common.p4runtime_lib.helper import P4InfoHelper
import redis

from common.p4runtime_lib.switch import IterableQueue
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.redis_helper import RedisKeys, RedisRecords

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)
redis = redis.Redis()

def prefix_p4_name(original_p4_name : str, prefix : str) -> str:
    if not '.' in original_p4_name:
        return original_p4_name

    namespace,table_name = original_p4_name.split('.')

    return f'{namespace}.{prefix}{table_name}'

def remove_prefix_p4_name(prefixed_p4_name : str, prefix : str) -> str:
    if '.' not in prefixed_p4_name:
        return prefixed_p4_name

    namespace,table_name = prefixed_p4_name.split('.')
    if table_name.startswith(prefix):
        return f'{namespace}.{table_name[len(prefix):]}'
    else:
        raise Exception(f'Cannot find prefix "{prefix}" at the begining of the table name "{table_name}"')


def get_pure_table_name(original_table_name : str) -> str:
    namespace,table_name = original_table_name.split('.')

    return f'{table_name}'


class RedisMode(Enum):
    READWRITE = 'READWRITE'
    ONLY_WRITE = 'ONLY_WRITE'
    ONLY_READ = 'ONLY_READ'
    OFF = 'OFF'

    @classmethod
    def is_reading(cls, redis_mode: 'RedisMode') -> bool:
        return redis_mode == RedisMode.READWRITE or redis_mode == RedisMode.ONLY_READ

    @classmethod
    def is_writing(cls, redis_mode: 'RedisMode') -> bool:
        return redis_mode == RedisMode.READWRITE or redis_mode == RedisMode.ONLY_WRITE


class ProxyP4ServicerWorkerThread(Thread):
    def __init__(self, servicer) -> None:
        Thread.__init__(self)
        self.stopped = Event()
        self.servicer = servicer

    def run(self) -> None:
        while not self.stopped.wait(2):
            print(f'Heartbeat... {self.servicer.prefix}')
            if RedisMode.is_writing(self.servicer.redis_mode):
                self.servicer.save_counters_state_to_redis()

    def stop(self) -> None:
        self.stopped.set()

HandledEntityTypes = Union[
                           p4runtime_pb2.Entity,
                           p4runtime_pb2.CounterEntry,
                           p4runtime_pb2.DirectCounterEntry,
                           p4runtime_pb2.MeterEntry,
                           p4runtime_pb2.DirectMeterEntry,
                           p4runtime_pb2.RegisterEntry
                       ]

class ProxyP4RuntimeServicer(P4RuntimeServicer):
    def __init__(self, prefix, from_p4info_path, target_switch: HighLevelSwitchConnection, redis_mode: RedisMode):
        self.prefix = prefix
        if prefix.strip() != '':
            redis_prefix = prefix
        else:
            path_for_prefix = os.path.basename(from_p4info_path).split('.')[0]
            redis_prefix = f'{path_for_prefix}_'

        self.redis_keys = RedisKeys(
            TABLE_ENTRIES=f'{redis_prefix}{RedisRecords.TABLE_ENTRIES.postfix}',
            P4INFO= f'{redis_prefix}{RedisRecords.P4INFO.postfix}',
            COUNTER_ENTRIES=f'{redis_prefix}{RedisRecords.COUNTER_ENTRIES.postfix}',
            METER_ENTRIES=f'{redis_prefix}{RedisRecords.METER_ENTRIES.postfix}',
            HEARTBEAT=f'{redis_prefix}{RedisRecords.HEARTBEAT.postfix}'
        )

        self.from_p4info_helper = P4InfoHelper(from_p4info_path)
        self.requests_stream = IterableQueue()
        self.target_switch = target_switch
        self.redis_mode = redis_mode

        self.worker_thread = ProxyP4ServicerWorkerThread(self)
        self.worker_thread.start()

    def stop(self) -> None:
        self.worker_thread.stop()
        if RedisMode.is_writing(self.redis_mode):
            self.save_counters_state_to_redis()


    def Write(self, request, context, from_p4info_helper: P4InfoHelper = None, save_to_redis: bool = True) -> None:
        print('------------------- Write -------------------')
        print(request)

        for update in request.updates:
            if update.type == Update.INSERT or update.type == Update.MODIFY or update.type == Update.DELETE:
                entity = update.entity
                which_one = entity.WhichOneof('entity')
                if save_to_redis and RedisMode.is_writing(self.redis_mode):
                    if which_one == 'table_entry':
                        redis.rpush(self.redis_keys.TABLE_ENTRIES, MessageToJson(update))
                    elif which_one == 'meter_entry' or which_one == 'direct_meter_entry':
                        redis.rpush(self.redis_keys.METER_ENTRIES, MessageToJson(entity))

                self.convert_entity(entity, from_p4info_helper=from_p4info_helper)
            else:
                raise Exception(f'Unhandled update type {update.Type.Name(update.type)}')

        print('== SENDING')
        print(request)
        request.device_id = self.target_switch.device_id
        self.target_switch.connection.client_stub.Write(request)
        return WriteResponse()



    def convert_id(self,
                   id_type:str,
                   original_id: int,
                   reverse = False,
                   verbose=True,
                   from_p4info_helper: P4InfoHelper=None) -> int:

        if not reverse:
           from_p4info_helper_inner = self.from_p4info_helper if from_p4info_helper is None else from_p4info_helper
           target_p4info_helper = self.target_switch.p4info_helper
        else:
           from_p4info_helper_inner = self.target_switch.p4info_helper  if from_p4info_helper is None else from_p4info_helper
           target_p4info_helper = self.from_p4info_helper
        if id_type == 'table':
            name = from_p4info_helper_inner.get_tables_name(original_id)
        elif id_type == 'meter':
            name = from_p4info_helper_inner.get_meters_name(original_id)
        elif id_type == 'action':
            name = from_p4info_helper_inner.get_actions_name(original_id)
        elif id_type == 'counter':
            name = from_p4info_helper_inner.get_counters_name(original_id)
        elif id_type == 'register':
            name = from_p4info_helper_inner.get_registers_name(original_id)
        else:
            raise Exception(f'convert_id cannot handle "{id_type}" id_type')

        if verbose:
            print(f'name={name}')
        if reverse:
            new_name = remove_prefix_p4_name(name, self.prefix)
        else:
            new_name = prefix_p4_name(name, self.prefix)
        if verbose:
            print(f'new_name={new_name}')

        if id_type == 'table':
            return target_p4info_helper.get_tables_id(new_name)
        if id_type == 'meter':
            return target_p4info_helper.get_meters_id(new_name)
        elif id_type == 'action':
            return target_p4info_helper.get_actions_id(new_name)
        elif id_type == 'counter':
            return target_p4info_helper.get_counters_id(new_name)
        elif id_type == 'register':
            return target_p4info_helper.get_registers_id(new_name)
        else:
            raise Exception(f'convert_id cannot handle "{id_type}" id_type')



    def convert_table_entry(self,
                            entity: p4runtime_pb2.TableEntry,
                            reverse: bool=False,
                            verbose: bool=True,
                            from_p4info_helper: P4InfoHelper=None) -> None:
        if entity.table_entry.table_id != 0:
            entity.table_entry.table_id = self.convert_id('table', entity.table_entry.table_id,
                                                          reverse, verbose, from_p4info_helper)
        if entity.table_entry.HasField('action'):
            if entity.table_entry.action.WhichOneof('type') == 'action':
                entity.table_entry.action.action.action_id = self.convert_id('action', entity.table_entry.action.action.action_id,
                                                  reverse, verbose, from_p4info_helper)
            else:
                raise Exception(f'Unhandled action type {entity.table_entry.action.type}')

    def convert_meter_entry(self,
                            entity: p4runtime_pb2.MeterEntry,
                            reverse: bool=False,
                            verbose: bool=True,
                            from_p4info_helper: P4InfoHelper=None) -> None:
        if entity.meter_entry.meter_id != 0:
            entity.meter_entry.meter_id = self.convert_id('meter', entity.meter_entry.meter_id,
                                                          reverse, verbose, from_p4info_helper)
    def convert_direct_meter_entry(self,
                                   entity: p4runtime_pb2.DirectMeterEntry,
                                   reverse: bool=False,
                                   verbose: bool=True,
                                   from_p4info_helper: P4InfoHelper=None) -> None:
        if entity.direct_meter_entry.table_entry.table_id != 0:
            entity.direct_meter_entry.table_entry.table_id = self.convert_id('table', entity.direct_meter_entry.table_entry.table_id,
                                                          reverse, verbose, from_p4info_helper)


    def convert_counter_entry(self,
                              entity: p4runtime_pb2.CounterEntry,
                              reverse: bool=False,
                              verbose: bool=True,
                              from_p4info_helper: P4InfoHelper=None) -> None:
        if entity.counter_entry.counter_id != 0:
            entity.counter_entry.counter_id = self.convert_id('counter', entity.counter_entry.counter_id,
                                                      reverse, verbose, from_p4info_helper)


    def convert_direct_counter_entry(self,
                                     entity: p4runtime_pb2.DirectCounterEntry,
                                     reverse: bool=False,
                                     verbose: bool=True,
                                     from_p4info_helper: P4InfoHelper=None) -> None:
        if entity.direct_counter_entry.table_entry.table_id != 0:
            entity.direct_counter_entry.table_entry.table_id = self.convert_id('table', entity.direct_counter_entry.table_entry.table_id,
                                                      reverse, verbose, from_p4info_helper)

    def convert_register_entry(self,
                               entity: p4runtime_pb2.RegisterEntry,
                               reverse: bool=False,
                               verbose: bool=True,
                               from_p4info_helper: P4InfoHelper=None) -> None:
        if entity.table_entry.table_id != 0:
            entity.counter_entry.counter_id = self.convert_id('register', entity.register_entry.register_id,
                                                          reverse, verbose, from_p4info_helper)

    def convert_entity(self,
                       entity: HandledEntityTypes,
                       reverse: bool=False,
                       verbose: bool=True,
                       from_p4info_helper: P4InfoHelper=None) -> None:
        which_one = entity.WhichOneof('entity')
        if which_one == 'table_entry':
            self.convert_table_entry(entity, reverse, verbose, from_p4info_helper)
        elif which_one == 'counter_entry':
            self.convert_counter_entry( entity, reverse, verbose, from_p4info_helper)
        elif which_one == 'direct_counter_entry':
            self.convert_direct_counter_entry( entity, reverse, verbose, from_p4info_helper)
        elif which_one == 'meter_entry':
            self.convert_meter_entry(entity, reverse, verbose, from_p4info_helper)
        elif which_one == 'direct_meter_entry':
            self.convert_direct_meter_entry(entity, reverse, verbose, from_p4info_helper)
        elif which_one == 'register_entry':
            self.convert_register_entry(entity, reverse, verbose, from_p4info_helper)
        else:
            raise Exception(f'Not implemented type for read "{which_one}"')

    def convert_read_request(self,
                             request: p4runtime_pb2.ReadRequest,
                             verbose: bool=True) -> None:
        for entity in request.entities:
            self.convert_entity(entity, reverse=False,verbose=verbose)


    def get_entity_name(self, p4info_helper: P4InfoHelper, entity: HandledEntityTypes) -> str:
        which_one = entity.WhichOneof('entity')
        if which_one == 'table_entry':
            return p4info_helper.get_tables_name(entity.table_entry.table_id)
        elif which_one == 'counter_entry':
            return p4info_helper.get_counters_name(entity.counter_entry.counter_id)
        elif which_one == 'direct_counter_entry':
            return p4info_helper.get_tables_name(entity.direct_counter_entry.table_entry.table_id)
        elif which_one == 'meter_entry':
            return p4info_helper.get_meters_name(entity.meter_entry.meter_id)
        elif which_one == 'direct_meter_entry':
            return p4info_helper.get_tables_name(entity.direct_meter_entry.table_entry.table_id)
        else:
            raise Exception(f'Not implemented type for read "{which_one}"')

    def Read(self, request: p4runtime_pb2.ReadRequest, context):
        """Read one or more P4 entities from the target.
        """
        print('------------------- Read -------------------')
        if len(request.entities) == 1:
            ret = ReadResponse()
            print('request:')
            print(request)
            self.convert_read_request(request)
            request.device_id = self.target_switch.device_id
            print('converted_request:')
            print(request)
            for result in self.target_switch.connection.client_stub.Read(request):
                print('result:')
                print(result)
                for entity in result.entities:
                    entity_name = self.get_entity_name(self.target_switch.p4info_helper,entity)
                    if get_pure_table_name(entity_name).startswith(self.prefix):
                        self.convert_entity(entity, reverse=True)
                        ret_entity = ret.entities.add()
                        ret_entity.CopyFrom(entity)


            yield ret
        else:
            raise Exception(f"Read only handles when requested everything")

    def SetForwardingPipelineConfig(self, request: p4runtime_pb2.SetForwardingPipelineConfigRequest, context):
        # Do not forward p4info just save it, on init we load the p4info
        self.delete_redis_entries_for_this_service()
        if RedisMode.is_writing(self.redis_mode):
            redis.set(self.redis_keys.P4INFO,MessageToString(request.config.p4info))

        return SetForwardingPipelineConfigResponse()

    def GetForwardingPipelineConfig(self, request: p4runtime_pb2.GetForwardingPipelineConfigRequest, context):
        """Gets the current P4 forwarding-pipeline config.
        """
        print('GetForwardingPipelineConfig')
        print(request)
        print(context)
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def StreamChannel(self, request_iterator, context):
        return iter([])

    def Capabilities(self, request: p4runtime_pb2.CapabilitiesRequest, context):
        # missing associated documentation comment in .proto file
        print('Capabilities')
        print(request)
        print(context)
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def fill_from_redis(self) -> None:
        print('FILLING FROM REDIS')
        raw_p4info = redis.get(self.redis_keys.P4INFO)
        if raw_p4info is None:
            print('Fillig from redis failed, because p4info cannot be found in redis')
            return

        redis_p4info_helper = P4InfoHelper(raw_p4info=raw_p4info)
        for protobuf_message_json_object in redis.lrange(self.redis_keys.TABLE_ENTRIES,0,-1):
            parsed_update_object = Parse(protobuf_message_json_object, p4runtime_pb2.Update())
            print(parsed_update_object)
            self._write_update_object(parsed_update_object, redis_p4info_helper)

        for protobuf_message_json_object in itertools.chain(redis.lrange(self.redis_keys.COUNTER_ENTRIES, 0, -1),
                                                            redis.lrange(self.redis_keys.METER_ENTRIES, 0, -1),
                                                            ):
            entity = Parse(protobuf_message_json_object, p4runtime_pb2.Entity())
            print(entity)

            update = p4runtime_pb2.Update()
            update.type = p4runtime_pb2.Update.MODIFY
            update.entity.CopyFrom(entity)
            self._write_update_object(update, redis_p4info_helper)

    def _write_update_object(self, update_object, from_p4info_helper):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.target_switch.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.CopyFrom(update_object)
        self.Write(request, None, from_p4info_helper, save_to_redis=False)

    def delete_redis_entries_for_this_service(self) -> None:
        redis.delete(self.redis_keys.TABLE_ENTRIES)
        redis.delete(self.redis_keys.COUNTER_ENTRIES)
        redis.delete(self.redis_keys.HEARTBEAT)

    def save_counters_state_to_redis(self) -> None:
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.target_switch.connection.device_id

        for direct_counter in self.from_p4info_helper.p4info.direct_counters:
            entity = request.entities.add()
            entity.direct_counter_entry.table_entry.table_id = direct_counter.direct_table_id
            self.convert_entity(entity)

        entity = request.entities.add()
        entity.counter_entry.counter_id = 0
        with redis.pipeline() as pipe:
            pipe.multi()
            pipe.delete(self.redis_keys.COUNTER_ENTRIES)
            print('-----------REQUEST')
            print(request)
            print('-----------REQUESTEND')
            for response in self.target_switch.connection.client_stub.Read(request):
                for entity in response.entities:
                    entity_name = self.get_entity_name(self.target_switch.p4info_helper,entity)
                    if get_pure_table_name(entity_name).startswith(self.prefix):
                        print(entity)
                        self.convert_entity(entity, reverse=True)
                        pipe.rpush(self.redis_keys.COUNTER_ENTRIES, MessageToJson(entity))

            pipe.execute()

        print(self.redis_keys.HEARTBEAT, time.time())
        redis.set(self.redis_keys.HEARTBEAT, time.time())



class ProxyServer:
    def __init__(self, port, prefix, from_p4info_path, target_switch: HighLevelSwitchConnection, redis_mode: RedisMode):
        self.port = port
        self.prefix = prefix
        self.from_p4info_path = from_p4info_path
        self.target_switch = target_switch
        self.server = None
        self.servicer = None
        self.redis_mode = redis_mode

    def start(self) -> None:
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        self.servicer = ProxyP4RuntimeServicer(self.prefix, self.from_p4info_path, self.target_switch, self.redis_mode)
        if RedisMode.is_reading(self.redis_mode):
            self.servicer.fill_from_redis()
        add_P4RuntimeServicer_to_server(self.servicer, self.server)
        self.server.add_insecure_port(f'[::]:{self.port}')
        self.server.start()

    def stop(self) -> None:
        self.servicer.stop()
        self.server.stop(grace=None)

class ProxyConfig:
    def __init__(self, filename = 'proxy_config.json') -> None:
        with open(filename) as f:
            self.proxy_config = json.load(f)

    def get_redis_mode(self) -> RedisMode:
        return RedisMode(self.proxy_config['redis'])

    def get_mappings(self) -> dict:
        return self.proxy_config['mappings']

proxy_config = ProxyConfig()
mappings = proxy_config.get_mappings()
servers = []

def serve(port, prefix, p4info_path, target_switch: HighLevelSwitchConnection, redis_mode: RedisMode):
    global servers
    proxy_server = ProxyServer(port, prefix, p4info_path, target_switch, redis_mode)
    proxy_server.start()
    servers.append(proxy_server)

for mapping in mappings:
    target_config = mapping['target']
    reset_dataplane = 'reset_dataplane' in target_config and target_config['reset_dataplane']
    mapping_target_switch = HighLevelSwitchConnection(target_config['device_id'], target_config['program_name'], target_config['port'], send_p4info=True, reset_dataplane=reset_dataplane)
    print('On startup the rules on the target are the following')
    for response in mapping_target_switch.connection.ReadTableEntries():
        for starter_entity in response.entities:
            entry = starter_entity.table_entry
            print(mapping_target_switch.p4info_helper.get_tables_name(entry.table_id))
            print(entry)
            print('-----')


    sources = mapping['sources']
    for source in sources:
        p4_info_path = f"build/{source['program_name']}.p4.p4info.txt"
        serve(source['controller_port'], prefix=source['prefix'], p4info_path=p4_info_path, target_switch=mapping_target_switch, redis_mode=proxy_config.get_redis_mode())

    if 'preload_entries' in mapping:
        for entry in mapping['preload_entries']:
            entry_type = entry['type']
            if entry_type == 'table':
                table_entry = mapping_target_switch.p4info_helper.buildTableEntry(**entry['parameters'])
                mapping_target_switch.connection.WriteTableEntry(table_entry)
            elif entry_type == 'meter':
                meter_entry = mapping_target_switch.p4info_helper.buildMeterConfigEntry(**entry['parameters'])
                mapping_target_switch.connection.WriteMeterEntry(meter_entry)
            elif entry_type == 'direct_meter':
                meter_entry = mapping_target_switch.p4info_helper.buildDirectMeterConfigEntry(**entry['parameters'])
                mapping_target_switch.connection.WriteDirectMeterEntry(meter_entry)
            elif entry_type == 'counter':
                counter_entry = mapping_target_switch.p4info_helper.buildCounterEntry(**entry['parameters'])
                mapping_target_switch.connection.WriteCountersEntry(counter_entry)
            elif entry_type == 'direct_counter':
                counter_entry = mapping_target_switch.p4info_helper.buildDirectCounterEntry(**entry['parameters'])
                mapping_target_switch.connection.WriteDirectCounterEntry(counter_entry)
            else:
                raise Exception(f'Preload does not handle {entry_type} yet, inform the author to add what you need.')

def sigint_handler(signum, frame):
    global servers
    for server in servers:
        server.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, sigint_handler)


try:
    # Important message for the testing system, do not remove :)
    print('Proxy is ready')
    while True:
        time.sleep(60 * 60)
except KeyboardInterrupt:
    for server in servers:
        server.stop(0)

