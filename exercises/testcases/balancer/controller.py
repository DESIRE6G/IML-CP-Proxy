#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'portfwd', '50051')
    s2 = HighLevelSwitchConnection(1, 'portfwd', '50052')
    s3 = HighLevelSwitchConnection(2, 'portfwd', '50053')
    s4 = HighLevelSwitchConnection(3, 'portfwd', '50054')

    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.13', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 2,
            "dstAddr": '08:00:00:00:02:22',
            "flag": 0
        })
    s1.connection.WriteTableEntry(table_entry)
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.25', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 3,
            "dstAddr": '08:00:00:00:02:22',
            "flag": 0
        })
    s1.connection.WriteTableEntry(table_entry)

    table_entry = s2.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.13', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 2,
            "dstAddr": '08:00:00:00:02:22',
            "flag": 10
        })
    s2.connection.WriteTableEntry(table_entry)

    table_entry = s3.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.25', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 2,
            "dstAddr": '08:00:00:00:02:22',
            "flag": 11
        })
    s3.connection.WriteTableEntry(table_entry)


    table_entry = s4.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.13', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 3,
            "dstAddr": '08:00:00:00:02:22',
            "flag": 0
        })
    s4.connection.WriteTableEntry(table_entry)
    table_entry = s4.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.25', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 3,
            "dstAddr": '08:00:00:00:02:22',
            "flag": 0
        })
    s4.connection.WriteTableEntry(table_entry)
