#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'fwd', '60051')

    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:00',
            "port": 2
        })
    s1.connection.WriteTableEntry(table_entry)
