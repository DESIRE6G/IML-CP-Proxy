#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.convert import decodeIPv4

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'arp_icmp', '60051')
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name='MyIngress.arp_exact',
        match_fields={
            'hdr.arp.dst_ip': '10.0.2.20'
        },
        action_name="MyIngress.arp_reply",
        action_params={
            'request_mac': '08:00:00:00:02:22',
        }
    )
    s1.connection.WriteTableEntry(table_entry)

    table_entry = s1.p4info_helper.buildTableEntry(
        table_name='MyIngress.icmp_responder',
        match_fields={
            'hdr.ethernet.dstAddr': 'ff:ff:ff:ff:ff:ff',
        },
        action_name="MyIngress.icmp_reply"
    )
    s1.connection.WriteTableEntry(table_entry)

