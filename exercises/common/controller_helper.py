from dataclasses import dataclass
from typing import List, Optional

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
    s1 = HighLevelSwitchConnection(0, 'fwd')
    s2 = HighLevelSwitchConnection(1, 'fwd')
    # PING response can come on this line (s1 and s2 has same p4info)
    table_entry = s1.p4info_helper.buildTableEntry(
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
    table_entry = s2.p4info_helper.buildTableEntry(
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
    table_entry = s1.p4info_helper.buildTableEntry(
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



def get_counter_objects_by_id(sw: SwitchConnection, counters_id: Optional[int] = None, index=None) -> List[CounterObject]:
    results = []
    for response in sw.ReadCounters(counters_id, index):
        for entity in response.entities:
            new_obj = CounterObject(
                counter_id=entity.counter_entry.counter_id,
                packet_count=entity.counter_entry.data.packet_count,
                byte_count=entity.counter_entry.data.byte_count,
            )
            results.append(new_obj)

    return results

def get_counter_object_by_id(sw: SwitchConnection, counters_id: int, index: int) -> CounterObject:
    results = get_counter_objects_by_id(sw, counters_id, index)

    if len(results) > 1:
        raise Exception(f'More than one result arrived for counter read!')

    return results[0]

def get_counter_object(p4info_helper: P4InfoHelper, sw: SwitchConnection, counter_name: str, index: int) -> CounterObject:
    counters_id = p4info_helper.get_counters_id(counter_name)
    return get_counter_object_by_id(sw, counters_id, index)

def get_counter_objects(p4info_helper: P4InfoHelper, sw: SwitchConnection, counter_name: str) -> List[CounterObject]:
    counters_id = p4info_helper.get_counters_id(counter_name)
    return get_counter_objects_by_id(sw, counters_id)


def get_counter(p4info_helper: P4InfoHelper, sw: SwitchConnection, counter_name: str, index: int):
    return get_counter_object(p4info_helper, sw, counter_name, index)


@dataclass
class LPMMatchObject:
    value: bytes
    prefix_length_in_bits: int

@dataclass
class DirectCounterObject:
    table_id: int
    packet_count: int
    byte_count: int
    match: LPMMatchObject

def get_direct_counter_objects_by_id(sw: SwitchConnection, table_id: int) -> List[DirectCounterObject]:
    results = []
    for response in sw.ReadDirectCounters(table_id):
        for entity in response.entities:
            table_entry = entity.direct_counter_entry.table_entry
            new_obj = DirectCounterObject(
                table_id=table_entry.table_id,
                packet_count=entity.direct_counter_entry.data.packet_count,
                byte_count=entity.direct_counter_entry.data.byte_count,
                match=LPMMatchObject(table_entry.match[0].lpm.value, table_entry.match[0].lpm.prefix_len)
            )
            results.append(new_obj)

    return results

def get_direct_counter_objects(p4info_helper: P4InfoHelper, sw: SwitchConnection, table_name: str) -> List[DirectCounterObject]:
    table_name = p4info_helper.get_tables_id(table_name)
    return get_direct_counter_objects_by_id(sw, table_name)


def init_l3fwd_table_rules_for_both_directions(s1: HighLevelSwitchConnection, s2: HighLevelSwitchConnection):
    table_entry = s1.p4info_helper.buildTableEntry(table_name="MyIngress.ipv4_lpm", match_fields={"hdr.ipv4.dstAddr": ('10.0.1.1', 32)}, action_name="MyIngress.ipv4_forward", action_params={"dstAddr": '08:00:00:00:01:11', "port": 1})
    s1.connection.WriteTableEntry(table_entry)
    s2.connection.WriteTableEntry(table_entry)
    # s2 forwards packet to h2 if arrives
    table_entry = s2.p4info_helper.buildTableEntry(table_name="MyIngress.ipv4_lpm", match_fields={"hdr.ipv4.dstAddr": ('10.0.2.2', 32)}, action_name="MyIngress.ipv4_forward", action_params={"dstAddr": '08:00:00:00:02:22', "port": 2})
    s1.connection.WriteTableEntry(table_entry)
    s2.connection.WriteTableEntry(table_entry)


class ControllerExceptionHandling:
    def __enter__(self):
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
