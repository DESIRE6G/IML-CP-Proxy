#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051')
    s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052')

    counter_entry = s1.p4info_helper.buildCounterEntry('packetCounter', 1, 1234, 6443)
    s1.connection.WriteCountersEntry(counter_entry)
