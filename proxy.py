import asyncio
import itertools
import logging
import os.path
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
from common.high_level_switch_connection_async import HighLevelSwitchConnection, StreamMessageResponseWithInfo
from common.proxy_config import ProxyConfig, RedisMode, ProxyConfigSource, ProxyAllowedParamsDict
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
    filter_params_allow_only: Optional[ProxyAllowedParamsDict] = None
    fill_counter_from_redis: Optional[bool] = True

@dataclass
class TargetSwitchObject:
    high_level_connection: HighLevelSwitchConnection
    converter: P4NameConverter
    names: Optional[Dict[str, str]] = None
    filter_params_allow_only: Optional[ProxyAllowedParamsDict] = None
    fill_counter_from_redis: Optional[bool] = True


class RuntimeMeasurer:
    def __init__(self) -> None:
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
    def __init__(self) -> None:
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
        self.verbose_name_converting = False
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
        self._target_switches: Dict[str, TargetSwitchObject] = {}
        for target_key in target_switch_configs:
            self._add_target_switch(target_key)

        self.running = True
        self.runtime_measurer = RuntimeMeasurer()
        self.ticker = Ticker()

    def _add_target_switch(self, new_target_switch_config: TargetSwitchConfig) -> None:
        converter = P4NameConverter(self.from_p4info_helper, new_target_switch_config.high_level_connection.p4info_helper, self.prefix, new_target_switch_config.names)
        target_switch = TargetSwitchObject(
            new_target_switch_config.high_level_connection,
            converter,
            new_target_switch_config.names,
            new_target_switch_config.filter_params_allow_only,
            new_target_switch_config.fill_counter_from_redis
        )
        new_switch_address = target_switch.high_level_connection.get_address()
        print(f'--->{new_switch_address=}')
        target_switch.high_level_connection.subscribe_to_stream_with_queue(self.stream_queue_from_target, new_switch_address)
        self._target_switches[new_switch_address] = target_switch

    async def add_target_switch(self, new_target_switch: TargetSwitchConfig) -> None:
        self._add_target_switch(new_target_switch)
        if RedisMode.is_writing(self.redis_mode):
            switch_address = new_target_switch.high_level_connection.get_address()
            await self.fill_from_redis_one_target(self._target_switches[switch_address], switch_address)

    async def remove_target_switch(self, host: str, port: int) -> None:
        target_switch = self._target_switches.pop(f'{host}:{port}', None)
        target_switch.high_level_connection.unsubscribe_from_stream_with_queue(self.stream_queue_from_target)

    async def add_filter_params_allow_only_to_host(self, host: str, port: int, filters_to_add: ProxyAllowedParamsDict) -> None:
        key = f'{host}:{port}'
        if key not in self._target_switches:
            raise ValueError(f'Cannot find {key} address target switch')

        new_added_params_dict: ProxyAllowedParamsDict = {k: [] for k in filters_to_add}
        target_switch = self._target_switches[key]
        if target_switch.filter_params_allow_only is None:
            target_switch.filter_params_allow_only = {}
        actual_params_dict = target_switch.filter_params_allow_only
        for param_name, allowed_values in filters_to_add.items():
            if param_name in actual_params_dict:
                for allowed_value in allowed_values:
                    if allowed_value not in actual_params_dict[param_name]:
                        actual_params_dict[param_name].append(allowed_value)
                        new_added_params_dict[param_name].append(allowed_value)
            else:
                actual_params_dict[param_name] = allowed_values[:]
                new_added_params_dict[param_name] = allowed_values[:]

        await self.fill_from_redis_one_target(target_switch, key, filter_by_params_allow_only=new_added_params_dict)

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
        for target_switch in self._target_switches.values():
            target_switch.high_level_connection.unsubscribe_from_stream_with_queue(self.stream_queue_from_target)


    def get_multi_target_switch_and_index(self, entity: p4runtime_pb2.Entity) -> List[Tuple[TargetSwitchObject, str]]:
        if len(self._target_switches) == 1:
            first_element_index, first_element = next(iter(self._target_switches.items()))
            return [(first_element, first_element_index)]

        ret: List[Tuple[TargetSwitchObject, str]] = []
        entity_name = P4NameConverter.get_entity_name(self.from_p4info_helper, entity)
        for index, target_switch in self._target_switches.items():
            if target_switch.names is None or entity_name in target_switch.names:
                if self.verbose:
                    print(f'Choosen target switch: {target_switch.high_level_connection.filename}, {target_switch.high_level_connection.host}:{target_switch.high_level_connection.port}')
                ret.append((target_switch, index))

        return ret

    def get_target_switch_and_index(self, entity: p4runtime_pb2.Entity) -> Tuple[TargetSwitchObject, str]:
        if len(self._target_switches) == 1:
            first_element_index, first_element = next(iter(self._target_switches.items()))
            return first_element, first_element_index

        entity_name = P4NameConverter.get_entity_name(self.from_p4info_helper, entity)
        for index, target_switch in self._target_switches.items():
            if target_switch.names is None or entity_name in target_switch.names:
                if self.verbose:
                    print(f'Choosen target switch: {target_switch.high_level_connection.filename}, {target_switch.high_level_connection.port}')
                return target_switch, index

        raise Exception(f'Cannot find a target switch for {entity_name=}')

    def get_target_switch(self, entity: p4runtime_pb2.Entity) -> TargetSwitchObject:
        target_switch, _ = self.get_target_switch_and_index(entity)
        return target_switch

    def is_parameters_allowed_by_filters(self, entity: p4runtime_pb2.Entity, filter_params_allow_only: ProxyAllowedParamsDict) -> bool:
        if filter_params_allow_only is None:
            return True

        which_one = entity.WhichOneof('entity')
        if which_one == 'table_entry':
            for match in entity.table_entry.match:
                match_which = match.WhichOneof('field_match_type')

                if match_which == 'exact':
                    table_name = self.from_p4info_helper.get_tables_name(entity.table_entry.table_id)
                    match_field_name = self.from_p4info_helper.get_match_field_name(table_name, match.field_id)

                    for allowed_param_rule_key, values in filter_params_allow_only.items():
                        if allowed_param_rule_key == match_field_name:
                            encoded_values = [self.from_p4info_helper.get_match_field_pb(table_name, match_field_name, value).exact.value for value in values]
                            if match.exact.value not in encoded_values:
                                return False

        return True

    async def Write(self,
                    request,
                    context,
                    converter_override: Optional[P4NameConverter] = None,
                    target_switch_override_index: Optional[str] = None,
                    save_to_redis: bool = True) -> None:
        start_time = time.time()
        if self.verbose:
            print('------------------- Write -------------------')
            print(request)

        updates_distributed_by_target = {k : [] for k in self._target_switches.keys()}
        tasks_to_wait = []
        for update in request.updates:
            if update.type == Update.INSERT or update.type == Update.MODIFY or update.type == Update.DELETE:
                entity = update.entity
                which_one = entity.WhichOneof('entity')

                if save_to_redis and RedisMode.is_writing(self.redis_mode):
                    if which_one == 'table_entry':
                        get_redis().rpush(self.redis_keys.TABLE_ENTRIES, MessageToJson(update))
                    elif which_one == 'meter_entry' or which_one == 'direct_meter_entry':
                        get_redis().rpush(self.redis_keys.METER_ENTRIES, MessageToJson(entity))

                if target_switch_override_index is None:
                    switches_to_iterate_on = self.get_multi_target_switch_and_index(entity)
                else:
                    switches_to_iterate_on = [(self._target_switches[target_switch_override_index], target_switch_override_index)]

                switches_to_iterate_on = [switch_and_index for switch_and_index in switches_to_iterate_on if self.is_parameters_allowed_by_filters(entity, switch_and_index[0].filter_params_allow_only)]


                for target_switch, target_switch_index in switches_to_iterate_on:
                    if converter_override is None:
                        converter = target_switch.converter
                    else:
                        converter = converter_override

                    try:
                        converter.convert_entity(entity, verbose=self.verbose_name_converting)
                    except Exception as e:
                        raise Exception(f'Conversion failed while trying to convert to target switch with index {target_switch_index}, entity: {entity}') from e
                    updates_distributed_by_target[target_switch_index].append(update)
            else:
                raise Exception(f'Unhandled update type {update.Type.Name(update.type)}')

        for target_switch_index, updates in updates_distributed_by_target.items():
            if len(updates) == 0:
                continue
            if self.verbose:
                print(f'== SENDING to target {target_switch_index}')
                print(updates)

            tasks_to_wait.append(asyncio.ensure_future(self._target_switches[target_switch_index].high_level_connection.connection.WriteUpdates(updates)))

        if self.verbose:
            self.runtime_measurer.measure('write', time.time() - start_time)
            if self.ticker.is_tick_passed('write_runtime', 1):
                print(self.runtime_measurer.get_avg('write'))
                self.runtime_measurer.reset('write')

        if not enviroment_settings.production_mode:
            await asyncio.gather(*tasks_to_wait)
        if self.verbose:
            print('------ End Write')
        return WriteResponse()

    async def Read(self, original_request: p4runtime_pb2.ReadRequest, context):
        """Read one or more P4 entities from the target.
        """
        if self.verbose:
            print('------------------- Read -------------------')

        read_entites_by_target_switch = {k: [] for k in self._target_switches.keys()}
        for entity in original_request.entities:
            try:
                for target_switch, target_switch_index in self.get_multi_target_switch_and_index(entity):
                    read_entites_by_target_switch[target_switch_index].append(entity)
            except EntityCannotHaveZeroId:
                for target_switch_index, target_switch in self._target_switches.items():
                    read_entites_by_target_switch[target_switch_index].append(entity)

        received_entries = []
        for target_switch_index, read_entites_for_target_switch in read_entites_by_target_switch.items():
            if len(read_entites_for_target_switch) == 0:
                continue
            target_switch_object = self._target_switches[target_switch_index]

            new_request = p4runtime_pb2.ReadRequest()
            new_request.device_id = target_switch_object.high_level_connection.device_id

            for original_read_entity in read_entites_for_target_switch:
                read_entity = new_request.entities.add()
                read_entity.CopyFrom(original_read_entity)
                target_switch_object.converter.convert_entity(read_entity, reverse=False, verbose=self.verbose_name_converting)

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
                        target_switch_object.converter.convert_entity(entity, reverse=True, verbose=self.verbose_name_converting)
                        received_entries.append(entity)

        received_entries = self.merge_duplicates_for_read_answer(received_entries)
        print(received_entries)

        ret = ReadResponse()
        for entity in received_entries:
            ret_entity = ret.entities.add()
            ret_entity.CopyFrom(entity)

        if self.verbose:
            print('--------- Response for read:')
            print(ret)

        yield ret

    def merge_duplicates_for_read_answer(self, received_entries: List[p4runtime_pb2.Entity]) -> List[p4runtime_pb2.Entity]:
        def get_entity_identifier(entity: p4runtime_pb2.Entity) -> Union[str, int]:
            which_one = entity.WhichOneof('entity')
            if which_one == 'table_entry':
                return entity.table_entry.table_id
            if which_one == 'meter_entry':
                return entity.meter_entry.meter_id
            if which_one == 'direct_meter_entry':
                return entity.direct_meter_entry.table_entry.table_id
            if which_one == 'counter_entry':
                return f'{entity.counter_entry.counter_id}-{entity.counter_entry.index}'
            if which_one == 'direct_counter_entry':
                return MessageToJson(entity.direct_counter_entry.table_entry) #table and match are both in
            raise NotImplementedError(f'{which_one} is not handled by read feedback')

        groupped_entries: Dict[Union[str, int], p4runtime_pb2.Entity] = {}
        for entity in received_entries:
            identifier = get_entity_identifier(entity)
            if identifier not in groupped_entries:
                groupped_entries[identifier] = []

            groupped_entries[identifier].append(entity)

        ret: List[p4runtime_pb2.Entity] = []
        def are_all_same_entity(entities: List[p4runtime_pb2.Entity]) -> bool:
            json_dump = None
            for entity in entities:
                if json_dump is None:
                    json_dump = MessageToJson(entity)
                elif json_dump != MessageToJson(entity):
                    return False
            return True

        for group in groupped_entries.values():
            first_entity = group[0]
            which_one = first_entity.WhichOneof('entity')
            if which_one in ['table_entry', 'meter_entry', 'direct_meter_entry']:
                if not are_all_same_entity(group):
                    raise Exception(f'Cannot merge, because responses are differs on different targets {group}')
            elif which_one == 'counter_entry':
                for entity in group[1:]:
                    first_entity.counter_entry.data.byte_count += entity.counter_entry.data.byte_count
                    first_entity.counter_entry.data.packet_count += entity.counter_entry.data.packet_count
            elif which_one == 'direct_counter_entry':
                for entity in group[1:]:
                    first_entity.direct_counter_entry.data.byte_count += entity.direct_counter_entry.data.byte_count
                    first_entity.direct_counter_entry.data.packet_count += entity.direct_counter_entry.data.packet_count
            else:
                raise NotImplementedError(f'{which_one} is not handled by read feedback')
            ret.append(first_entity)
        return ret

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
                    print('Sendin back master arbitrage ACK')
                yield response

                while self.running:
                    stream_response: StreamMessageResponseWithInfo = await self.stream_queue_from_target.get()
                    target_switch = self._target_switches[stream_response.extra_information]
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
        for target_switch in self._target_switches.values():
            versions.append(await target_switch.high_level_connection.connection.client_stub.Capabilities(request))

        if not all(version == versions[0] for version in versions):
            raise Exception(f'The underlying api versions not match to each other. Versions from dataplane: {versions}')

        return versions[0]

    def build_source_p4infohelper_from_redis(self) -> Optional[P4InfoHelper]:
        self.raw_p4info = get_redis().get(self.redis_keys.P4INFO)
        if self.raw_p4info is None:
            if self.verbose:
                print('Fillig from redis failed, because p4info cannot be found in redis')
            return None

        return P4InfoHelper(raw_p4info=self.raw_p4info)

    async def fill_from_redis(self) -> None:
        if self.verbose:
            print('FILLING FROM REDIS')

        redis_p4info_helper = self.build_source_p4infohelper_from_redis()
        if redis_p4info_helper is None:
            return

        for address, target_switch in self._target_switches.items():
            await self.fill_from_redis_one_target(target_switch, address, redis_p4info_helper)

    async def fill_from_redis_one_target(
            self,
            target_switch: TargetSwitchObject,
            target_switch_index: str,
            redis_p4info_helper: Optional[P4InfoHelper] = None,
            filter_by_params_allow_only: Optional[ProxyAllowedParamsDict] = None
    ):
        if redis_p4info_helper is None:
            redis_p4info_helper = self.build_source_p4infohelper_from_redis()
            if redis_p4info_helper is None:
                print('Cannot find p4infohelper')
                return

        print(f'FILLING FROM REDIS to {target_switch.high_level_connection.host}:{target_switch.high_level_connection.port}')
        if filter_by_params_allow_only is None:
            used_filter_params_allow_only = target_switch.filter_params_allow_only
        else:
            used_filter_params_allow_only = filter_by_params_allow_only

        high_level_connection = target_switch.high_level_connection
        p4name_converter = P4NameConverter(redis_p4info_helper, high_level_connection.p4info_helper, self.prefix, target_switch.names)
        virtual_target_switch_for_load = TargetSwitchObject(high_level_connection, p4name_converter, target_switch.names)
        for protobuf_message_json_object in get_redis().lrange(self.redis_keys.TABLE_ENTRIES, 0, -1):
            parsed_update_object = Parse(protobuf_message_json_object, p4runtime_pb2.Update())
            name = p4name_converter.get_source_entity_name(parsed_update_object.entity)
            if virtual_target_switch_for_load.names is None or name in virtual_target_switch_for_load.names:
                if used_filter_params_allow_only is not None and not self.is_parameters_allowed_by_filters(parsed_update_object.entity, used_filter_params_allow_only):
                    continue

                if self.verbose:
                    print(parsed_update_object)
                await self._write_update_object(parsed_update_object, p4name_converter, target_switch_index)

        if target_switch.fill_counter_from_redis:
            for protobuf_message_json_object in itertools.chain(get_redis().lrange(self.redis_keys.COUNTER_ENTRIES, 0, -1), get_redis().lrange(self.redis_keys.METER_ENTRIES, 0, -1), ):
                entity = Parse(protobuf_message_json_object, p4runtime_pb2.Entity())
                name = p4name_converter.get_source_entity_name(entity)
                if virtual_target_switch_for_load.names is None or name in virtual_target_switch_for_load.names:
                    if used_filter_params_allow_only is not None and not self.is_parameters_allowed_by_filters(entity, target_switchused_filter_params_allow_only):
                        continue

                    if self.verbose:
                        print(entity)

                    update = p4runtime_pb2.Update()
                    update.type = p4runtime_pb2.Update.MODIFY
                    update.entity.CopyFrom(entity)
                    await self._write_update_object(update, p4name_converter, target_switch_index)

    async def _write_update_object(self, update_object, converter: P4NameConverter, target_switch_index: str):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = 0
        request.election_id.low = 1
        update = request.updates.add()
        update.CopyFrom(update_object)
        await self.Write(request, None, converter, target_switch_index, save_to_redis=False)

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
            for target_switch in self._target_switches.values():
                request = p4runtime_pb2.ReadRequest()
                request.device_id = target_switch.high_level_connection.connection.device_id

                for direct_counter in self.from_p4info_helper.p4info.direct_counters:
                    name = P4NameConverter.get_p4_name_from_id(self.from_p4info_helper, 'table', direct_counter.direct_table_id)
                    if target_switch.names is None or name in target_switch.names:
                        entity = request.entities.add()
                        entity.direct_counter_entry.table_entry.table_id = direct_counter.direct_table_id
                        target_switch.converter.convert_entity(entity, verbose=self.verbose_name_converting)

                entity = request.entities.add()
                entity.counter_entry.counter_id = 0
                async for response in target_switch.high_level_connection.connection.client_stub.Read(request):
                    for entity in response.entities:
                        entity_name = target_switch.converter.get_target_entity_name(entity)
                        if get_pure_p4_name(entity_name).startswith(self.prefix):
                            target_switch.converter.convert_entity(entity, reverse=True, verbose=self.verbose_name_converting)
                            pipe.rpush(self.redis_keys.COUNTER_ENTRIES, MessageToJson(entity))
            pipe.set(self.redis_keys.HEARTBEAT, time.time())
            pipe.execute()


