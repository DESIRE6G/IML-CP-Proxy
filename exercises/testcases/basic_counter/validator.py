#!/usr/bin/env python3
import os
import sys

from common.high_level_switch_connection import HighLevelSwitchConnection

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../../utils/'))
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections


def get_counter(p4info_helper, sw, counter_name, index):
    counters_id = p4info_helper.get_counters_id(counter_name)
    results = []
    for response in sw.ReadCounters(counters_id, index):
        for entity in response.entities:
            counter = entity.counter_entry
            results.append(counter.data.packet_count)

    if len(results) > 1:
        raise Exception(f'More than one result arrived for counter read!')

    return results[0]


if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051', send_p4info=False)
    s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052', send_p4info=False)

    counter1 = get_counter(s1.p4info_helper, s1.connection, "MyIngress.packetCounter", 0)
    counter2 = get_counter(s2.p4info_helper, s2.connection, "MyIngress.packetCounter", 0)
    print(f'{counter1} {counter2}')

    ShutdownAllSwitchConnections()

    if counter1 * 2 == counter2 and counter1 != 0:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)

