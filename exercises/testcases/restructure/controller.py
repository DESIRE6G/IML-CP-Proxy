#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'part1', '60051')
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.state_set",
        action_params={
            "newState":66
        })
    s1.connection.WriteTableEntry(table_entry)

    s2 = HighLevelSwitchConnection(1, 'part2', '60052')
    table_entry = s2.p4info_helper.buildTableEntry(
        table_name="MyIngress.state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.state_set",
        action_params={
            "newState": 80
        })
    s2.connection.WriteTableEntry(table_entry)

    s3 = HighLevelSwitchConnection(2, 'part3', '60053')
    table_entry = s3.p4info_helper.buildTableEntry(
        table_name="MyIngress.state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.state_set",
        action_params={
            "newState": 88
        })
    s3.connection.WriteTableEntry(table_entry)

    s4 = HighLevelSwitchConnection(3, 'part4', '60054')
    table_entry = s4.p4info_helper.buildTableEntry(
        table_name="MyIngress.state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.state_set",
        action_params={
            "newState": 61
        })
    s4.connection.WriteTableEntry(table_entry)