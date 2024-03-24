import itertools
import logging
import os.path
import queue
import signal
import sys
import time
from concurrent import futures
from dataclasses import dataclass
from enum import Enum
from threading import Thread, Event
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel

import grpc
from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2
from p4.v1.p4runtime_pb2 import SetForwardingPipelineConfigResponse, Update, WriteResponse, ReadResponse
from p4.v1.p4runtime_pb2_grpc import P4RuntimeServicer, add_P4RuntimeServicer_to_server
from google.protobuf.json_format import MessageToJson, Parse

from common.p4_name_id_helper import P4NameConverter, get_pure_p4_name
from common.p4runtime_lib.helper import P4InfoHelper
import redis

from common.p4runtime_lib.switch import IterableQueue
from common.high_level_switch_connection import HighLevelSwitchConnection, StreamMessageResponseWithInfo
from common.redis_helper import RedisKeys, RedisRecords

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)
redis = redis.Redis()



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


class ProxyP4ServicerHeartbeatWorkerThread(Thread):
    def __init__(self, servicer) -> None:
        Thread.__init__(self)
        self.stopped = Event()
        self.servicer = servicer

    def run(self) -> None:
        while not self.stopped.wait(2):
            if RedisMode.is_writing(self.servicer.redis_mode):
                self.servicer.save_counters_state_to_redis()

    def stop(self) -> None:
        self.stopped.set()

@dataclass
class TargetSwitchConfig:
    high_level_connection: HighLevelSwitchConnection
    names: Optional[Dict[str, str]] = None

@dataclass
class TargetSwitchObject:
    high_level_connection: HighLevelSwitchConnection
    converter: P4NameConverter
    names: Optional[Dict[str, str]] = None

