#!/usr/bin/env python3
import sys

from common.controller_helper import get_counter_object
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051', send_p4info=False)
    s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052', send_p4info=False)

    counter1_object_index0 = get_counter_object(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter', 0)
    counter2_object_index0 = get_counter_object(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter', 0)
    print('counter1_object_index0 object:')
    print(counter1_object_index0)

    print('counter2_object_index0 object:')
    print(counter2_object_index0)

    counter1_id = s1.p4info_helper.get_counters_id('MyIngress.packetCounter')
    counter2_id = s2.p4info_helper.get_counters_id('MyIngress.packetCounter')

    success = True
    if counter1_object_index0.packet_count == 0 or counter1_object_index0.byte_count == 0:
        print('counter1_object_index0 is zero!')
        success = False

    if counter1_object_index0.packet_count * 2 != counter2_object_index0.packet_count or \
            counter1_object_index0.byte_count * 2 != counter2_object_index0.byte_count:
        print('Counter 1 has to be twice as counter 2')
        success = False

    if counter1_id != counter1_object_index0.counter_id:
        print(f'counters_id1 should be {counter1_id}')
        success = False

    if counter2_id != counter2_object_index0.counter_id:
        print(f'counters_id2 should be {counter2_id}')
        success = False



    counter1_object_index1 = get_counter_object(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter', 1)
    counter2_object_index1 = get_counter_object(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter', 1)
    print('counter1_object_index1 object:')
    print(counter1_object_index1)

    print('counter1_object_index1 object:')
    print(counter2_object_index1)

    if counter1_object_index1.packet_count != 0:
        print('counter1_object_index1 packet_count should be zero!')
        success = False

    if counter2_object_index1.packet_count != counter1_object_index0.packet_count:
        print('counter2_object_index1 should be equal to counter1_object_index0')
        success = False



    counter1_object_index2 = get_counter_object(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter', 2)
    counter2_object_index2 = get_counter_object(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter', 2)
    print('counter1_object_index2 object:')
    print(counter1_object_index2)

    print('counter1_object_index2 object:')
    print(counter2_object_index2)

    if counter2_object_index2.packet_count != 0:
        print('counter2_object_index1 packet_count should be zero!')
        success = False

    if counter1_object_index2.packet_count != counter1_object_index0.packet_count * 2:
        print('counter1_object_index2 should be double to counter1_object_index1')
        success = False


    ShutdownAllSwitchConnections()

    if success:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)


