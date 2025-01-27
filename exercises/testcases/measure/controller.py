#!/usr/bin/env python3
import argparse
import json
import os.path
import sys
import time
from pathlib import Path
import numpy as np

from p4.v1 import p4runtime_pb2

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.convert import decodeMac
from common.rates import TickOutputJSON

parser = argparse.ArgumentParser(prog='Validator')
parser.add_argument('--batch_size', default=1, type=int)
parser.add_argument('--sender_num', default=1, type=int)
parser.add_argument('--rate_limit', default=None, type=int)
parser.add_argument('--target_port', default='60051')
args = parser.parse_args()

if __name__ == '__main__':
    s = [HighLevelSwitchConnection(i, f'measure', int(args.target_port) + i, rate_limit=args.rate_limit)
         for i in range(args.sender_num)]

    test_runtime = 5
    counter = 0
    update_counter = 0
    start_time = time.time()
    start_mac_int = 0x080000000222
    while time.time() - start_time < test_runtime:
        request = p4runtime_pb2.WriteRequest()
        request.device_id = 0
        request.election_id.low = 1
        actual_target_index = counter % args.sender_num
        for _ in range(args.batch_size):

            actual_mac_int = start_mac_int + update_counter
            actual_mac_bytes = actual_mac_int.to_bytes(6, 'big')
            actual_mac_str = ':'.join(hex(s)[2:].rjust(2,'0') for s in actual_mac_bytes)
            table_entry = s[actual_target_index].p4info_helper.buildTableEntry(
            table_name="MyIngress.table_entry_drop_counter",
                match_fields={
                    'hdr.ethernet.dstAddr': actual_mac_str
                },
                action_name="MyIngress.mock_action",
                action_params={
                    "packet_count": update_counter
                }
            )
            update = request.updates.add()
            update.type = p4runtime_pb2.Update.INSERT
            update.entity.table_entry.CopyFrom(table_entry)
            update_counter += 1
        s[actual_target_index].connection.client_stub.Write(request)

        counter += 1

    table_write_measure_result = None
    for response in s[0].connection.ReadTableEntries():
        print(f'{len(response.entities)}/{update_counter}')
        table_write_measure_result = len(response.entities)/test_runtime

    s[0].connection.purge_rate_limiter_buffer()
    Path('.controller_ready').touch()

    while not os.path.exists('.pcap_send_started'):
        time.sleep(0.1)

    def generate_timed_table_entry():
        return s[0].p4info_helper.buildTableEntry(
            table_name="MyIngress.table_write_time",
            match_fields={
                'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
            },
            action_name="MyIngress.write_time",
            action_params={
                "table_write_time": time.time_ns()
            })
    time.sleep(0.5)
    s[0].connection.WriteTableEntry(generate_timed_table_entry())
    start_time = time.time()
    while time.time() - start_time < 4:
        s[0].connection.WriteTableEntry(generate_timed_table_entry(), update_type='MODIFY')
        time.sleep(0.2)

    while not os.path.exists('.pcap_receive_finished'):
        time.sleep(0.1)


    with open('test_output.json', 'r') as test_output_f, open('ticks.json', 'w') as f:
        latencies = json.load(test_output_f)['latencies']
        output = TickOutputJSON(
            tick_per_sec_list=[table_write_measure_result],
            average=table_write_measure_result,
            stdev=0,
            delay_list=latencies,
            delay_average=np.mean(latencies),
            delay_stdev=np.std(latencies)
        )
        f.write(output.model_dump_json(indent=4))

    Path('.controller_finished').touch()
    print('Touched .controller_finished')