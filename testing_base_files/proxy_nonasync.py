import itertools
import logging
import os.path
import queue
import signal
import sys
import time
from concurrent import futures
from dataclasses import dataclass
from threading import Thread, Event
from typing import Dict, List, Optional, Union, Tuple
import yappi
import google
import grpc
from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2
from p4.v1.p4runtime_pb2 import SetForwardingPipelineConfigResponse, Update, WriteResponse, ReadResponse
from p4.v1.p4runtime_pb2_grpc import P4RuntimeServicer, add_P4RuntimeServicer_to_server
from google.protobuf.json_format import MessageToJson, Parse

from common.p4_name_id_helper import P4NameConverter, get_pure_p4_name, EntityCannotHaveZeroId
from common.p4runtime_lib.helper import P4InfoHelper
import redis

from common.p4runtime_lib.switch import IterableQueue
from common.high_level_switch_connection import HighLevelSwitchConnection, StreamMessageResponseWithInfo
from common.model.proxy_config import ProxyConfig, RedisMode, ProxyConfigSource
from common.redis_helper import RedisKeys, RedisRecords

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)
redis = redis.Redis()

RUN_PERF = False

if RUN_PERF:
    yappi.start()


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


class RuntimeMeasurer:
    def __init__(self):
        self.measurements = {}

    def measure(self, key: str, value: float) -> None:
        if key not in self.measurements:
            self.reset(key)

        self.measurements[key]['times'].append(value)

    def get_avg(self, key: str) -> float:
        if len(self.measurements[key]['times']) == 0:
            return -1

        return sum(self.measurements[key]['times']) / len(self.measurements[key]['times'])

    def reset(self, key: str) -> None:
        self.measurements[key] = {
            'times': []
        }


class Ticker:
    def __init__(self):
        self.last_ticks = {}

    def is_tick_passed(self, key: str, time_to_wait: float) -> bool:
        ret = key not in self.last_ticks or time.time() - self.last_ticks[key] > time_to_wait

        if ret:
            self.last_ticks[key] = time.time()

        return ret


