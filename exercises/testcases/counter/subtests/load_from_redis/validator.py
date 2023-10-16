#!/usr/bin/env python3
import sys
import time

import redis

from common.controller_helper import CounterObject, get_counter_object
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.validator_tools import Validator

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

    validator = Validator()

    validator.should_be_greater(counter1_object_index0.packet_count, 100000)
    validator.should_be_greater(counter1_object_index0.byte_count, 9800000)

    validator.should_be_equal(counter1_object_index0.packet_count * 2, counter2_object_index0.packet_count)

    validator.should_be_equal(counter1_id, counter1_object_index0.counter_id)
    validator.should_be_equal(counter2_id, counter2_object_index0.counter_id)

    counter1_object_index1 = get_counter_object(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter', 1)
    counter2_object_index1 = get_counter_object(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter', 1)
    print(counter1_object_index1)
    print(counter2_object_index1)

    validator.should_be_equal(counter1_object_index1.packet_count, 0)
    validator.should_be_greater(counter2_object_index1.packet_count, 200000)
    validator.should_be_equal(counter2_object_index1.packet_count - 100000, counter1_object_index0.packet_count)


    counter1_object_index2 = get_counter_object(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter', 2)
    counter2_object_index2 = get_counter_object(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter', 2)
    print(counter1_object_index2)
    print(counter2_object_index2)

    validator.should_be_equal(counter2_object_index2.packet_count, 200000)
    validator.should_be_equal(counter1_object_index2.packet_count + 200000, counter2_object_index0.packet_count)

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
