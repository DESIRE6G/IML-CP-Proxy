#!/usr/bin/env python3
import os
import sys

import grpc

from common.high_level_switch_connection import HighLevelSwitchConnection

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../../utils/'))
from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

def config_response_simple_forward():
    s1 = HighLevelSwitchConnection(0, 'fwd')
    s2 = HighLevelSwitchConnection(1, 'fwd')
    # PING response can come on this line (s1 and s2 has same p4info)
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.1.1', 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:01:11',
            "port": 1
        })
    s1.connection.WriteTableEntry(table_entry)
    s2.connection.WriteTableEntry(table_entry)

    # s2 forwards packet to h2 if arrives
    table_entry = s2.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 2
        })
    s2.connection.WriteTableEntry(table_entry)


    # s1 forwards packet to the experimental track
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 3
        })
    s1.connection.WriteTableEntry(table_entry)

def config_not_aggregated_controller():

    s3 = HighLevelSwitchConnection(2, 'basic_part1', '60053')
    s4 = HighLevelSwitchConnection(3, 'basic_part2', '60054')

    table_entry = s3.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm1",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.chg_addr",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 2
        })
    s3.connection.WriteTableEntry(table_entry)


    table_entry = s4.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm2",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.set_port",
        )
    s4.connection.WriteTableEntry(table_entry)

if __name__ == '__main__':
    try:
        config_response_simple_forward()
        config_not_aggregated_controller()
    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