class ProxyP4RuntimeServicer(P4RuntimeServicer):
    def __init__(self, prefix: str, from_p4info_path: str, target_switch_configs: List[TargetSwitchConfig], redis_mode: RedisMode) -> None:
        self.prefix = prefix
        self.verbose = False
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
        self.raw_p4info = MessageToString(self.from_p4info_helper.p4info)
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
        self.runtime_measurer = RuntimeMeasurer()
        self.ticker = Ticker()

    def stop(self) -> None:
        self.running = False
        self.heartbeat_worker_thread.stop()
        if RedisMode.is_writing(self.redis_mode):
            self.save_counters_state_to_redis()
        for target_switch in self.target_switches:
            target_switch.high_level_connection.unsubscribe_from_stream_with_queue(self.stream_queue_from_target)


    def get_target_switch_and_index(self, entity: p4runtime_pb2.Entity) -> Tuple[TargetSwitchObject, int]:
        if len(self.target_switches) == 1:
            return self.target_switches[0], 0

        entity_name = P4NameConverter.get_entity_name(self.from_p4info_helper, entity)
        for index, target_switch in enumerate(self.target_switches):
            if target_switch.names is None or entity_name in target_switch.names:
                if self.verbose:
                    print(f'Choosen target switch: {target_switch.high_level_connection.filename}, {target_switch.high_level_connection.port}')
                return target_switch, index

        raise Exception(f'Cannot find a target switch for {entity_name=}')

    def get_target_switch(self, entity: p4runtime_pb2.Entity) -> TargetSwitchObject:
        target_switch, _ = self.get_target_switch_and_index(entity)
        return target_switch

    def Write(self, request, context, converter: P4NameConverter = None, save_to_redis: bool = True) -> None:
        start_time = time.time()
        if self.verbose:
            print('------------------- Write -------------------')
            print(request)

        updates_distributed_by_target = [[] for _ in self.target_switches]

        for update in request.updates:
            if update.type == Update.INSERT or update.type == Update.MODIFY or update.type == Update.DELETE:
                entity = update.entity
                target_switch, target_switch_index = self.get_target_switch_and_index(entity)
                which_one = entity.WhichOneof('entity')
                if save_to_redis and RedisMode.is_writing(self.redis_mode):
                    if which_one == 'table_entry':
                        redis.rpush(self.redis_keys.TABLE_ENTRIES, MessageToJson(update))
                    elif which_one == 'meter_entry' or which_one == 'direct_meter_entry':
                        redis.rpush(self.redis_keys.METER_ENTRIES, MessageToJson(entity))

                if converter is not None:
                    converter.convert_entity(entity, verbose=self.verbose)
                else:
                    target_switch.converter.convert_entity(entity, verbose=self.verbose)
                updates_distributed_by_target[target_switch_index].append(update)
            else:
                raise Exception(f'Unhandled update type {update.Type.Name(update.type)}')

        for target_switch_index, updates in enumerate(updates_distributed_by_target):
            if len(updates) == 0:
                continue
            if self.verbose:
                print(f'== SENDING to target {target_switch_index}')
                print(updates)
            self.target_switches[target_switch_index].high_level_connection.connection.WriteUpdates(updates)
        if self.verbose:
            self.runtime_measurer.measure('write', time.time() - start_time)
            if self.ticker.is_tick_passed('write_runtime', 1):
                print(self.runtime_measurer.get_avg('write'))
                self.runtime_measurer.reset('write')

        return WriteResponse()

    def Read(self, original_request: p4runtime_pb2.ReadRequest, context):
        """Read one or more P4 entities from the target.
        """
        if self.verbose:
            print('------------------- Read -------------------')

        ret = ReadResponse()
        read_entites_by_target_switch = [[] for _ in range(len(self.target_switches))]
        for entity in original_request.entities:
            try:
                _, target_switch_index = self.get_target_switch_and_index(entity)
                read_entites_by_target_switch[target_switch_index].append(entity)
            except EntityCannotHaveZeroId:
                for target_switch_index, target_switch in enumerate(self.target_switches):
                    read_entites_by_target_switch[target_switch_index].append(entity)


        for target_switch_index, read_entites_for_target_switch in enumerate(read_entites_by_target_switch):
            if len(read_entites_for_target_switch) == 0:
                continue
            target_switch_object = self.target_switches[target_switch_index]

            new_request = p4runtime_pb2.ReadRequest()
            new_request.device_id = target_switch_object.high_level_connection.device_id

            for original_read_entity in read_entites_for_target_switch:
                read_entity = new_request.entities.add()
                read_entity.CopyFrom(original_read_entity)
                target_switch_object.converter.convert_entity(read_entity, reverse=False, verbose=self.verbose)

            if self.verbose:
                print(f'Request for switch {target_switch_index}')
                print(new_request)

            for result in target_switch_object.high_level_connection.connection.client_stub.Read(new_request):
                if self.verbose:
                    print('result:')
                    print(result)
                for entity in result.entities:
                    entity_name = target_switch_object.converter.get_target_entity_name(entity)
                    if get_pure_p4_name(entity_name).startswith(self.prefix):
                        target_switch_object.converter.convert_entity(entity, reverse=True, verbose=self.verbose)
                        ret_entity = ret.entities.add()
                        ret_entity.CopyFrom(entity)



        yield ret

    def SetForwardingPipelineConfig(self, request: p4runtime_pb2.SetForwardingPipelineConfigRequest, context):
        if self.verbose:
            print('SetForwardingPipelineConfig')
            logger.info(request)
        # Do not forward p4info just save it, on init we load the p4info
        self.delete_redis_entries_for_this_service()
        self.raw_p4info = MessageToString(request.config.p4info)
        if RedisMode.is_writing(self.redis_mode):
            redis.set(self.redis_keys.P4INFO, self.raw_p4info)

        return SetForwardingPipelineConfigResponse()

    def GetForwardingPipelineConfig(self, request: p4runtime_pb2.GetForwardingPipelineConfigRequest, context):
        if self.verbose:
            print('GetForwardingPipelineConfig')
        response = p4runtime_pb2.GetForwardingPipelineConfigResponse()
        google.protobuf.text_format.Merge(self.raw_p4info, response.config.p4info)
        return response


    def StreamChannel(self, request_iterator, context):
        if self.verbose:
            print('StreamChannel')
        for request in request_iterator:
            if self.verbose:
                print(request)
            logger.info('StreamChannel message arrived')
            logger.info(request)
            which_one = request.WhichOneof('update')
            if which_one == 'arbitration':
                response = p4runtime_pb2.StreamMessageResponse()
                response.arbitration.device_id = request.arbitration.device_id
                response.arbitration.election_id.high = 0
                response.arbitration.election_id.low = 1
                if self.verbose:
                    print(f'Sendin back master arbitrage ACK {self.target_switches[0].high_level_connection.p4info_path}')
                yield response

                while self.running:
                    stream_response: StreamMessageResponseWithInfo = self.stream_queue_from_target.get()
                    target_switch = self.target_switches[stream_response.extra_information]
                    if self.verbose:
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
        if self.verbose:
            print('Capabilities')
        versions = []
        for target_switch in self.target_switches:
            versions.append(target_switch.high_level_connection.connection.client_stub.Capabilities(request))

        if not all(version == versions[0] for version in versions):
            raise Exception(f'The underlying api versions not match to each other. Versions from dataplane: {versions}')

        return versions[0]

    def fill_from_redis(self) -> None:
        if self.verbose:
            print('FILLING FROM REDIS')
        self.raw_p4info = redis.get(self.redis_keys.P4INFO)
        if self.raw_p4info is None:
            if self.verbose:
                print('Fillig from redis failed, because p4info cannot be found in redis')
            return

        redis_p4info_helper = P4InfoHelper(raw_p4info=self.raw_p4info)

        for target_switch in self.target_switches:
            high_level_connection = target_switch.high_level_connection
            p4name_converter = P4NameConverter(redis_p4info_helper, high_level_connection.p4info_helper, self.prefix, target_switch.names)
            virtual_target_switch_for_load = TargetSwitchObject(high_level_connection, p4name_converter, target_switch.names)

            for protobuf_message_json_object in redis.lrange(self.redis_keys.TABLE_ENTRIES,0,-1):
                parsed_update_object = Parse(protobuf_message_json_object, p4runtime_pb2.Update())
                name = p4name_converter.get_source_entity_name(parsed_update_object.entity)
                if virtual_target_switch_for_load.names is None or name in virtual_target_switch_for_load.names:
                    if self.verbose:
                        print(parsed_update_object)
                    self._write_update_object(parsed_update_object, virtual_target_switch_for_load)

            for protobuf_message_json_object in itertools.chain(redis.lrange(self.redis_keys.COUNTER_ENTRIES, 0, -1),
                                                                redis.lrange(self.redis_keys.METER_ENTRIES, 0, -1),
                                                                ):
                entity = Parse(protobuf_message_json_object, p4runtime_pb2.Entity())
                name = p4name_converter.get_source_entity_name(entity)
                if virtual_target_switch_for_load.names is None or name in virtual_target_switch_for_load.names:
                    if self.verbose:
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
                        target_switch.converter.convert_entity(entity, verbose=self.verbose)

                entity = request.entities.add()
                entity.counter_entry.counter_id = 0
                for response in target_switch.high_level_connection.connection.client_stub.Read(request):
                    for entity in response.entities:
                        entity_name = target_switch.converter.get_target_entity_name(entity)
                        if get_pure_p4_name(entity_name).startswith(self.prefix):
                            target_switch.converter.convert_entity(entity, reverse=True, verbose=self.verbose)
                            pipe.rpush(self.redis_keys.COUNTER_ENTRIES, MessageToJson(entity))
            pipe.set(self.redis_keys.HEARTBEAT, time.time())
            pipe.execute()



