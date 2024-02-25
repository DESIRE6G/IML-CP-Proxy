import itertools
import json
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
from typing import Dict, List, Optional

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
from common.high_level_switch_connection import HighLevelSwitchConnection
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
        for c in target_switch_configs:
            converter = P4NameConverter(self.from_p4info_helper, c.high_level_connection.p4info_helper, self.prefix)
            target_switch = TargetSwitchObject(c.high_level_connection, converter, c.names)
            target_switch.high_level_connection.subscribe_to_stream_with_queue(self.stream_queue_from_target)
            self.target_switches.append(target_switch)

        self.running = True

        self.target_hl_switch_connection = self.target_switches[0].high_level_connection
        self.converter = self.target_switches[0].converter

    def stop(self) -> None:
        self.running = False
        self.heartbeat_worker_thread.stop()
        if RedisMode.is_writing(self.redis_mode):
            self.save_counters_state_to_redis()

    def get_target_switch(self, entity: p4runtime_pb2.Entity) -> TargetSwitchObject:
        entity_name = self.target_switches[0].converter.get_source_entity_name(entity)
        for target_switch in self.target_switches:
            if target_switch.names is None or entity_name in target_switch.names:
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
            print('request:')
            print(request)
            self.converter.convert_read_request(request)
            request.device_id = self.target_hl_switch_connection.device_id
            print('converted_request:')
            print(request)
            for result in self.target_hl_switch_connection.connection.client_stub.Read(request):
                print('result:')
                print(result)
                for entity in result.entities:
                    entity_name = self.converter.get_target_entity_name(entity)
                    if get_pure_p4_name(entity_name).startswith(self.prefix):
                        self.converter.convert_entity(entity, reverse=True)
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
                    stream_response = self.stream_queue_from_target.get()

                    print('Arrived stream_response_from target')
                    print(stream_response)
                    which_one = stream_response.WhichOneof('update')
                    if which_one == 'digest':
                        name = self.converter.get_target_p4_name_from_id('digest', stream_response.digest.digest_id)
                        if name.startswith(self.prefix):
                            self.converter.convert_stream_response(stream_response)
                            yield stream_response
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
        p4name_converter = P4NameConverter(redis_p4info_helper, self.target_hl_switch_connection.p4info_helper, self.prefix)

        for protobuf_message_json_object in redis.lrange(self.redis_keys.TABLE_ENTRIES,0,-1):
            parsed_update_object = Parse(protobuf_message_json_object, p4runtime_pb2.Update())
            print(parsed_update_object)
            self._write_update_object(parsed_update_object, p4name_converter)

        for protobuf_message_json_object in itertools.chain(redis.lrange(self.redis_keys.COUNTER_ENTRIES, 0, -1),
                                                            redis.lrange(self.redis_keys.METER_ENTRIES, 0, -1),
                                                            ):
            entity = Parse(protobuf_message_json_object, p4runtime_pb2.Entity())
            print(entity)

            update = p4runtime_pb2.Update()
            update.type = p4runtime_pb2.Update.MODIFY
            update.entity.CopyFrom(entity)
            self._write_update_object(update, p4name_converter)

    def _write_update_object(self, update_object, p4name_converter: P4NameConverter):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = self.target_hl_switch_connection.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.CopyFrom(update_object)
        self.Write(request, None, p4name_converter, save_to_redis=False)

    def delete_redis_entries_for_this_service(self) -> None:
        redis.delete(self.redis_keys.TABLE_ENTRIES)
        redis.delete(self.redis_keys.COUNTER_ENTRIES)
        redis.delete(self.redis_keys.HEARTBEAT)

    def save_counters_state_to_redis(self) -> None:
        request = p4runtime_pb2.ReadRequest()
        request.device_id = self.target_hl_switch_connection.connection.device_id

        for direct_counter in self.from_p4info_helper.p4info.direct_counters:
            entity = request.entities.add()
            entity.direct_counter_entry.table_entry.table_id = direct_counter.direct_table_id
            self.converter.convert_entity(entity)

        entity = request.entities.add()
        entity.counter_entry.counter_id = 0
        with redis.pipeline() as pipe:
            pipe.multi()
            pipe.delete(self.redis_keys.COUNTER_ENTRIES)
            print('-----------REQUEST')
            print(request)
            print('-----------REQUESTEND')
            for response in self.target_hl_switch_connection.connection.client_stub.Read(request):
                for entity in response.entities:
                    entity_name = self.converter.get_target_entity_name(entity)
                    if get_pure_p4_name(entity_name).startswith(self.prefix):
                        print(entity)
                        self.converter.convert_entity(entity, reverse=True)
                        pipe.rpush(self.redis_keys.COUNTER_ENTRIES, MessageToJson(entity))

            pipe.execute()

        print(self.redis_keys.HEARTBEAT, time.time())
        redis.set(self.redis_keys.HEARTBEAT, time.time())


