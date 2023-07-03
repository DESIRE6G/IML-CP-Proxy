import logging
import time
from concurrent import futures
from typing import TypedDict

import grpc
from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2_grpc, p4runtime_pb2
from p4.v1.p4runtime_pb2 import StreamMessageRequest, StreamMessageResponse, SetForwardingPipelineConfigResponse, \
    Update, WriteResponse, ReadResponse
from p4.v1.p4runtime_pb2_grpc import P4RuntimeServicer, add_P4RuntimeServicer_to_server
from google.protobuf.json_format import MessageToJson, Parse
import redis

import common.p4runtime_lib
import common.p4runtime_lib.helper
from common.p4runtime_lib.switch import IterableQueue
from common.high_level_switch_connection import HighLevelSwitchConnection

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)

target_switch = HighLevelSwitchConnection(2, 'basic', '50053', send_p4info=True)
print('On startup the rules on the target are the following')
for response in target_switch.connection.ReadTableEntries():
    for entity in response.entities:
        entry = entity.table_entry
        print(target_switch.p4info_helper.get_tables_name(entry.table_id))
        print(entry)
        print('-----')

redis = redis.Redis()

def prefix_p4_action_or_table(original_table_name : str, prefix : str) -> str:
    namespace,table_name = original_table_name.split('.')

    return f'{namespace}.{prefix}{table_name}'

def remove_prefix_p4_action_or_talbe(prefixed_table_name : str, prefix : str) -> str:
    namespace,table_name = prefixed_table_name.split('.')

    return f'{namespace}.{table_name.lstrip(prefix)}'


def get_pure_table_name(original_table_name : str) -> str:
    namespace,table_name = original_table_name.split('.')

    return f'{table_name}'


class RedisKeys(TypedDict):
    TABLE_ENTRIES: str
    P4INFO: str


