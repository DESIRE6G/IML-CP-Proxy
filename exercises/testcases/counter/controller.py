#!/usr/bin/env python3

import grpc

from common.controller_helper import init_l2fwd_table_rules_for_both_directions, ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection


with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051')
    s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052')
    # PING response can come on this line (s1 and s2 has same p4info)
    init_l2fwd_table_rules_for_both_directions(s1, s2)