#!/usr/bin/env python3
import sys

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections


def get_counter_object(p4info_helper, sw, counter_name, index):
    counters_id = p4info_helper.get_counters_id(counter_name)
    results = []
    for response in sw.ReadCounters(counters_id, index):
        for entity in response.entities:
            results.append({
                'counter_id':entity.counter_entry.counter_id,
                'packet_count':entity.counter_entry.data.packet_count,
                'byte_count':entity.counter_entry.data.byte_count,
            })

    if len(results) > 1:
        raise Exception(f'More than one result arrived for counter read!')

    return results[0]

def get_counter(p4info_helper, sw, counter_name, index):
    return get_counter_object(p4info_helper, sw, counter_name, index)['packet_count']


if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051', send_p4info=False)
    s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052', send_p4info=False)

    counter1_object = get_counter_object(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter', 0)
    counter2_object = get_counter_object(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter', 0)
    print('Counter1 object:')
    print(counter1_object)

    print('Counter2 object:')
    print(counter2_object)

    counters_id1 = s1.p4info_helper.get_counters_id('MyIngress.packetCounter')
    counters_id2 = s2.p4info_helper.get_counters_id('MyIngress.packetCounter')

    success = True
    if counter1_object['packet_count'] == 0:
        print('Counter is zero!')
        success = False

    if counter1_object['packet_count'] * 2 != counter2_object['packet_count']:
        print('Counter 1 has to be twice as counter 2')
        success = False

    if counters_id1 != counter1_object['counter_id'] :
        print(f'counters_id1 should be {counters_id1}')
        success = False

    if counters_id2 != counter2_object['counter_id']:
        print(f'counters_id2 should be {counters_id2}')
        success = False

    ShutdownAllSwitchConnections()

    if success:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)


