#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection


with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'part1', '60051')
    s2 = HighLevelSwitchConnection(1, 'part2', '60052')
    s3 = HighLevelSwitchConnection(2, 'part3', '60053')
    s4 = HighLevelSwitchConnection(3, 'part4', '60054')

    s5 = HighLevelSwitchConnection(0, 'aggregated1234', '51051')
    table_entry = s5.p4info_helper.buildTableEntry(
        table_name="MyIngress.part1_state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.part1_state_set",
        action_params={
            "newState":66
        })
    s5.connection.WriteTableEntry(table_entry)

    table_entry = s5.p4info_helper.buildTableEntry(
        table_name="MyIngress.part2_state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.part2_state_set",
        action_params={
            "newState": 80
        })
    s5.connection.WriteTableEntry(table_entry)

    table_entry = s5.p4info_helper.buildTableEntry(
        table_name="MyIngress.part3_state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.part3_state_set",
        action_params={
            "newState": 88
        })
    s5.connection.WriteTableEntry(table_entry)

    table_entry = s5.p4info_helper.buildTableEntry(
        table_name="MyIngress.part4_state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.part4_state_set",
        action_params={
            "newState": 61
        })
    s5.connection.WriteTableEntry(table_entry)
