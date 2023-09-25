#!/usr/bin/env python3
import os
import sys
import time

import grpc

from common.high_level_switch_connection import HighLevelSwitchConnection

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../../utils/'))
from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

if __name__ == '__main__':
    try:
        s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051')
        s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052')
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
        s1.connection.WriteTableEntry(table_entry)
        s2.connection.WriteTableEntry(table_entry)

    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()
