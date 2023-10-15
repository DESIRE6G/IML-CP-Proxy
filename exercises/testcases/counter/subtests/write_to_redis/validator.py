#!/usr/bin/env python3
import sys
import time

import redis
import json

from common.controller_helper import CounterObject
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

redis = redis.Redis()

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051', send_p4info=False)
    s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052', send_p4info=False)

    counter1_id = s1.p4info_helper.get_counters_id('MyIngress.packetCounter')
    counter2_id = s2.p4info_helper.get_counters_id('MyIngress.packetCounter')

    counter1_raw_object = json.loads(redis.get(f'NF1_COUNTER.{counter1_id}'))
    counter1_object = CounterObject(**counter1_raw_object)
    counter2_raw_object = json.loads(redis.get(f'NF2_COUNTER.{counter2_id}'))
    counter2_object = CounterObject(**counter2_raw_object)

    print('Read from redis the actual counters:')
    print(counter1_object)
    print(counter2_object)
    time.sleep(5)
    success = True
    if counter1_object.packet_count == 0:
        print('Counter is zero!')
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
