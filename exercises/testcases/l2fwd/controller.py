#!/usr/bin/env python3
import grpc

from common.controller_helper import create_experimental_model_forwards
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

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
            "port": 21
        })
    s3.connection.WriteTableEntry(table_entry)
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
    s3.connection.WriteTableEntry(table_entry, modify_request = True)


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
        create_experimental_model_forwards()
        config_not_aggregated_controller()
    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

