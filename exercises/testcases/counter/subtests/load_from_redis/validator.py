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
    counter1_object = get_counter_object(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter', 0)
    counter2_object = get_counter_object(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter', 0)

    print('Read from redis the actual counters:')
    print(counter1_object)
    print(counter2_object)
    success = True
    if counter1_object.packet_count <= 100000:
        print('Counter is less than the counter status in redis!')
        success = False

    if counter1_object.byte_count <= 9800000:
        print('Counter is less than the counter status in redis!')
        success = False

    if counter1_object.packet_count * 2 != counter2_object.packet_count:
        print('Counter 1 has to be twice as counter 2')
        success = False

    if counter1_id != counter1_object.counter_id :
        print(f'counters_id1 should be {counter1_id}')
        success = False

    if counter2_id != counter2_object.counter_id:
        print(f'counters_id2 should be {counter2_id}')
        success = False

    ShutdownAllSwitchConnections()

    if success:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