class ProxyP4RuntimeServicer(P4RuntimeServicer):
    def __init__(self, prefix: str, from_p4info_path: str, target_switch_configs: List[TargetSwitchConfig], redis_mode: RedisMode) -> None:
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
        self.redis_mode = redis_mode

        self.heartbeat_worker_thread = ProxyP4ServicerHeartbeatWorkerThread(self)
        self.heartbeat_worker_thread.start()


        self.stream_queue_from_target = queue.Queue()
        self.target_switches = []
        for target_key, c in enumerate(target_switch_configs):
            converter = P4NameConverter(self.from_p4info_helper, c.high_level_connection.p4info_helper, self.prefix, c.names)
            target_switch = TargetSwitchObject(c.high_level_connection, converter, c.names)
            target_switch.high_level_connection.subscribe_to_stream_with_queue(self.stream_queue_from_target, target_key)
            self.target_switches.append(target_switch)

        self.running = True

    def stop(self) -> None:
        self.running = False
        self.heartbeat_worker_thread.stop()
        if RedisMode.is_writing(self.redis_mode):
            self.save_counters_state_to_redis()

    def get_target_switch(self, entity: p4runtime_pb2.Entity) -> TargetSwitchObject:
        if len(self.target_switches) == 1:
            return self.target_switches[0]

        entity_name = P4NameConverter.get_entity_name(self.from_p4info_helper, entity)
        for target_switch in self.target_switches:
            if target_switch.names is None or entity_name in target_switch.names:
                print(f'Choosen target switch: {target_switch.high_level_connection.filename}, {target_switch.high_level_connection.port}')
                return target_switch

        raise Exception(f'Cannot find a target switch for {entity_name=}')

    def Write(self, request, context, converter: P4NameConverter = None, save_to_redis: bool = True) -> None:
        print('------------------- Write -------------------')
        print(request)

        target_switch = None

        for update in request.updates:
            if update.type == Update.INSERT or update.type == Update.MODIFY or update.type == Update.DELETE:
                entity = update.entity
                target_switch = self.get_target_switch(entity)
                which_one = entity.WhichOneof('entity')
                if save_to_redis and RedisMode.is_writing(self.redis_mode):
                    if which_one == 'table_entry':
                        redis.rpush(self.redis_keys.TABLE_ENTRIES, MessageToJson(update))
                    elif which_one == 'meter_entry' or which_one == 'direct_meter_entry':
                        redis.rpush(self.redis_keys.METER_ENTRIES, MessageToJson(entity))

                if converter is not None:
                    converter.convert_entity(entity)
                else:
                    target_switch.converter.convert_entity(entity)
            else:
                raise Exception(f'Unhandled update type {update.Type.Name(update.type)}')

        if target_switch is None:
            raise Exception("There is no found target switch")

        print('== SENDING')
        print(request)
        request.device_id = target_switch.high_level_connection.device_id
        target_switch.high_level_connection.connection.client_stub.Write(request)
        return WriteResponse()

    def Read(self, request: p4runtime_pb2.ReadRequest, context):
        """Read one or more P4 entities from the target.
        """
        print('------------------- Read -------------------')
        if len(request.entities) == 1:
            ret = ReadResponse()
            entity = request.entities[0]
            target_switch = self.get_target_switch(entity)
            print('request:')
            print(request)
            target_switch.converter.convert_read_request(request)
            request.device_id = target_switch.high_level_connection.device_id
            print('converted_request:')
            print(request)
            for result in target_switch.high_level_connection.connection.client_stub.Read(request):
                print('result:')
                print(result)
                for entity in result.entities:
                    entity_name = target_switch.converter.get_target_entity_name(entity)
                    if get_pure_p4_name(entity_name).startswith(self.prefix):
                        target_switch.converter.convert_entity(entity, reverse=True)
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
        for request in request_iterator:
            logger.info('StreamChannel message arrived')
            logger.info(request)
            which_one = request.WhichOneof('update')
            if which_one == 'arbitration':
                response = p4runtime_pb2.StreamMessageResponse()
                response.arbitration.device_id = request.arbitration.device_id
                response.arbitration.election_id.high = 0
                response.arbitration.election_id.low = 1
                yield response

                while self.running:
                    stream_response: StreamMessageResponseWithInfo = self.stream_queue_from_target.get()
                    target_switch = self.target_switches[stream_response.extra_information]
                    print('Arrived stream_response_from target')
                    print(stream_response)
                    which_one = stream_response.message.WhichOneof('update')
                    if which_one == 'digest':
                        name = target_switch.converter.get_target_p4_name_from_id('digest', stream_response.message.digest.digest_id)
                        if name.startswith(self.prefix):
                            target_switch.converter.convert_stream_response(stream_response.message)
                            yield stream_response.message
                    else:
                        raise Exception('Only handling digest messages from the dataplane')
            else:
                raise Exception(f'Unhandled Stream field type {request.WhichOneof}')

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

        for target_switch in self.target_switches:
            high_level_connection = target_switch.high_level_connection
            p4name_converter = P4NameConverter(redis_p4info_helper, high_level_connection.p4info_helper, self.prefix, target_switch.names)
            virtual_target_switch_for_load = TargetSwitchObject(high_level_connection, p4name_converter, target_switch.names)

            for protobuf_message_json_object in redis.lrange(self.redis_keys.TABLE_ENTRIES,0,-1):
                parsed_update_object = Parse(protobuf_message_json_object, p4runtime_pb2.Update())
                name = p4name_converter.get_source_entity_name(parsed_update_object.entity)
                if virtual_target_switch_for_load.names is None or name in virtual_target_switch_for_load.names:
                    print(parsed_update_object)
                    self._write_update_object(parsed_update_object, virtual_target_switch_for_load)

            for protobuf_message_json_object in itertools.chain(redis.lrange(self.redis_keys.COUNTER_ENTRIES, 0, -1),
                                                                redis.lrange(self.redis_keys.METER_ENTRIES, 0, -1),
                                                                ):
                entity = Parse(protobuf_message_json_object, p4runtime_pb2.Entity())
                name = p4name_converter.get_source_entity_name(entity)
                if virtual_target_switch_for_load.names is None or name in virtual_target_switch_for_load.names:
                    print(entity)

                    update = p4runtime_pb2.Update()
                    update.type = p4runtime_pb2.Update.MODIFY
                    update.entity.CopyFrom(entity)
                    self._write_update_object(update, virtual_target_switch_for_load)

    def _write_update_object(self, update_object, target_switch: TargetSwitchObject):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = target_switch.high_level_connection.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.CopyFrom(update_object)
        self.Write(request, None, target_switch.converter, save_to_redis=False)

    def delete_redis_entries_for_this_service(self) -> None:
        redis.delete(self.redis_keys.TABLE_ENTRIES)
        redis.delete(self.redis_keys.COUNTER_ENTRIES)
        redis.delete(self.redis_keys.METER_ENTRIES)
        redis.delete(self.redis_keys.HEARTBEAT)

    def save_counters_state_to_redis(self) -> None:
        with redis.pipeline() as pipe:
            pipe.multi()
            pipe.delete(self.redis_keys.COUNTER_ENTRIES)
            for target_switch in self.target_switches:
                request = p4runtime_pb2.ReadRequest()
                request.device_id = target_switch.high_level_connection.connection.device_id

                for direct_counter in self.from_p4info_helper.p4info.direct_counters:
                    name = P4NameConverter.get_p4_name_from_id(self.from_p4info_helper, 'table', direct_counter.direct_table_id)
                    if target_switch.names is None or name in target_switch.names:
                        entity = request.entities.add()
                        entity.direct_counter_entry.table_entry.table_id = direct_counter.direct_table_id
                        target_switch.converter.convert_entity(entity)

                entity = request.entities.add()
                entity.counter_entry.counter_id = 0
                print('-----------REQUEST')
                print(request)
                print('-----------REQUESTEND')
                for response in target_switch.high_level_connection.connection.client_stub.Read(request):
                    for entity in response.entities:
                        entity_name = target_switch.converter.get_target_entity_name(entity)
                        if get_pure_p4_name(entity_name).startswith(self.prefix):
                            print(entity)
                            target_switch.converter.convert_entity(entity, reverse=True)
                            pipe.rpush(self.redis_keys.COUNTER_ENTRIES, MessageToJson(entity))
            pipe.set(self.redis_keys.HEARTBEAT, time.time())
            pipe.execute()



