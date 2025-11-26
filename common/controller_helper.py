import time
from dataclasses import dataclass
from typing import List, Optional, Union

from p4.config.v1 import p4info_pb2
from p4.v1 import p4runtime_pb2

import grpc

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.helper import P4InfoHelper
from common.p4runtime_lib.switch import SwitchConnection, ShutdownAllSwitchConnections


def dump_table_rules(p4info_helper: P4InfoHelper, sw: SwitchConnection) -> None:
    print('\n----- Reading tables rules for %s -----' % sw.name)
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            print(p4info_helper.get_tables_name(entry.table_id))
            print(entry)

            print('-----')


def create_experimental_model_forwards() -> None:
    s1 = HighLevelSwitchConnection(0, 'fwd', port=50051)
    s2 = HighLevelSwitchConnection(1, 'fwd', port=50052)
    # PING response can come on this line (s1 and s2 has same p4info)
    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.1.1', 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:01:11',
            "port": 1
        })
    s1.connection.WriteTableEntry(table_entry)
    s2.connection.WriteTableEntry(table_entry)

    # s2 forwards packet to h2 if arrives
    table_entry = s2.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 2
        })
    s2.connection.WriteTableEntry(table_entry)


    # s1 forwards packet to the experimental track
    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 3
        })
    s1.connection.WriteTableEntry(table_entry)

@dataclass
class CounterObject:
    counter_id: int
    packet_count: int
    byte_count: int

    @classmethod
    def from_proto_entry(cls, counter_entry: p4runtime_pb2.CounterEntry) -> 'CounterObject':
        return cls(
                counter_id=counter_entry.counter_id,
                packet_count=counter_entry.data.packet_count,
                byte_count=counter_entry.data.byte_count,
            )


def get_counter_objects_by_id(sw: SwitchConnection, counters_id: Optional[int] = None, index=None) -> List[CounterObject]:
    results = []
    for response in sw.ReadCounters(counters_id, index):
        for entity in response.entities:
            new_obj = CounterObject.from_proto_entry(entity.counter_entry)
            results.append(new_obj)

    return results

def get_counter_objects(s1: HighLevelSwitchConnection, counter_name: str) -> List[CounterObject]:
    counters_id = s1.p4info_helper.get_counters_id(counter_name)
    return get_counter_objects_by_id(s1.connection, counters_id)


@dataclass
class LPMMatchObject:
    value: bytes
    prefix_length_in_bits: int

@dataclass
class ExactMatchObject:
    value: bytes

@dataclass
class DirectCounterObject:
    table_id: int
    packet_count: int
    byte_count: int
    match_type: p4info_pb2.MatchField
    match: Union[LPMMatchObject, ExactMatchObject]


def get_direct_counter_objects(s1: HighLevelSwitchConnection, table_name: str) -> List[DirectCounterObject]:
    table_id = s1.p4info_helper.get_tables_id(table_name)
    results = []
    sw = s1.connection
    for response in sw.ReadDirectCounters(table_id):
        for entity in response.entities:
            table_entry = entity.direct_counter_entry.table_entry
            match_field = s1.p4info_helper.get_match_field(table_name)
            match_type = match_field.match_type
            if len(table_entry.match) > 1:
                raise Exception('Only supported simple matches')

            if match_type == p4info_pb2.MatchField.LPM:
                match_object = LPMMatchObject(table_entry.match[0].lpm.value, table_entry.match[0].lpm.prefix_len)
            elif match_type == p4info_pb2.MatchField.EXACT:
                match_object = ExactMatchObject(table_entry.match[0].exact.value)
            else:
                raise Exception(f'Unhandled match type for {table_name} is {match_type}')

            new_obj = DirectCounterObject(
                table_id=table_entry.table_id,
                packet_count=entity.direct_counter_entry.data.packet_count,
                byte_count=entity.direct_counter_entry.data.byte_count,
                match_type=match_type,
                match=match_object
            )
            results.append(new_obj)

    return results


def init_l3fwd_table_rules_for_both_directions(s1: HighLevelSwitchConnection, s2: HighLevelSwitchConnection):
    table_entry = s1.p4info_helper.build_table_entry(table_name="MyIngress.ipv4_lpm", match_fields={"hdr.ipv4.dstAddr": ('10.0.1.1', 32)}, action_name="MyIngress.ipv4_forward", action_params={"dstAddr": '08:00:00:00:01:11', "port": 1})
    s1.connection.WriteTableEntry(table_entry)
    s2.connection.WriteTableEntry(table_entry)
    # s2 forwards packet to h2 if arrives
    table_entry = s2.p4info_helper.build_table_entry(table_name="MyIngress.ipv4_lpm", match_fields={"hdr.ipv4.dstAddr": ('10.0.2.2', 32)}, action_name="MyIngress.ipv4_forward", action_params={"dstAddr": '08:00:00:00:02:22', "port": 2})
    s1.connection.WriteTableEntry(table_entry)
    s2.connection.WriteTableEntry(table_entry)


class ControllerExceptionHandling:
    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type, exc_value, exc_tb):
        if isinstance(exc_value, KeyboardInterrupt):
            print('KeyboardInterrupt occured, shutting down.')
            ShutdownAllSwitchConnections()
            return True
        elif isinstance(exc_value, grpc.RpcError):
            printGrpcError(exc_value)
            ShutdownAllSwitchConnections()
            raise Exception('GRPC Error occured')


def get_now_ts_us_int32() -> int:
    return int(time.time() * 1_000_000) % (2 ** 32)

def diff_ts_us_int32(a: int, b: int) -> int:
    '''
    >>> diff_ts_us_int32(1, 1000)
    999
    >>> diff_ts_us_int32(1, 1)
    0
    >>> diff_ts_us_int32(1234, 11234)
    10000
    >>> diff_ts_us_int32(2 ** 32 - 1, 1)
    2
    >>> diff_ts_us_int32(2 ** 32 - 100, 100)
    200
    '''
    if a <= b:
        return b - a
    else:
        return b - (a - 2 ** 32)
