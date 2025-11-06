#!/usr/bin/env python3
import os
import time
from pathlib import Path

import requests

from common.controller_helper import ControllerExceptionHandling
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
    requests.post('http://127.0.0.1:8080/set_route', json={'source_address': '10.0.1.13', 'target_port': 2}).raise_for_status()

    table_entry = s1.p4info_helper.buildTableEntry(
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
    table_entry = s1.p4info_helper.buildTableEntry(
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
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_exact",
        match_fields={
            "hdr.ipv4.dstAddr": '10.0.2.33'
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

    requests.post('http://127.0.0.1:8080/add_node', json={'host': '127.0.0.1', 'port': 50053, 'device_id':2}).raise_for_status()
    requests.post('http://127.0.0.1:8080/set_route', json={'source_address': '10.0.1.25', 'target_port': 3}).raise_for_status()
    while time.time() - start_time < 1.5:
        time.sleep(0.1)

    requests.post('http://127.0.0.1:8080/add_node', json={
        'host': '127.0.0.1',
        'port': 50054,
        'device_id':3,
        'filter_params_allow_only': {'hdr.ipv4.dstAddr': ['10.0.2.33']}
    }).raise_for_status()
    requests.post('http://127.0.0.1:8080/set_route', json={'source_address': '10.0.1.33', 'target_port':4}).raise_for_status()

    while time.time() - start_time < 2.5:
        time.sleep(0.1)
    requests.post('http://127.0.0.1:8080/set_route', json={'source_address': '10.0.1.33','target_port': 2}).raise_for_status()
    requests.post('http://127.0.0.1:8080/set_route', json={'source_address': '10.0.1.25','target_port': 4}).raise_for_status()

    while time.time() - start_time < 3.5:
        time.sleep(0.1)

    requests.post('http://127.0.0.1:8080/add_to_filter', json={
        'host': '127.0.0.1',
        'port': 50054,
        'filter': {'hdr.ipv4.dstAddr': ['10.0.2.25']}
    }).raise_for_status()

    while time.time() - start_time < 4.5:
        time.sleep(0.1)
    requests.post('http://127.0.0.1:8080/remove_node', json={'host': '127.0.0.1', 'port': 50053}).raise_for_status()
    requests.post('http://127.0.0.1:8080/remove_from_filter', json={
        'host': '127.0.0.1',
        'port': 50054,
        'filter': {'hdr.ipv4.dstAddr': ['10.0.2.25']}
    }).raise_for_status()

