#!/usr/bin/env python3
import ipaddress
import os
import queue
import time
from pathlib import Path
from pprint import pprint

from common.balancer import Balancer, BalancerMode
from common.controller_helper import ControllerExceptionHandling, get_counter_objects, get_direct_counter_objects
from common.high_level_switch_connection import HighLevelSwitchConnection

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'balancer_with_counter', '50051')
    s2 = HighLevelSwitchConnection(1, 'flagged_portfwd', '50052')
    s3 = HighLevelSwitchConnection(2, 'flagged_portfwd', '50053')

    balancer = Balancer(s1, BalancerMode.COUNTER_MODE)
    balancer.add_node(s2, 2)
    balancer.add_node(s3, 3)

    table_entry = s2.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.13', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 2
        })
    s2.connection.WriteTableEntry(table_entry)
    table_entry = s2.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.25', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 2
        })
    s2.connection.WriteTableEntry(table_entry)
    balancer.set_target_node('10.0.1.13', 0)
    balancer.set_target_node('10.0.1.25', 0)
    balancer.load_entries()

    # Fill Flagger for nodes
    table_entry = s2.p4info_helper.build_table_entry(
        table_name="MyIngress.flagger",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.0', 24)
        },
        action_name="MyIngress.set_flag",
        action_params={
            "flag": 10
        })
    s2.connection.WriteTableEntry(table_entry)
    table_entry = s3.p4info_helper.build_table_entry(
        table_name="MyIngress.flagger",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.0', 24)
        },
        action_name="MyIngress.set_flag",
        action_params={
            "flag": 11
        })
    s3.connection.WriteTableEntry(table_entry)

    # Fill last aggregator switch to forward everything to H2
    s4 = HighLevelSwitchConnection(3, 'portfwd', '50054')
    table_entry = s4.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.0', 24)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 3,
            "dstAddr": '08:00:00:00:02:22'
        })
    s4.connection.WriteTableEntry(table_entry)

    Path('.controller_ready').touch()

    for _ in range(10):
        counter_objects = get_direct_counter_objects(s1, 'MyIngress.ipv4_lpm')
        pprint(counter_objects)
        for counter_object in counter_objects:
            ip = int.from_bytes(counter_object.match.value, 'big')
            counter_entry = s1.p4info_helper.build_direct_counter_entry(
                table_name= "MyIngress.ipv4_lpm",
                match_fields= {
                  "hdr.ipv4.srcAddr": ip
                },
                packet_count= 0,
                byte_count= 0
            )
            target_route =  1 if counter_object.packet_count > 1 else 0
            print(f'Zero counters and set route to {target_route}')
            s1.connection.WriteDirectCounterEntry(counter_entry)
            balancer.set_target_node(str(ipaddress.ip_address(ip)),target_route)
        time.sleep(1)
