#!/usr/bin/env python3
import argparse
import sys
import time

from p4.v1 import p4runtime_pb2

from common.controller_helper import get_now_ts_us_int32
from common.high_level_switch_connection import HighLevelSwitchConnection

parser = argparse.ArgumentParser(prog='Validator')
parser.add_argument('--batch_size', default=1, type=int)
parser.add_argument('--sender_num', default=1, type=int)
parser.add_argument('--rate_limit', default=None)
parser.add_argument('--target_port', default='60051')
args = parser.parse_args()

if __name__ == '__main__':
    s = [HighLevelSwitchConnection(i, f'part{i+1}', str(int(args.target_port) + 1), rate_limit=args.rate_limit)
         for i in range(args.sender_num)]

    counter = 0
    while True:
        request = p4runtime_pb2.WriteRequest()
        request.device_id = 0
        request.election_id.low = 1
        ts = get_now_ts_us_int32()
        actual_target_index = counter % args.sender_num
        for _ in range(args.batch_size):
            table_entry = s[actual_target_index].p4info_helper.buildTableEntry(
            table_name="MyIngress.state_setter",
                match_fields={
                    'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
                },
                action_name="MyIngress.state_set",
                action_params={
                    "newState": ts
                }
            )
            update = request.updates.add()
            update.type = p4runtime_pb2.Update.INSERT
            update.entity.table_entry.CopyFrom(table_entry)
        s[actual_target_index].connection.client_stub.Write(request)

        counter += 1