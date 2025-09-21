#!/usr/bin/env python3
from pprint import pprint
import sys

from common.controller_helper import get_counter_objects, get_direct_counter_objects, get_counter_objects_by_id, LPMMatchObject
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.convert import decodeIPv4
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.validator_tools import Validator

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'fwd_with_count_per_ip', '60051', send_p4info=False)


    node1_direct_counter = get_direct_counter_objects(s1, 'MyIngress.ipv4_lpm')

    print('node1_direct_counter')
    pprint(node1_direct_counter)

    validator = Validator()

    node1_direct_counter_dict = {}
    for counter in node1_direct_counter:
        print(counter)
        if isinstance(counter.match, LPMMatchObject):
            source_ip = decodeIPv4(counter.match.value)
            node1_direct_counter_dict[source_ip] = counter
    print(node1_direct_counter_dict)
    validator.should_be_equal(node1_direct_counter_dict['10.0.2.13'].packet_count, 3)
    validator.should_be_equal(node1_direct_counter_dict['10.0.2.25'].packet_count, 2)
    validator.should_be_equal(node1_direct_counter_dict['10.0.2.33'].packet_count, 1)

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)


