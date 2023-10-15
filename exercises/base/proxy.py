import json
import logging
import time
from concurrent import futures
from dataclasses import dataclass
from enum import Enum
from threading import Thread, Event
from typing import TypedDict

import grpc
from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2
from p4.v1.p4runtime_pb2 import SetForwardingPipelineConfigResponse, Update, WriteResponse, ReadResponse
from p4.v1.p4runtime_pb2_grpc import P4RuntimeServicer, add_P4RuntimeServicer_to_server
from google.protobuf.json_format import MessageToJson, Parse
import redis

import common.p4runtime_lib
import common.p4runtime_lib.helper
from common.controller_helper import get_counter_object_by_id
from common.p4runtime_lib.switch import IterableQueue
from common.high_level_switch_connection import HighLevelSwitchConnection

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)
redis = redis.Redis()

def prefix_p4_name(original_table_name : str, prefix : str) -> str:
    namespace,table_name = original_table_name.split('.')

    return f'{namespace}.{prefix}{table_name}'

def remove_prefix_p4_name(prefixed_table_name : str, prefix : str) -> str:
    namespace,table_name = prefixed_table_name.split('.')

    return f'{namespace}.{table_name.lstrip(prefix)}'


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

@dataclass
class RedisKeys:
    TABLE_ENTRIES: str
    P4INFO: str
    COUNTER_PREFIX: str

class ProxyP4ServicerWorkerThread(Thread):
    def __init__(self, servicer):
        Thread.__init__(self)
        self.stopped = Event()
        self.servicer = servicer

    def run(self):
        while not self.stopped.wait(2):
            print(f'Heartbeat... {self.servicer.prefix}')
            self.servicer.save_counters_to_redis()

    def stop(self):
        self.stopped.set()

class ProxyP4RuntimeServicer(P4RuntimeServicer):
    def __init__(self, prefix, from_p4info_path, target_switch, redis_mode: RedisMode):
        self.prefix = prefix
        self.redis_keys = RedisKeys(
            TABLE_ENTRIES=f'{prefix}TABLE_ENTRIES',
            P4INFO= f'{prefix}P4INFO',
            COUNTER_PREFIX= f'{prefix}COUNTER'
        )
        self.from_p4info_helper = common.p4runtime_lib.helper.P4InfoHelper(from_p4info_path)
        self.requests_stream = IterableQueue()
        self.target_switch = target_switch
        self.redis_mode = redis_mode

        self.worker_thread = ProxyP4ServicerWorkerThread(self)
        self.worker_thread.start()

    def stop(self):
        self.worker_thread.stop()


    def Write(self, request, context, from_p4info_helper = None, save_to_redis = True):
        print('------------------- Write -------------------')
        if from_p4info_helper is None:
            from_p4info_helper = self.from_p4info_helper

        for update in request.updates:
            if update.type == Update.INSERT:
                if update.entity.WhichOneof('entity') == 'table_entry':
                    if save_to_redis and RedisMode.is_writing(self.redis_mode):
                        redis.rpush(self.redis_keys.TABLE_ENTRIES, MessageToJson(request))
                    entity = update.entity
                    self.convert_table_entry(from_p4info_helper, self.target_switch.p4info_helper, entity)

                    print(update.entity.table_entry)
                else:
                    raise Exception(f'Unhandled {update.Type.Name(update.type)} for {update.entity.WhichOneof("entity")}')
            else:
                raise Exception(f'Unhandled update type {update.Type.Name(update.type)}')

        print('== SENDING')
        print(request)
        request.device_id = self.target_switch.device_id
        self.target_switch.connection.client_stub.Write(request)
        return WriteResponse()



    def convert_id(self, from_p4info_helper, target_p4info_helper, id_type:str, original_id: int, reverse = False, verbose=True) -> int:
        if id_type == 'table':
            name = from_p4info_helper.get_tables_name(original_id)
        elif id_type == 'action':
            name = from_p4info_helper.get_actions_name(original_id)
        elif id_type == 'counter':
            name = from_p4info_helper.get_counters_name(original_id)
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
        elif id_type == 'action':
            return target_p4info_helper.get_actions_id(new_name)
        elif id_type == 'counter':
            return target_p4info_helper.get_counters_id(new_name)
        else:
            raise Exception(f'convert_id cannot handle "{id_type}" id_type')



    def convert_table_entry(self, from_p4info_helper, target_p4info_helper, entity, reverse=False, verbose=True):
        if entity.table_entry.table_id != 0:
            entity.table_entry.table_id = self.convert_id(from_p4info_helper, target_p4info_helper,
                                                          'table', entity.table_entry.table_id,
                                                          reverse, verbose)
        if entity.table_entry.HasField('action'):
            if entity.table_entry.action.WhichOneof('type') == 'action':
                entity.table_entry.action.action.action_id = self.convert_id(from_p4info_helper, target_p4info_helper,
                                                  'action', entity.table_entry.action.action.action_id,
                                                  reverse, verbose)
            else:
                raise Exception(f'Unhandled action type {entity.table_entry.action.type}')


    def convert_counter_entry(self, from_p4info_helper, target_p4info_helper, entity, reverse=False, verbose=True):
        entity.counter_entry.counter_id = self.convert_id(from_p4info_helper, target_p4info_helper,
                                                      'counter', entity.counter_entry.counter_id,
                                                      reverse, verbose)

    def convert_entity(self,  from_p4info_helper, target_p4info_helper, entity, reverse=False, verbose=True):
        if entity.WhichOneof('entity') == 'table_entry':
            self.convert_table_entry(  from_p4info_helper, target_p4info_helper, entity, reverse, verbose)
        elif entity.WhichOneof('entity') == 'counter_entry':
            self.convert_counter_entry(  from_p4info_helper, target_p4info_helper, entity, reverse, verbose)
        else:
            raise Exception(f"Not implemented type for read")

    def convert_read_request(self,  from_p4info_helper, target_p4info_helper, request, verbose=True):
        for entity in request.entities:
            self.convert_entity(from_p4info_helper, target_p4info_helper, entity, reverse=False,verbose=verbose)


    def get_entity_name(self, p4info_helper, entity):
        if entity.WhichOneof('entity') == 'table_entry':
            return p4info_helper.get_tables_name(entity.table_entry.table_id)
        elif entity.WhichOneof('entity') == 'counter_entry':
            return p4info_helper.get_counters_name(entity.counter_entry.counter_id)
        else:
            raise Exception(f"Not implemented type for read")

    def Read(self, request, context):
        """Read one or more P4 entities from the target.
        """
        print('------------------- Read -------------------')
        if len(request.entities) == 1:
            ret = ReadResponse()
            print('request:')
            print(request)
            self.convert_read_request(self.from_p4info_helper,self.target_switch.p4info_helper,request)
            request.device_id = self.target_switch.device_id
            print('converted_request:')
            print(request)
            for result in self.target_switch.connection.client_stub.Read(request):
                print('result:')
                print(result)
                for entity in result.entities:
                    entity_name = self.get_entity_name(self.target_switch.p4info_helper,entity)
                    if get_pure_table_name(entity_name).startswith(self.prefix):
                        self.convert_entity(self.target_switch.p4info_helper, self.from_p4info_helper, entity, reverse=True)
                        ret_entity = ret.entities.add()
                        ret_entity.CopyFrom(entity)


            yield ret
        else:
            raise Exception(f"Read only handles when requested everything")

    def SetForwardingPipelineConfig(self, request, context):
        # Do not forward p4info just save it, on init we loads the p4info
        self.clear_redis()
        redis.set(self.redis_keys.P4INFO,MessageToString(request.config.p4info))
        return SetForwardingPipelineConfigResponse()

    def GetForwardingPipelineConfig(self, request, context):
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

    def Capabilities(self, request, context):
        # missing associated documentation comment in .proto file
        print('Capabilities')
        print(request)
        print(context)
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def fill_from_redis(self):
        print('FILLING FROM REDIS')
        raw_p4info = redis.get(self.redis_keys.P4INFO)
        if raw_p4info is None:
            return
        redis_p4info_helper = common.p4runtime_lib.helper.P4InfoHelper(raw_p4info=raw_p4info)
        for protobuf_message_json_object in redis.lrange(self.redis_keys.TABLE_ENTRIES,0,-1):
            parsed_write_request = Parse(protobuf_message_json_object, p4runtime_pb2.WriteRequest())
            print(parsed_write_request)
            self.Write(parsed_write_request, None, redis_p4info_helper, save_to_redis = False)

    def clear_redis(self):
        redis.delete(self.redis_keys.TABLE_ENTRIES)

    def save_counters_to_redis(self):
        for counter_entry in self.from_p4info_helper.p4info.counters:
            counter_id_at_target = self.convert_id(self.from_p4info_helper, self.target_switch.p4info_helper, 'counter', counter_entry.preamble.id)
            counter_object = get_counter_object_by_id(self.target_switch.connection, counter_id_at_target, 0)
            print(counter_entry.preamble.name)
            print(counter_object)

            redis_key = f'{self.redis_keys.COUNTER_PREFIX}.{counter_entry.preamble.id}'
            redis_value = json.dumps({
                'counter_id': counter_entry.preamble.id,
                'packet_count': counter_object.packet_count,
                'byte_count': counter_object.byte_count,
            })

            redis.set(redis_key, redis_value)




