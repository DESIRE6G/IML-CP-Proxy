from dataclasses import dataclass
from typing import List

from common.high_level_switch_connection import HighLevelSwitchConnection


def dump_table_rules(p4info_helper, sw):
    print('\n----- Reading tables rules for %s -----' % sw.name)
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            print(p4info_helper.get_tables_name(entry.table_id))
            print(entry)

            print('-----')


def create_experimental_model_forwards():
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


def get_counter_objects_by_id(sw, counters_id, index=None) -> List[CounterObject]:
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

def get_counter_object_by_id(sw, counters_id, index) -> CounterObject:
    results = get_counter_objects_by_id(sw, counters_id, index)

    if len(results) > 1:
        raise Exception(f'More than one result arrived for counter read!')

    return results[0]

def get_counter_object(p4info_helper, sw, counter_name, index) -> CounterObject:
    counters_id = p4info_helper.get_counters_id(counter_name)
    return get_counter_object_by_id(sw, counters_id, index)

def get_counter_objects(p4info_helper, sw, counter_name) -> List[CounterObject]:
    counters_id = p4info_helper.get_counters_id(counter_name)
    return get_counter_objects_by_id(sw, counters_id)


def get_counter(p4info_helper, sw, counter_name, index):
    return get_counter_object(p4info_helper, sw, counter_name, index)['packet_count']