class ProxyServer:
    def __init__(self,
                 port: int,
                 prefix: str,
                 from_p4info_path: str,
                 target_switches: Union[List[TargetSwitchConfig], HighLevelSwitchConnection],
                 redis_mode: RedisMode,
                 config: ProxyConfigSource):
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
        self.config = config

    def start(self) -> None:
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=self.config.worker_num))
        self.servicer = ProxyP4RuntimeServicer(self.prefix, self.from_p4info_path, self.target_switches, self.redis_mode)
        if RedisMode.is_reading(self.redis_mode):
            self.servicer.fill_from_redis()
        add_P4RuntimeServicer_to_server(self.servicer, self.server)
        self.server.add_insecure_port(f'[::]:{self.port}')
        print(f'Start [::]:{self.port}')
        self.server.start()

    def stop(self) -> None:
        self.servicer.stop()
        self.server.stop(grace=None)


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
            mapping_target_switch = HighLevelSwitchConnection(
                target_config_raw.device_id,
                target_config_raw.program_name,
                target_config_raw.port,
                send_p4info=True,
                reset_dataplane=target_config_raw.reset_dataplane,
                rate_limit=target_config_raw.rate_limit,
                rate_limiter_buffer_size=target_config_raw.rate_limiter_buffer_size,
                batch_delay=target_config_raw.batch_delay,
                )
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
            proxy_server = ProxyServer(source.port, source.prefix, p4info_path, target_switch_configs, proxy_config.redis, source)
            proxy_server.start()
            servers.append(proxy_server)

        if len(mapping.preload_entries) > 0:
            if len(target_switch_configs) > 1:
                raise Exception('Cannot determine where to preload entries, because there are multiple targets')

            target_high_level_connection = target_switch_configs[0].high_level_connection
            for entry in mapping.preload_entries:
                entry_type = entry.type
                if entry_type == 'table':
                    table_entry = target_high_level_connection.p4info_helper.build_table_entry(**entry.parameters)
                    target_high_level_connection.connection.WriteTableEntry(table_entry)
                elif entry_type == 'meter':
                    meter_entry = target_high_level_connection.p4info_helper.build_meter_config_entry(**entry.parameters)
                    target_high_level_connection.connection.WriteMeterEntry(meter_entry)
                elif entry_type == 'direct_meter':
                    meter_entry = target_high_level_connection.p4info_helper.build_direct_meter_config_entry(**entry.parameters)
                    target_high_level_connection.connection.WriteDirectMeterEntry(meter_entry)
                elif entry_type == 'counter':
                    counter_entry = target_high_level_connection.p4info_helper.build_counter_entry(**entry.parameters)
                    target_high_level_connection.connection.WriteCountersEntry(counter_entry)
                elif entry_type == 'direct_counter':
                    counter_entry = target_high_level_connection.p4info_helper.build_direct_counter_entry(**entry.parameters)
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
            if RUN_PERF:
                time.sleep(5)
                threads = yappi.get_thread_stats()
                for thread in threads :
                    yappi_stats = yappi.get_func_stats(ctx_id=thread.id)

                    if 'Bmv2SwitchConnection.WriteUpdates' in [stat.name for stat in yappi_stats]:
                        yappi_stats.print_all()
                        yappi.convert2pstats(yappi_stats.get()).dump_stats('perf2.prof')
                        break
            else:
                time.sleep(60 * 60)


    except KeyboardInterrupt:
        for server in proxy_servers:
            server.stop()

