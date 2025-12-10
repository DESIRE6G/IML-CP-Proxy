#!/usr/bin/env python3
import time

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection
from google.protobuf.json_format import MessageToJson

with ControllerExceptionHandling():
    expected_entries_json = []

    s1 = HighLevelSwitchConnection(0, 'basicv3', '60051', host='p4runtime-proxy')
    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm1",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.20', 32)
        },
        action_name="MyIngress.chg_addr",
        action_params={
            'port': 2,
            'dstAddr': '08:00:00:00:02:00',
        }
    )
    s1.connection.WriteTableEntry(table_entry)
    expected_entries_json.append(MessageToJson(table_entry))


    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_lpm2",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.20', 32)
        },
        action_name="MyIngress.set_port"
    )
    s1.connection.WriteTableEntry(table_entry)
    expected_entries_json.append(MessageToJson(table_entry))


    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.just_another",
        match_fields={
            "hdr.ethernet.dstAddr": '08:00:00:00:02:23'
        },
        action_name="MyIngress.drop"
    )
    s1.connection.WriteTableEntry(table_entry)
    expected_entries_json.append(MessageToJson(table_entry))
    
    
    for response in s1.connection.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            entry_json = MessageToJson(entry)
            expected_entries_json.remove(entry_json)
            try:
               print('----------------')
               print(f'Filled table entry in: {s1.p4info_helper.get_tables_name(entry.table_id)}')
               print(entry)
            except AttributeError as e:
                print(e)

    if len(expected_entries_json) > 0:
        print(f"Missing {len(expected_entries_json)} entries", flush=True)
        for expected_entry in expected_entries_json:
            print(expected_entry)

        raise Exception(f"Verification Failed: {len(expected_entries_json)} missing entries.")

    print('Tables filled successfully', flush=True)
    time.sleep(2)