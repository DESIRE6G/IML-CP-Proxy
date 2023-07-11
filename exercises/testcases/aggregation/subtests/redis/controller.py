#!/usr/bin/env python3
import os
import sys

import grpc

from common.high_level_switch_connection import HighLevelSwitchConnection

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


def main(aggregated = False):
    try:
        config_response_simple_forward()
        #config_aggregated_controller()
    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    main(aggregated=True)
