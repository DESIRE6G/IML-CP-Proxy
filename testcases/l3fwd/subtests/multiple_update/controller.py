#!/usr/bin/env python3
from p4.v1 import p4runtime_pb2

from common.controller_helper import create_experimental_model_forwards, ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection

with ControllerExceptionHandling():
    create_experimental_model_forwards()
    s3 = HighLevelSwitchConnection(2, 'basic_part1', '60053')
    s4 = HighLevelSwitchConnection(3, 'basic_part2', '60054')

    request = p4runtime_pb2.WriteRequest()
    request.device_id = 2
    request.election_id.low = 1

    update = request.updates.add()
    table_entry = s3.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm1",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.chg_addr",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 21
        })
    update.type = p4runtime_pb2.Update.INSERT
    update.entity.table_entry.CopyFrom(table_entry)

    update = request.updates.add()
    table_entry = s3.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm1",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.chg_addr",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 2
        })
    update.type = p4runtime_pb2.Update.MODIFY
    update.entity.table_entry.CopyFrom(table_entry)

    update = request.updates.add()
    table_entry = s3.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm1",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.chg_addr",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 2
        })
    update.type = p4runtime_pb2.Update.MODIFY
    update.entity.table_entry.CopyFrom(table_entry)


    s3.connection.client_stub.Write(request)




    table_entry = s4.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm2",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.set_port",
        )
    s4.connection.WriteTableEntry(table_entry)
