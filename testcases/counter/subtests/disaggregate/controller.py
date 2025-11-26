#!/usr/bin/env python3

import grpc

from common.controller_helper import init_l3fwd_table_rules_for_both_directions, ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection


with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting_aggregated', '60051')


    table_entry = s1.p4info_helper.build_table_entry(table_name="MyIngress.NF1_ipv4_lpm", match_fields={"hdr.ipv4.dstAddr": ('10.0.1.1', 32)}, action_name="MyIngress.NF1_ipv4_forward", action_params={"dstAddr": '08:00:00:00:01:11', "port": 1})
    s1.connection.WriteTableEntry(table_entry)
    table_entry = s1.p4info_helper.build_table_entry(table_name="MyIngress.NF2_ipv4_lpm", match_fields={"hdr.ipv4.dstAddr": ('10.0.1.1', 32)}, action_name="MyIngress.NF2_ipv4_forward", action_params={"dstAddr": '08:00:00:00:01:11', "port": 1})
    s1.connection.WriteTableEntry(table_entry)
    # s2 forwards packet to h2 if arrives
    table_entry = s1.p4info_helper.build_table_entry(table_name="MyIngress.NF1_ipv4_lpm", match_fields={"hdr.ipv4.dstAddr": ('10.0.2.2', 32)}, action_name="MyIngress.NF1_ipv4_forward", action_params={"dstAddr": '08:00:00:00:02:22', "port": 2})
    s1.connection.WriteTableEntry(table_entry)
    table_entry = s1.p4info_helper.build_table_entry(table_name="MyIngress.NF2_ipv4_lpm", match_fields={"hdr.ipv4.dstAddr": ('10.0.2.2', 32)}, action_name="MyIngress.NF2_ipv4_forward", action_params={"dstAddr": '08:00:00:00:02:22', "port": 2})
    s1.connection.WriteTableEntry(table_entry)