class ProxyServer:
    def __init__(self, port, prefix, from_p4info_path, target_switches: Union[List[TargetSwitchConfig], HighLevelSwitchConnection], redis_mode: RedisMode):
        self.port = port
        self.prefix = prefix
        self.from_p4info_path = from_p4info_path
        if isinstance(target_switches, list):
            self.target_switches = target_switches
        elif isinstance(target_switches, HighLevelSwitchConnection):
            self.target_switches = [TargetSwitchConfig(target_switches)]
        else:
            raise Exception(f'You cannot init target_switches of ProxyServer with "{type(target_switches)}" typed object.')

        self.server = None
        self.servicer = None
        self.redis_mode = redis_mode

    def start(self) -> None:
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        self.servicer = ProxyP4RuntimeServicer(self.prefix, self.from_p4info_path, self.target_switches, self.redis_mode)
        if RedisMode.is_reading(self.redis_mode):
            self.servicer.fill_from_redis()
        add_P4RuntimeServicer_to_server(self.servicer, self.server)
        self.server.add_insecure_port(f'[::]:{self.port}')
        self.server.start()

    def stop(self) -> None:
        self.servicer.stop()
        self.server.stop(grace=None)

class ProxyConfigTarget(BaseModel):
    program_name: str
    port: int
    device_id: int
    reset_dataplane: Optional[bool] = False
    names: Optional[Dict[str,str]] = None

class ProxyConfigSource(BaseModel):
    program_name: str
    prefix: str = ''
    controller_port: int

class ProxyConfigPreloadEntry(BaseModel):
    type: str
    parameters: Dict[str, Any]

