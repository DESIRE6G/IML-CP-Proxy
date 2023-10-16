#!/usr/bin/env python3
import sys
import time

import redis
import json

from common.controller_helper import CounterObject
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.validator_tools import Validator

redis = redis.Redis()

def get_redis_counter_object_by_id(prefix,counter_id, index):
    raw_object = json.loads(redis.lindex(f'{prefix}COUNTER.{counter_id}', index))
    return CounterObject(**raw_object)

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051', send_p4info=False)
    s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052', send_p4info=False)

    counter1_id = s1.p4info_helper.get_counters_id('MyIngress.packetCounter')
    counter2_id = s2.p4info_helper.get_counters_id('MyIngress.packetCounter')

    time.sleep(2)
    counter1_object_index0 = get_redis_counter_object_by_id('NF1_', counter1_id, 0)
    counter2_object_index0 = get_redis_counter_object_by_id('NF2_', counter2_id, 0)

    print('Read from redis the actual counters:')
    print(counter1_object_index0)
    print(counter2_object_index0)


    validator = Validator()
    validator.should_be_not_equal(counter1_object_index0.packet_count, 0)
    validator.should_be_equal(counter1_object_index0.packet_count * 2, counter2_object_index0.packet_count)

    validator.should_be_equal(counter1_id, counter1_object_index0.counter_id)
    validator.should_be_equal(counter2_id, counter2_object_index0.counter_id)

    counter1_object_index1 = get_redis_counter_object_by_id('NF1_', counter1_id, 1)
    counter2_object_index1 = get_redis_counter_object_by_id('NF2_', counter2_id, 1)
    print('counter1_object_index1 object:')
    print(counter1_object_index1)

    print('counter1_object_index1 object:')
    print(counter2_object_index1)

    validator.should_be_equal(counter1_object_index1.packet_count, 0)
    validator.should_be_equal(counter2_object_index1.packet_count, counter1_object_index0.packet_count)


    counter1_object_index2 = get_redis_counter_object_by_id('NF1_', counter2_id, 2)
    counter2_object_index2 = get_redis_counter_object_by_id('NF2_', counter2_id, 2)
    print('counter1_object_index2 object:')
    print(counter1_object_index2)

    print('counter1_object_index2 object:')
    print(counter2_object_index2)

    validator.should_be_equal(counter2_object_index2.packet_count, 0)
    validator.should_be_equal(counter1_object_index2.packet_count, counter1_object_index0.packet_count * 2)

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