class ProxyServer:
    def __init__(self, port, prefix, from_p4info_path, target_switches: List[TargetSwitchConfig], redis_mode: RedisMode):
        self.port = port
        self.prefix = prefix
        self.from_p4info_path = from_p4info_path
        self.target_switches = target_switches
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

for mapping in mappings:
    target_configs_raw = []
    if 'target' in mapping:
        target_configs_raw.append(mapping['target'])
    if 'targets' in mapping:
        target_configs_raw += mapping['targets']

    target_switch_configs = []
    for target_config_raw in target_configs_raw:
        reset_dataplane = 'reset_dataplane' in target_config_raw and target_config_raw['reset_dataplane']
        mapping_target_switch = HighLevelSwitchConnection(target_config_raw['device_id'], target_config_raw['program_name'], target_config_raw['port'], send_p4info=True, reset_dataplane=reset_dataplane)
        print('On startup the rules on the target are the following')
        for table_entry_response in mapping_target_switch.connection.ReadTableEntries():
            for starter_table_entity in table_entry_response.entities:
                entry = starter_table_entity.table_entry
                print(mapping_target_switch.p4info_helper.get_tables_name(entry.table_id))
                print(entry)
                print('-----')
        target_switch_configs.append(TargetSwitchConfig(mapping_target_switch))

    sources = mapping['sources']
    for source in sources:
        p4info_path = f"build/{source['program_name']}.p4.p4info.txt"
        proxy_server = ProxyServer(source['controller_port'], source['prefix'], p4info_path, target_switch_configs, proxy_config.get_redis_mode())
        proxy_server.start()
        servers.append(proxy_server)

    if 'preload_entries' in mapping:
        if len(target_switch_configs) > 1:
            raise Exception('Cannot determine where to preload entries, because there are multiple targets')

        target_high_level_connection = target_switch_configs[0].high_level_connection
        for entry in mapping['preload_entries']:
            entry_type = entry['type']
            if entry_type == 'table':
                table_entry = target_high_level_connection.p4info_helper.buildTableEntry(**entry['parameters'])
                target_high_level_connection.connection.WriteTableEntry(table_entry)
            elif entry_type == 'meter':
                meter_entry = target_high_level_connection.p4info_helper.buildMeterConfigEntry(**entry['parameters'])
                target_high_level_connection.connection.WriteMeterEntry(meter_entry)
            elif entry_type == 'direct_meter':
                meter_entry = target_high_level_connection.p4info_helper.buildDirectMeterConfigEntry(**entry['parameters'])
                target_high_level_connection.connection.WriteDirectMeterEntry(meter_entry)
            elif entry_type == 'counter':
                counter_entry = target_high_level_connection.p4info_helper.buildCounterEntry(**entry['parameters'])
                target_high_level_connection.connection.WriteCountersEntry(counter_entry)
            elif entry_type == 'direct_counter':
                counter_entry = target_high_level_connection.p4info_helper.buildDirectCounterEntry(**entry['parameters'])
                target_high_level_connection.connection.WriteDirectCounterEntry(counter_entry)
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

