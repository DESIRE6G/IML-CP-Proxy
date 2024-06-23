#!/usr/bin/env python3
import ipaddress
import queue
import time

from common.balancer import Balancer
from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'balancer', '50051')
    s2 = HighLevelSwitchConnection(1, 'flagged_portfwd', '50052')
    s3 = HighLevelSwitchConnection(2, 'flagged_portfwd', '50053')

    balancer = Balancer(s1)
    balancer.add_node(s2, 2)
    balancer.add_node(s3, 3)

    table_entry = s2.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.13', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 2
        })
    s2.connection.WriteTableEntry(table_entry)
    table_entry = s2.p4info_helper.buildTableEntry(
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
    table_entry = s2.p4info_helper.buildTableEntry(
        table_name="MyIngress.flagger",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.0', 24)
        },
        action_name="MyIngress.set_flag",
        action_params={
            "flag": 10
        })
    s2.connection.WriteTableEntry(table_entry)
    table_entry = s3.p4info_helper.buildTableEntry(
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
    table_entry = s4.p4info_helper.buildTableEntry(
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

    s1_recv_queue = queue.Queue()
    s1.subscribe_to_stream_with_queue(s1_recv_queue)
    s1.connection.WriteDigest(s1.p4info_helper.get_digests_id('color_change_digest_t'))
    # Important message for the testing system, do not remove :)
    print('Controller is ready')

    try:
        while True:
            stream_message_response = s1_recv_queue.get(block=True, timeout=5)
            print(stream_message_response)
            ip, color = [int.from_bytes(member.bitstring, 'big') for member in stream_message_response.message.digest.data[0].struct.members]
            print(ip, color, ipaddress.ip_address(ip))
            balancer.set_target_node(str(ipaddress.ip_address(ip)), color)
    except queue.Empty:
        pass