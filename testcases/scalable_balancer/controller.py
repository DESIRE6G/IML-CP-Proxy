#!/usr/bin/env python3
import os
import time
from pathlib import Path

import requests

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'fwd_with_count_per_ip', '60051')

    response = requests.post('http://127.0.0.1:8080/add_node', json={'host': '127.0.0.1', 'port': 50052, 'device_id':1})
    response.raise_for_status()

    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.13', 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:00',
            "port": 2
        })
    s1.connection.WriteTableEntry(table_entry)
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.25', 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:00',
            "port": 2
        })
    s1.connection.WriteTableEntry(table_entry)
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.33', 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:00',
            "port": 2
        })
    s1.connection.WriteTableEntry(table_entry)
    Path('.controller_ready').touch()

    while not os.path.exists('.pcap_send_started_h1'):
        time.sleep(0.05)
    start_time = time.time()


    while time.time() - start_time < 0.5:
        time.sleep(0.1)

    response = requests.post('http://127.0.0.1:8080/add_node', json={'host': '127.0.0.1', 'port': 50053, 'device_id':2})
    response.raise_for_status()
    while time.time() - start_time < 1.5:
        time.sleep(0.1)

    response = requests.post('http://127.0.0.1:8080/add_node', json={'host': '127.0.0.1', 'port': 50054, 'device_id':3})
    response.raise_for_status()