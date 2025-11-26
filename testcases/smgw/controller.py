#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.convert import decodeIPv4

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'smgw', '60051')

    start_ip_int = 0x0a010000
    for i in range(11):
        actual_ip_int = start_ip_int + i
        actual_ip_str = decodeIPv4(actual_ip_int.to_bytes(4, 'big'))
        #print(actual_ip_str)
        table_entry = s1.p4info_helper.build_table_entry(
            table_name="ingress.ue_selector",
            match_fields={
                "hdr.ipv4.dstAddr": (actual_ip_str, 32)
            },
            action_name="ingress.gtp_decapsulate",
            priority=i+1,
        )
        s1.connection.WriteTableEntry(table_entry)

        table_entry = s1.p4info_helper.build_table_entry(
            table_name="ingress.ipv4_lpm",
            match_fields={
                "hdr.ipv4.dstAddr": (actual_ip_str, 32)
            },
            action_name="ingress.set_nhgrp",
            action_params={
                "nhgrp": 1,
            },
        )
        s1.connection.WriteTableEntry(table_entry)

    table_entry = s1.p4info_helper.build_table_entry(
        table_name="ingress.ipv4_forward",
        match_fields={
            "meta.routing_metadata.nhgrp": 1
        },
        action_name="ingress.pkt_send",
        action_params={
            "nhmac": "08:00:00:00:02:00",
            "port": 2
        },
    )
    s1.connection.WriteTableEntry(table_entry)
