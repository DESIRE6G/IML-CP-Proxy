#!/usr/bin/env python3
from pprint import pprint
import sys

from common.controller_helper import get_counter_objects, get_direct_counter_objects, get_counter_objects_by_id
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.validator_tools import Validator

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051', send_p4info=False)
    s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052', send_p4info=False)


    counter1_objects = get_counter_objects(s1, 'MyIngress.packetCounter')
    counter2_objects = get_counter_objects(s2, 'MyIngress.packetCounter')
    node1_direct_counter = get_direct_counter_objects(s1, 'MyIngress.ipv4_lpm')
    counter1_all_objects = get_counter_objects_by_id(s1.connection, None)

    print('counter1_objects object:')
    pprint(counter1_objects)

    print('counter2_objects object:')
    pprint(counter2_objects)

    print('node1_direct_counter')
    pprint(node1_direct_counter)

    print('id=0 request for counter for s1')
    pprint(counter1_all_objects)


    counter1_id = s1.p4info_helper.get_counters_id('MyIngress.packetCounter')
    counter2_id = s2.p4info_helper.get_counters_id('MyIngress.packetCounter')
    counter1_packet_only_id = s1.p4info_helper.get_counters_id('MyIngress.packetCounterOnlyPacket')
    validator = Validator()

    validator.should_be_equal(counter1_all_objects[0:3], counter1_objects)
    validator.should_be_equal(counter1_all_objects[3].counter_id, counter1_packet_only_id)


    validator.should_be_not_equal(counter1_objects[0].packet_count, 0)
    validator.should_be_not_equal(counter1_objects[0].byte_count, 0)
    validator.should_be_equal(node1_direct_counter[0].packet_count,counter1_objects[0].packet_count / 2)
    validator.should_be_equal(node1_direct_counter[1].packet_count,counter1_objects[0].packet_count / 2)

    validator.should_be_equal(counter1_objects[0].packet_count * 2, counter2_objects[0].packet_count)
    validator.should_be_equal(counter1_objects[0].byte_count * 2, counter2_objects[0].byte_count)

    validator.should_be_equal(counter1_id, counter1_objects[0].counter_id)
    validator.should_be_equal(counter2_id, counter2_objects[0].counter_id)

    validator.should_be_equal(counter1_objects[1].packet_count, 0)
    validator.should_be_equal(counter2_objects[1].packet_count, counter1_objects[0].packet_count)

    validator.should_be_equal(counter2_objects[2].packet_count, 0)
    validator.should_be_equal(counter1_objects[2].packet_count, counter1_objects[0].packet_count * 2)

    counter1packet_objects = get_counter_objects(s1, 'MyIngress.packetCounterOnlyPacket')
    counter2bytes_objects = get_counter_objects(s2, 'MyIngress.packetCounterOnlyBytes')

    print('counter1packet_objects object:')
    pprint(counter1packet_objects)

    print('counter2bytes_objects object:')
    pprint(counter2bytes_objects)

    validator.should_be_equal(counter1packet_objects[0].packet_count, counter1_objects[0].packet_count)
    # BMV looks counts packets and bytes regardless of CounterType
    # validator.should_be_equal(counter1packet_objects[0].byte_count, 0)
    validator.should_be_equal(counter2bytes_objects[0].byte_count, counter2_objects[0].byte_count)
    # validator.should_be_equal(counter2bytes_objects[0].packet_count, 0)

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)