class ProxyConfigMapping(BaseModel):
    target: Optional[ProxyConfigTarget] = None
    targets: List[ProxyConfigTarget] = []
    source: Optional[ProxyConfigSource] = None
    sources: List[ProxyConfigSource] = []
    preload_entries: List[ProxyConfigPreloadEntry] = []

class ProxyConfig(BaseModel):
    redis: RedisMode
    mappings: List[ProxyConfigMapping]



def start_servers_by_proxy_config(proxy_config: ProxyConfig) -> List[ProxyServer]:
    servers = []

    for mapping in proxy_config.mappings:
        target_configs_raw = mapping.targets
        if mapping.target is not None:
            target_configs_raw.append(mapping.target)

        source_configs_raw = mapping.sources
        if mapping.source is not None:
            source_configs_raw.append(mapping.source)

        target_switch_configs = []
        for target_config_raw in target_configs_raw:
            mapping_target_switch = HighLevelSwitchConnection(target_config_raw.device_id, target_config_raw.program_name, target_config_raw.port, send_p4info=True, reset_dataplane=target_config_raw.reset_dataplane)
            print('On startup the rules on the target are the following')
            for table_entry_response in mapping_target_switch.connection.ReadTableEntries():
                for starter_table_entity in table_entry_response.entities:
                    entry = starter_table_entity.table_entry
                    print(mapping_target_switch.p4info_helper.get_tables_name(entry.table_id))
                    print(entry)
                    print('-----')
            target_switch_configs.append(TargetSwitchConfig(mapping_target_switch, target_config_raw.names))

        for source in source_configs_raw:
            p4info_path = f"build/{source.program_name}.p4.p4info.txt"
            proxy_server = ProxyServer(source.controller_port, source.prefix, p4info_path, target_switch_configs, proxy_config.redis)
            proxy_server.start()
            servers.append(proxy_server)

        if len(mapping.preload_entries) > 0:
            if len(target_switch_configs) > 1:
                raise Exception('Cannot determine where to preload entries, because there are multiple targets')

            target_high_level_connection = target_switch_configs[0].high_level_connection
            for entry in mapping.preload_entries:
                entry_type = entry.type
                if entry_type == 'table':
                    table_entry = target_high_level_connection.p4info_helper.buildTableEntry(**entry.parameters)
                    target_high_level_connection.connection.WriteTableEntry(table_entry)
                elif entry_type == 'meter':
                    meter_entry = target_high_level_connection.p4info_helper.buildMeterConfigEntry(**entry.parameters)
                    target_high_level_connection.connection.WriteMeterEntry(meter_entry)
                elif entry_type == 'direct_meter':
                    meter_entry = target_high_level_connection.p4info_helper.buildDirectMeterConfigEntry(**entry.parameters)
                    target_high_level_connection.connection.WriteDirectMeterEntry(meter_entry)
                elif entry_type == 'counter':
                    counter_entry = target_high_level_connection.p4info_helper.buildCounterEntry(**entry.parameters)
                    target_high_level_connection.connection.WriteCountersEntry(counter_entry)
                elif entry_type == 'direct_counter':
                    counter_entry = target_high_level_connection.p4info_helper.buildDirectCounterEntry(**entry.parameters)
                    target_high_level_connection.connection.WriteDirectCounterEntry(counter_entry)
                else:
                    raise Exception(f'Preload does not handle {entry_type} yet, inform the author to add what you need.')

    return servers

if __name__ == '__main__':
    with open('proxy_config.json') as f:
        json_data = f.read()
        proxy_config_from_file = ProxyConfig.model_validate_json(json_data)

    proxy_servers = start_servers_by_proxy_config(proxy_config_from_file)

    def sigint_handler(_signum, _frame):
        global proxy_servers
        for server_to_stop in proxy_servers:
            server_to_stop.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)


    try:
        # Important message for the testing system, do not remove :)
        print('Proxy is ready')
        while True:
            time.sleep(60 * 60)
    except KeyboardInterrupt:
        for server in proxy_servers:
            server.stop()

