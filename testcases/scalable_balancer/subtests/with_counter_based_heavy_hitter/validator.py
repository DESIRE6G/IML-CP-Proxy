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

    validator = Validator()

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)


