#!/usr/bin/env python3
import ipaddress
import os
import time
from pathlib import Path
from pprint import pprint

import requests

from common.controller_helper import ControllerExceptionHandling, get_direct_counter_objects
from common.high_level_switch_connection import HighLevelSwitchConnection

with ControllerExceptionHandling():

    merger_node_connection = HighLevelSwitchConnection(
        4,
        'fwd2p1',
        50055,
        send_p4info=True,
        reset_dataplane=False,
        host='127.0.0.1'
    )

    s1 = HighLevelSwitchConnection(0, 'scalable_balancer_fwd', '60051')

    requests.post('http://127.0.0.1:8080/add_node', json={'host': '127.0.0.1', 'port': 50052, 'device_id':1}).raise_for_status()
    requests.post('http://127.0.0.1:8080/add_node', json={'host': '127.0.0.1', 'port': 50053, 'device_id':2}).raise_for_status()
    requests.post('http://127.0.0.1:8080/set_route', json={'source_address': '10.0.1.13', 'target_port': 2}).raise_for_status()
    requests.post('http://127.0.0.1:8080/set_route', json={'source_address': '10.0.1.25', 'target_port': 2}).raise_for_status()

    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_exact",
        match_fields={
            "hdr.ipv4.dstAddr": '10.0.2.13'
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:00',
            "port": 2
        })
    s1.connection.WriteTableEntry(table_entry)
    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_exact",
        match_fields={
            "hdr.ipv4.dstAddr": '10.0.2.25'
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:00',
            "port": 2
        })
    s1.connection.WriteTableEntry(table_entry)

    Path('.controller_ready').touch()
    balancer_connection = HighLevelSwitchConnection(0, 'scalable_simple_balancer', '60059')
    while not os.path.exists('.pcap_send_started_h1'):
        time.sleep(0.1)

    for _ in range(5):
        counter_objects = get_direct_counter_objects(balancer_connection, 'MyIngress.ipv4_exact')
        pprint(counter_objects)
        for counter_object in counter_objects:
            ip = int.from_bytes(counter_object.match.value, 'big')
            counter_entry = balancer_connection.p4info_helper.build_direct_counter_entry(
                table_name= "MyIngress.ipv4_exact",
                match_fields= {
                  "hdr.ipv4.srcAddr": ip
                },
                packet_count= 0,
                byte_count= 0
            )
            if counter_object.packet_count > 1:
                target_port = 3
            else:
                target_port = 2

            print(f'Zero counters and set route to {target_port} port')
            balancer_connection.connection.WriteDirectCounterEntry(counter_entry)
            ip_str = str(ipaddress.ip_address(ip))
            requests.post('http://127.0.0.1:8080/set_route', json={'source_address': ip_str, 'target_port': target_port}).raise_for_status()
        time.sleep(1)
