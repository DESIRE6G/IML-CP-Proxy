import asyncio
import itertools
import logging
import os.path
import queue
import signal
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Union, Tuple
import google
import grpc
import grpc.aio
from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2
from p4.v1.p4runtime_pb2 import SetForwardingPipelineConfigResponse, Update, WriteResponse, ReadResponse
from p4.v1.p4runtime_pb2_grpc import P4RuntimeServicer, add_P4RuntimeServicer_to_server
from google.protobuf.json_format import MessageToJson, Parse

from common.enviroment import enviroment_settings
from common.p4_name_id_helper import P4NameConverter, get_pure_p4_name, EntityCannotHaveZeroId
from common.p4runtime_lib.helper import P4InfoHelper
import redis

from common.p4runtime_lib.switch import IterableQueue
from common.high_level_switch_connection_async import HighLevelSwitchConnection
from common.proxy_config import ProxyConfig, RedisMode, ProxyConfigSource
from common.redis_helper import RedisKeys, RedisRecords

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)

_redis: Optional[redis.Redis] = None

def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis()

    return _redis

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

        self.stream_queue_from_target = asyncio.Queue()
        self.target_switches = []
        for target_key, c in enumerate(target_switch_configs):
            converter = P4NameConverter(self.from_p4info_helper, c.high_level_connection.p4info_helper, self.prefix, c.names)
            target_switch = TargetSwitchObject(c.high_level_connection, converter, c.names)
            target_switch.high_level_connection.subscribe_to_stream_with_queue(self.stream_queue_from_target, target_key)
            self.target_switches.append(target_switch)

        self.running = True
        self.runtime_measurer = RuntimeMeasurer()
        self.ticker = Ticker()

    async def start(self) -> None:
        asyncio.create_task(self.heartbeat())

    async def heartbeat(self) -> None:
        while self.running:
            if RedisMode.is_writing(self.redis_mode):
                await self.save_counters_state_to_redis()

            await asyncio.sleep(2)


    async def stop(self) -> None:
        self.running = False
        if RedisMode.is_writing(self.redis_mode):
            await self.save_counters_state_to_redis()
        for target_switch in self.target_switches:
            target_switch.high_level_connection.unsubscribe_from_stream_with_queue(self.stream_queue_from_target)


    def get_multi_target_switch_and_index(self, entity: p4runtime_pb2.Entity) -> List[Tuple[TargetSwitchObject, int]]:
        if len(self.target_switches) == 1:
            return [(self.target_switches[0], 0)]

        ret: List[Tuple[TargetSwitchObject, int]] = []
        entity_name = P4NameConverter.get_entity_name(self.from_p4info_helper, entity)
        for index, target_switch in enumerate(self.target_switches):
            if target_switch.names is None or entity_name in target_switch.names:
                if self.verbose:
                    print(f'Choosen target switch: {target_switch.high_level_connection.filename}, {target_switch.high_level_connection.port}')
                ret.append((target_switch, index))


        if len(ret) == 0:
            raise Exception(f'Cannot find a target switch for {entity_name=}')

        return ret

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

    async def Write(self, request, context, converter: P4NameConverter = None, save_to_redis: bool = True) -> None:
        start_time = time.time()
        if self.verbose:
            print('------------------- Write -------------------')
            print(request)

        updates_distributed_by_target = [[] for _ in self.target_switches]
        tasks_to_wait = []
        for update in request.updates:
            if update.type == Update.INSERT or update.type == Update.MODIFY or update.type == Update.DELETE:
                entity = update.entity

                for target_switch, target_switch_index in self.get_multi_target_switch_and_index(entity):
                    which_one = entity.WhichOneof('entity')
                    if save_to_redis and RedisMode.is_writing(self.redis_mode):
                        if which_one == 'table_entry':
                            get_redis().rpush(self.redis_keys.TABLE_ENTRIES, MessageToJson(update))
                        elif which_one == 'meter_entry' or which_one == 'direct_meter_entry':
                            get_redis().rpush(self.redis_keys.METER_ENTRIES, MessageToJson(entity))

                    if converter is not None:
                        try:
                            converter.convert_entity(entity, verbose=self.verbose)
                        except Exception as e:
                            raise Exception(f'Conversion failed while trying to convert with converter {entity}') from e
                    else:
                        try:
                            target_switch.converter.convert_entity(entity, verbose=self.verbose)
                        except Exception as e:
                            raise Exception(f'Conversion failed while trying to convert to target switch with index {target_switch_index}, entity: {entity}') from e
                    updates_distributed_by_target[target_switch_index].append(update)
            else:
                raise Exception(f'Unhandled update type {update.Type.Name(update.type)}')

        for target_switch_index, updates in enumerate(updates_distributed_by_target):
            if len(updates) == 0:
                continue
            if self.verbose:
                print(f'== SENDING to target {target_switch_index}')
                print(updates)

            tasks_to_wait.append(asyncio.ensure_future(self.target_switches[target_switch_index].high_level_connection.connection.WriteUpdates(updates)))

        if self.verbose:
            self.runtime_measurer.measure('write', time.time() - start_time)
            if self.ticker.is_tick_passed('write_runtime', 1):
                print(self.runtime_measurer.get_avg('write'))
                self.runtime_measurer.reset('write')

        if not enviroment_settings.production_mode:
            await asyncio.gather(*tasks_to_wait)

        return WriteResponse()

    async def Read(self, original_request: p4runtime_pb2.ReadRequest, context):
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

            async for result in target_switch_object.high_level_connection.connection.client_stub.Read(new_request):
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

    async def SetForwardingPipelineConfig(self, request: p4runtime_pb2.SetForwardingPipelineConfigRequest, context):
        if self.verbose:
            print('SetForwardingPipelineConfig')
            logger.info(request)
        # Do not forward p4info just save it, on init we load the p4info
        self.delete_redis_entries_for_this_service()
        self.raw_p4info = MessageToString(request.config.p4info)
        if RedisMode.is_writing(self.redis_mode):
            get_redis().set(self.redis_keys.P4INFO, self.raw_p4info)

        return SetForwardingPipelineConfigResponse()

    async def GetForwardingPipelineConfig(self, request: p4runtime_pb2.GetForwardingPipelineConfigRequest, context):
        if self.verbose:
            print('GetForwardingPipelineConfig')
        response = p4runtime_pb2.GetForwardingPipelineConfigResponse()
        google.protobuf.text_format.Merge(self.raw_p4info, response.config.p4info)
        return response


    async def StreamChannel(self, request_iterator, context):
        if self.verbose:
            print('StreamChannel')
        async for request in request_iterator:
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
                    stream_response: StreamMessageResponseWithInfo = await self.stream_queue_from_target.get()
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

    async def Capabilities(self, request: p4runtime_pb2.CapabilitiesRequest, context):
        if self.verbose:
            print('Capabilities')
        versions = []
        for target_switch in self.target_switches:
            versions.append(await target_switch.high_level_connection.connection.client_stub.Capabilities(request))

        if not all(version == versions[0] for version in versions):
            raise Exception(f'The underlying api versions not match to each other. Versions from dataplane: {versions}')

        return versions[0]

    async def fill_from_redis(self) -> None:
        if self.verbose:
            print('FILLING FROM REDIS')
        self.raw_p4info = get_redis().get(self.redis_keys.P4INFO)
        if self.raw_p4info is None:
            if self.verbose:
                print('Fillig from redis failed, because p4info cannot be found in redis')
            return

        redis_p4info_helper = P4InfoHelper(raw_p4info=self.raw_p4info)

        for target_switch in self.target_switches:
            high_level_connection = target_switch.high_level_connection
            p4name_converter = P4NameConverter(redis_p4info_helper, high_level_connection.p4info_helper, self.prefix, target_switch.names)
            virtual_target_switch_for_load = TargetSwitchObject(high_level_connection, p4name_converter, target_switch.names)

            for protobuf_message_json_object in get_redis().lrange(self.redis_keys.TABLE_ENTRIES,0,-1):
                parsed_update_object = Parse(protobuf_message_json_object, p4runtime_pb2.Update())
                name = p4name_converter.get_source_entity_name(parsed_update_object.entity)
                if virtual_target_switch_for_load.names is None or name in virtual_target_switch_for_load.names:
                    if self.verbose:
                        print(parsed_update_object)
                    await self._write_update_object(parsed_update_object, virtual_target_switch_for_load)

            for protobuf_message_json_object in itertools.chain(get_redis().lrange(self.redis_keys.COUNTER_ENTRIES, 0, -1),
                                                                get_redis().lrange(self.redis_keys.METER_ENTRIES, 0, -1),
                                                                ):
                entity = Parse(protobuf_message_json_object, p4runtime_pb2.Entity())
                name = p4name_converter.get_source_entity_name(entity)
                if virtual_target_switch_for_load.names is None or name in virtual_target_switch_for_load.names:
                    if self.verbose:
                        print(entity)

                    update = p4runtime_pb2.Update()
                    update.type = p4runtime_pb2.Update.MODIFY
                    update.entity.CopyFrom(entity)
                    await self._write_update_object(update, virtual_target_switch_for_load)

    async def _write_update_object(self, update_object, target_switch: TargetSwitchObject):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = target_switch.high_level_connection.device_id
        request.election_id.low = 1
        update = request.updates.add()
        update.CopyFrom(update_object)
        await self.Write(request, None, target_switch.converter, save_to_redis=False)

    def delete_redis_entries_for_this_service(self) -> None:
        if RedisMode.is_writing(self.redis_mode):
            get_redis().delete(self.redis_keys.TABLE_ENTRIES)
            get_redis().delete(self.redis_keys.COUNTER_ENTRIES)
            get_redis().delete(self.redis_keys.METER_ENTRIES)
            get_redis().delete(self.redis_keys.HEARTBEAT)

    async def save_counters_state_to_redis(self) -> None:
        with get_redis().pipeline() as pipe:
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
                async for response in target_switch.high_level_connection.connection.client_stub.Read(request):
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
        self.awaitable = None

    async def start(self) -> None:
        self.server = grpc.aio.server()
        self.servicer = ProxyP4RuntimeServicer(self.prefix, self.from_p4info_path, self.target_switches, self.redis_mode)
        servicer_awaitable = self.servicer.start()
        if RedisMode.is_reading(self.redis_mode):
            await self.servicer.fill_from_redis()
        add_P4RuntimeServicer_to_server(self.servicer, self.server)
        self.server.add_insecure_port(f'[::]:{self.port}')
        print(f'Start [::]:{self.port}')
        await asyncio.gather(servicer_awaitable, self.server.start())

    async def wait_for_termination(self) -> None:
        try:
            await self.server.wait_for_termination()
        finally:
            await self.server.stop(10)

    async def stop(self) -> None:
        await self.servicer.stop()
        self.server.stop(grace=None)


