#!/usr/bin/env python3
import sys
from pprint import pprint

from common.controller_helper import get_counter_objects
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.validator_tools import Validator

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'part1', '60051', send_p4info=False)
    s2 = HighLevelSwitchConnection(1, 'part2', '60052', send_p4info=False)
    s3 = HighLevelSwitchConnection(2, 'part3', '60053', send_p4info=False)

    counter1_objects = get_counter_objects(s1, 'MyIngress.packetCounter1')
    counter2_objects = get_counter_objects(s2, 'MyIngress.packetCounter2')
    counter3_objects = get_counter_objects(s3, 'MyIngress.packetCounter3')


    print('counter1_objects object:')
    pprint(counter1_objects)

    print('counter2_objects object:')
    pprint(counter2_objects)

    print('counter3_objects object:')
    pprint(counter3_objects)

    validator = Validator()

    # pcap stores 10, from redis 10 comes, and this test have to add 10 more
    validator.should_be_equal(counter1_objects[0].packet_count , 20)
    validator.should_be_equal(counter1_objects[0].packet_count * 2, counter2_objects[0].packet_count)
    validator.should_be_equal(counter1_objects[0].packet_count * 3, counter3_objects[0].packet_count)

    ShutdownAllSwitchConnections()


    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
