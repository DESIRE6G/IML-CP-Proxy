#!/usr/bin/env python3
import sys
import time
from pprint import pprint

import redis
import json

from common.controller_helper import CounterObject, get_counter_objects
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
    counter1_objects = get_counter_objects(s1.p4info_helper, s1.connection, 'MyIngress.packetCounter')
    counter2_objects = get_counter_objects(s2.p4info_helper, s2.connection, 'MyIngress.packetCounter')

    print('counter1_objects object:')
    pprint(counter1_objects)

    print('counter2_objects object:')
    pprint(counter2_objects)

    validator = Validator()
    validator.should_be_not_equal(counter1_objects[0].packet_count, 0)
    validator.should_be_equal(counter1_objects[0].packet_count * 2, counter2_objects[0].packet_count)

    validator.should_be_equal(counter1_id, counter1_objects[0].counter_id)
    validator.should_be_equal(counter2_id, counter2_objects[0].counter_id)

    validator.should_be_equal(counter1_objects[1].packet_count, 0)
    validator.should_be_equal(counter2_objects[1].packet_count, counter1_objects[0].packet_count)

    validator.should_be_equal(counter2_objects[2].packet_count, 0)
    validator.should_be_equal(counter1_objects[2].packet_count, counter1_objects[0].packet_count * 2)

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