async def start_servers_by_proxy_config(proxy_config: ProxyConfig) -> List[ProxyServer]:
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
                host=target_config_raw.host
                )
            await mapping_target_switch.init()

            target_switch_configs.append(TargetSwitchConfig(mapping_target_switch, target_config_raw.names))

        for source in source_configs_raw:
            p4info_path = f"build/{source.program_name}.p4.p4info.txt"
            proxy_server = ProxyServer(source.port, source.prefix, p4info_path, target_switch_configs, proxy_config.redis, source)
            proxy_server.awaitable = proxy_server.start()
            servers.append(proxy_server)

        if len(mapping.preload_entries) > 0:
            for entry in mapping.preload_entries:
                target_high_level_connection = target_switch_configs[entry.target_index].high_level_connection
                entry_type = entry.type
                if entry_type == 'table':
                    table_entry = target_high_level_connection.p4info_helper.buildTableEntry(**entry.parameters)
                    await target_high_level_connection.connection.WriteTableEntry(table_entry)
                elif entry_type == 'meter':
                    meter_entry = target_high_level_connection.p4info_helper.buildMeterConfigEntry(**entry.parameters)
                    await target_high_level_connection.connection.WriteMeterEntry(meter_entry)
                elif entry_type == 'direct_meter':
                    meter_entry = target_high_level_connection.p4info_helper.buildDirectMeterConfigEntry(**entry.parameters)
                    await target_high_level_connection.connection.WriteDirectMeterEntry(meter_entry)
                elif entry_type == 'counter':
                    counter_entry = target_high_level_connection.p4info_helper.buildCounterEntry(**entry.parameters)
                    await target_high_level_connection.connection.WriteCountersEntry(counter_entry)
                elif entry_type == 'direct_counter':
                    counter_entry = target_high_level_connection.p4info_helper.buildDirectCounterEntry(**entry.parameters)
                    await target_high_level_connection.connection.WriteDirectCounterEntry(counter_entry)
                else:
                    raise Exception(f'Preload does not handle {entry_type} yet, inform the author to add what you need.')

    return servers

if __name__ == '__main__':
    proxy_servers = []
    def sigint_handler(_signum, _frame):
        global proxy_servers
        for server_to_stop in proxy_servers:
            asyncio.ensure_future(server_to_stop.stop())
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)

    async def async_main():
        with open('proxy_config.json') as f:
            json_data = f.read()
            proxy_config_from_file = ProxyConfig.model_validate_json(json_data)

        global proxy_servers
        proxy_servers = await start_servers_by_proxy_config(proxy_config_from_file)

        try:
            await asyncio.gather(*[x.awaitable for x in proxy_servers])
            # Important message for the testing system, do not remove if you want to use that :)
            print('Proxy is ready')
            await asyncio.gather(*[x.wait_for_termination() for x in proxy_servers])

        except KeyboardInterrupt:
            for server in proxy_servers:
                await server.stop()

    asyncio.run(async_main())