class ProxyP4RuntimeServicer(P4RuntimeServicer):
    def __init__(self, prefix, from_p4info_path):
        self.prefix = prefix
        self.redis_keys : RedisKeys = {
            'TABLE_ENTRIES': f'{self.prefix}TABLE_ENTRIES',
            'P4INFO': f'{prefix}P4INFO'
        }
        self.from_p4info_helper = common.p4runtime_lib.helper.P4InfoHelper(from_p4info_path)
        self.requests_stream = IterableQueue()




    def Write(self, request, context, from_p4info_helper = None, save_to_redis = True):
        print('------------------- Write')
        if from_p4info_helper is None:
            from_p4info_helper = self.from_p4info_helper

        for update in request.updates:
            if update.type == Update.INSERT:
                if update.entity.WhichOneof('entity') == 'table_entry':
                    if save_to_redis:
                        redis.rpush(self.redis_keys['TABLE_ENTRIES'], MessageToJson(request))
                    entity = update.entity
                    self.convert_table_entry(from_p4info_helper, target_switch.p4info_helper, entity)

                    print(update.entity.table_entry)

                else:
                    raise Exception(f'Unhandled update type {update.type}')
            else:
                raise Exception(f'Unhandled update type {update.type}')

        print('== SENDING')
        print(request)
        request.device_id = target_switch.device_id
        target_switch.connection.client_stub.Write(request)
        return WriteResponse()

    def convert_table_entry(self, from_p4info_helper, target_p4info_helper, entity, reverse=False):
        table_name = from_p4info_helper.get_tables_name(entity.table_entry.table_id)
        if reverse:
            new_table_name = remove_prefix_p4_action_or_talbe(table_name, self.prefix)
        else:
            new_table_name = prefix_p4_action_or_table(table_name, self.prefix)

        new_table_id = target_p4info_helper.get_tables_id(new_table_name)
        entity.table_entry.table_id = new_table_id
        if entity.table_entry.action.WhichOneof('type') == 'action':
            received_action_id = entity.table_entry.action.action.action_id
            received_action_name = from_p4info_helper.get_actions_name(received_action_id)

            if reverse:
                new_action_name = remove_prefix_p4_action_or_talbe(received_action_name, self.prefix)
            else:
                new_action_name = prefix_p4_action_or_table(received_action_name, self.prefix)

            new_action_id = target_p4info_helper.get_actions_id(new_action_name)
            entity.table_entry.action.action.action_id = new_action_id
        else:
            raise Exception(f'Unhandled action type {entity.table_entry.action.type}')

    def Read(self, request, context):
        """Read one or more P4 entities from the target.
        """
        if len(request.entities) == 1:
            ret = ReadResponse()

            for result in target_switch.connection.client_stub.Read(request):
                for entity in result.entities:
                    table_name = target_switch.p4info_helper.get_tables_name(entity.table_entry.table_id)
                    if get_pure_table_name(table_name).startswith(self.prefix):
                        self.convert_table_entry(target_switch.p4info_helper, self.from_p4info_helper, entity, reverse=True)
                        ret_entity = ret.entities.add()
                        ret_entity.CopyFrom(entity)

            yield ret
        else:
            raise Exception(f"Read only handles when requested everything")

    def SetForwardingPipelineConfig(self, request, context):
        # Do not forward p4info just save it
        self.clear_redis()
        redis.set(self.redis_keys['P4INFO'],MessageToString(request.config.p4info))
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
        return

        for request in request_iterator:
            request_copy = p4runtime_pb2.StreamMessageRequest()
            request_copy.CopyFrom(request)
            self.requests_stream.put(request_copy)
            for item in self.stream_msg_resp:
                yield item
        '''
        for request in request_iterator:
            logger.info('StreamChannel message arrived')
            logger.info(request)
            which_one = request.WhichOneof('update')
            if which_one == 'arbitration':
                response = StreamMessageResponse()
                response.arbitration.device_id = request.arbitration.device_id
                response.arbitration.election_id.high = 0
                response.arbitration.election_id.low = 1
                yield response
            else:
                raise Exception(f'Unhandled Stream field type {request.WhichOneof}')
        '''

    def Capabilities(self, request, context):
        # missing associated documentation comment in .proto file
        print('Capabilities')
        print(request)
        print(context)
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')



    def fill_from_redis(self):
        raw_p4info = redis.get(self.redis_keys['P4INFO'])
        if raw_p4info is None:
            return
        redis_p4info_helper = common.p4runtime_lib.helper.P4InfoHelper(raw_p4info=raw_p4info)
        print('FILLING FROM REDIS')
        for protobuf_message_json_object in redis.lrange(self.redis_keys['TABLE_ENTRIES'],0,-1):
            parsed_write_request = Parse(protobuf_message_json_object, p4runtime_pb2.WriteRequest())
            print(parsed_write_request)
            self.Write(parsed_write_request, None, redis_p4info_helper, save_to_redis = False)

    def clear_redis(self):
        redis.delete(self.redis_keys['TABLE_ENTRIES'])

class ProxyServer:
    def __init__(self, port, prefix, from_p4info_path):
        self.port = port
        self.prefix = prefix
        self.from_p4info_path = from_p4info_path


    def start(self):
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        self.servicer = ProxyP4RuntimeServicer(self.prefix, self.from_p4info_path)
        # self.servicer.fill_from_redis()
        add_P4RuntimeServicer_to_server(self.servicer, self.server)
        self.server.add_insecure_port(f'[::]:{self.port}')
        self.server.start()

    def stop(self, *args):
        self.server.stop(*args)



servers = []
def serve(port, prefix, p4info_path):
    global servers
    server = ProxyServer(port, prefix, p4info_path)
    server.start()
    servers.append(server)

serve('60053', prefix='NF1_', p4info_path='build/basic_part1.p4.p4info.txt')
serve('60054', prefix='NF2_', p4info_path='build/basic_part2.p4.p4info.txt')

try:
    while True:
        time.sleep(60 * 60)
except KeyboardInterrupt:
    for server in servers:
        server.stop(0)

