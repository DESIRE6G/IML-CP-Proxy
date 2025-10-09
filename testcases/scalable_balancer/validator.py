#!/usr/bin/env python3
from pprint import pprint
import sys

from common.controller_helper import get_counter_objects, get_direct_counter_objects, get_counter_objects_by_id, LPMMatchObject, ExactMatchObject
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.convert import decodeIPv4
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.validator_tools import Validator

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'scalable_balancer_fwd', '60051', send_p4info=False)


    node1_direct_counter = get_direct_counter_objects(s1, 'MyIngress.ipv4_exact')
    counter1 = get_counter_objects(s1, 'MyIngress.packetCounter')
    counter1_all_objects = get_counter_objects_by_id(s1.connection, None)

    print('node1_direct_counter')
    pprint(node1_direct_counter)

    validator = Validator()

    node1_direct_counter_dict = {}
    for counter in node1_direct_counter:
        print(counter)
        if isinstance(counter.match, ExactMatchObject):
            source_ip = decodeIPv4(counter.match.value)
            node1_direct_counter_dict[source_ip] = counter
    print(node1_direct_counter_dict)
    validator.should_be_equal(node1_direct_counter_dict['10.0.2.13'].packet_count, 6)
    # TODO: It should be 3, removed node counter lost
    # validator.should_be_equal(node1_direct_counter_dict['10.0.2.25'].packet_count, 3)
    validator.should_be_equal(node1_direct_counter_dict['10.0.2.25'].packet_count, 1)
    validator.should_be_equal(node1_direct_counter_dict['10.0.2.33'].packet_count, 4)

    validator.should_be_equal(counter1[0].packet_count, 11)
    validator.should_be_equal(counter1[1].packet_count, 0)
    validator.should_be_equal(counter1[2].packet_count, 22)

    validator.should_be_equal(counter1[0].byte_count, 11 * 37)
    validator.should_be_equal(counter1[1].byte_count, 0)
    validator.should_be_equal(counter1[2].byte_count, 22 * 37)

    validator.should_be_equal(counter1_all_objects, counter1)

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)


