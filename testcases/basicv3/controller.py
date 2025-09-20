#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.convert import decodeIPv4

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'basicv3', '60051')
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm1",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.20', 32)
        },
        action_name="MyIngress.chg_addr",
        action_params={
            'port': 2,
            'dstAddr': '08:00:00:00:02:00',
        }
    )
    s1.connection.WriteTableEntry(table_entry)


    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm2",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.20', 32)
        },
        action_name="MyIngress.set_port"
    )
    s1.connection.WriteTableEntry(table_entry)


    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.just_another",
        match_fields={
            "hdr.ethernet.dstAddr": '08:00:00:00:02:23'
        },
        action_name="MyIngress.drop"
    )
    s1.connection.WriteTableEntry(table_entry)
