#!/usr/bin/env python3
import os
import sys
import time

import grpc

from common.high_level_switch_connection import HighLevelSwitchConnection

from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

if __name__ == '__main__':
    try:
        s1 = HighLevelSwitchConnection(0, 'direct_meter', '60051')

        table_entry = s1.p4info_helper.buildTableEntry(
            table_name="MyIngress.m_read",
            match_fields={
                "hdr.ethernet.srcAddr": '08:00:00:00:01:11'
            },
            action_name="MyIngress.m_action")
        s1.connection.WriteTableEntry(table_entry)

        table_entry = s1.p4info_helper.buildTableEntry(
            table_name="MyIngress.m_filter",
            match_fields={
                "meta.meter_tag": 0
            },
            action_name="NoAction")
        s1.connection.WriteTableEntry(table_entry)

        meter_entry = s1.p4info_helper.buildDirectMeterConfigEntry('MyIngress.m_read',
            {
                "hdr.ethernet.srcAddr": '08:00:00:00:01:11'
            },cir=1,cburst=1,pir=2,pburst=2000000)
        s1.connection.WriteDirectMeterEntry(meter_entry)
    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()
