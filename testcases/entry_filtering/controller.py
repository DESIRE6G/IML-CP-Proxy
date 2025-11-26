#!/usr/bin/env python3
import sys

import grpc

from common.controller_helper import init_l3fwd_table_rules_for_both_directions, ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection


with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'fwd_exact', '60051')

    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_exact",
        match_fields={
            "hdr.ipv4.dstAddr": '10.0.2.2'
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 2
        })
    s1.connection.WriteTableEntry(table_entry)
    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_exact",
        match_fields={
            "hdr.ipv4.dstAddr": '10.0.2.3'
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 2
        })
    s1.connection.WriteTableEntry(table_entry)
    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_exact",
        match_fields={
            "hdr.ipv4.dstAddr": '10.0.2.4'
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 2
        })
    s1.connection.WriteTableEntry(table_entry)


    for response in s1.connection.ReadTableEntries(s1.p4info_helper.get_tables_id('MyIngress.ipv4_exact')):
        for entity in response.entities:
            entry = entity.table_entry
            print(entry)
        print(f'Entries found: {len(response.entities)}')
        if len(response.entities) != 1:
            sys.exit(-1)


