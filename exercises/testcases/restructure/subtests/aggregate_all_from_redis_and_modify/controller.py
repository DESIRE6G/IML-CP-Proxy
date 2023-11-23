#!/usr/bin/env python3
import grpc

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections


if __name__ == '__main__':
    try:
        s3 = HighLevelSwitchConnection(2, 'part3', '60053')
        table_entry = s3.p4info_helper.buildTableEntry(
            table_name="MyIngress.state_setter",
            match_fields={
                'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
            },
            action_name="MyIngress.state_set",
            action_params={
                "newState": 89
            })
        s3.connection.WriteTableEntry(table_entry, update_type= 'MODIFY')
    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