class ProxyServer:
    def __init__(self, port, prefix, from_p4info_path, target_switch, redis_mode: RedisMode):
        self.port = port
        self.prefix = prefix
        self.from_p4info_path = from_p4info_path
        self.target_switch = target_switch
        self.server = None
        self.servicer = None
        self.redis_mode = redis_mode

    def start(self):
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        self.servicer = ProxyP4RuntimeServicer(self.prefix, self.from_p4info_path, self.target_switch, self.redis_mode)
        if RedisMode.is_reading(self.redis_mode):
            self.servicer.fill_from_redis()
        add_P4RuntimeServicer_to_server(self.servicer, self.server)
        self.server.add_insecure_port(f'[::]:{self.port}')
        self.server.start()

    def stop(self, *args):
        self.servicer.stop()
        self.server.stop(*args)

class ProxyConfig:
    def __init__(self, filename = 'proxy_config.json'):
        with open(filename) as f:
            self.proxy_config = json.load(f)

    def get_redis_mode(self) -> RedisMode:
        return RedisMode(self.proxy_config['redis'])

    def get_mappings(self):
        return self.proxy_config['mappings']

proxy_config = ProxyConfig()
mappings = proxy_config.get_mappings()
servers = []

def serve(port, prefix, p4info_path, target_switch, redis_mode: RedisMode):
    global servers
    proxy_server = ProxyServer(port, prefix, p4info_path, target_switch, redis_mode)
    proxy_server.start()
    servers.append(proxy_server)

for mapping in mappings:
    target_config = mapping['target']
    mapping_target_switch = HighLevelSwitchConnection(target_config['device_id'], target_config['program_name'], target_config['port'], send_p4info=True)
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

try:
    # Important message for the testing system, do not remove :)
    print('Proxy is ready')
    while True:
        time.sleep(60 * 60)
except KeyboardInterrupt:
    for server in servers:
        server.stop(0)

