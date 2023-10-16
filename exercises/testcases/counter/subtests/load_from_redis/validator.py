#!/usr/bin/env python3
import sys
import time

import redis

from common.controller_helper import CounterObject, get_counter_object
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

redis = redis.Redis()

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051', send_p4info=False)
    s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052', send_p4info=False)

    counter1_id = s1.p4info_helper.get_counters_id('MyIngress.packetCounter')
    counter2_id = s2.p4info_helper.get_counters_id('MyIngress.packetCounter')

    time.sleep(2)
    counter1_object_index0 = get_counter_object(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter', 0)
    counter2_object_index0 = get_counter_object(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter', 0)

    print('Read from redis the actual counters:')
    print(counter1_object_index0)
    print(counter2_object_index0)
    success = True
    if counter1_object_index0.packet_count <= 100000:
        print('Counter is less than the counter status in redis!')
        success = False

    if counter1_object_index0.byte_count <= 9800000:
        print('Counter is less than the counter status in redis!')
        success = False

    if counter1_object_index0.packet_count * 2 != counter2_object_index0.packet_count:
        print('Counter 1 has to be twice as counter 2')
        success = False

    if counter1_id != counter1_object_index0.counter_id :
        print(f'counters_id1 should be {counter1_id}')
        success = False

    if counter2_id != counter2_object_index0.counter_id:
        print(f'counters_id2 should be {counter2_id}')
        success = False


    counter1_object_index1 = get_counter_object(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter', 1)
    counter2_object_index1 = get_counter_object(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter', 1)
    print(counter1_object_index1)
    print(counter2_object_index1)
    if counter1_object_index1.packet_count != 0:
        print('counter1_object_index1 should be 0, because it is not increased!')
        success = False

    if counter2_object_index1.packet_count <= 200000:
        print('counter2_object_index1 should be at least 200000!')
        success = False

    if counter2_object_index1.packet_count - 100000 != counter1_object_index0.packet_count:
        print(f'counter2_object_index1-100000 should be equal to counter1_object_index0 {counter2_object_index1.packet_count}, {counter1_object_index0.packet_count}!')
        success = False


    counter1_object_index2 = get_counter_object(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter', 2)
    counter2_object_index2 = get_counter_object(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter', 2)
    print(counter1_object_index2)
    print(counter2_object_index2)
    if counter2_object_index2.packet_count != 200000:
        print('counter2_object_index2 should be 200000, because it is not increased!')
        success = False

    if counter1_object_index2.packet_count + 200000 != counter2_object_index0.packet_count:
        print('counter1_object_index2 + 200000 should be counter2_object_index0!')
        success = False





    ShutdownAllSwitchConnections()

    if success:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