class ProxyServer:
    def __init__(self,
                 port: int,
                 prefix: str,
                 from_p4info_path: str,
                 target_switche_configs_or_one_connection: Union[List[TargetSwitchConfig], HighLevelSwitchConnection],
                 redis_mode: RedisMode):
        self.port = port
        self.prefix = prefix
        self.from_p4info_path = from_p4info_path
        if isinstance(target_switche_configs_or_one_connection, list):
            self.target_switch_configs = target_switche_configs_or_one_connection
        elif isinstance(target_switche_configs_or_one_connection, HighLevelSwitchConnection):
            self.target_switch_configs = [TargetSwitchConfig(target_switche_configs_or_one_connection)]
        else:
            raise Exception(f'You cannot init target_switche_configs_or_one_connection of ProxyServer with "{type(target_switche_configs_or_one_connection)}" typed object.')

        self.server = None
        self.servicer = None
        self.redis_mode = redis_mode
        self.awaitable = None

    async def start(self) -> None:
        self.server = grpc.aio.server()
        self.servicer = ProxyP4RuntimeServicer(self.prefix, self.from_p4info_path, self.target_switch_configs, self.redis_mode)
        servicer_awaitable = self.servicer.start()
        if RedisMode.is_reading(self.redis_mode):
            await self.servicer.fill_from_redis()
        add_P4RuntimeServicer_to_server(self.servicer, self.server)
        self.server.add_insecure_port(f'[::]:{self.port}')
        print(f'Start [::]:{self.port}')
        await asyncio.gather(servicer_awaitable, self.server.start())

    async def add_target_switch(self, new_switch: TargetSwitchConfig) -> None:
        self.assert_inited()
        await self.servicer.add_target_switch(new_switch)

    async def remove_target_switch(self, host: str, port: int) -> None:
        self.assert_inited()
        await self.servicer.remove_target_switch(host, port)

    async def add_filter_params_allow_only_to_host(self, host: str, port: int, filters_to_add: ProxyAllowedParamsDict) -> None:
        self.assert_inited()
        await self.servicer.add_filter_params_allow_only_to_host(host, port, filters_to_add)

    def assert_inited(self) -> None:
        if self.servicer is None:
            raise Exception('Proxy server has to be started to remove a node')

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

            target_switch_configs.append(TargetSwitchConfig(mapping_target_switch, target_config_raw.names, target_config_raw.filter_params_allow_only))

        for source in source_configs_raw:
            p4info_path = f"build/{source.program_name}.p4.p4info.txt"
            proxy_server = ProxyServer(source.port, source.prefix, p4info_path, target_switch_configs, proxy_config.redis)
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
