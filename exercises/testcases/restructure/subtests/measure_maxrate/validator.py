#!/usr/bin/env python3
import argparse
import sys
import time

from p4.v1 import p4runtime_pb2

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.redis_helper import compare_redis, wait_heartbeats_in_redis

parser = argparse.ArgumentParser(prog='Validator')
parser.add_argument('batch_size', default=1, type=int)
parser.add_argument('--rate_limit', default=None)
parser.add_argument('--target_port', default='50051')
args = parser.parse_args()

print(f'{args.rate_limit=} {args.target_port=}')
if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'part1', args.target_port, rate_limit=args.rate_limit)
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.state_set",
        action_params={
            "newState":66
        })
    while True:
        request = p4runtime_pb2.WriteRequest()
        request.device_id = 0
        request.election_id.low = 1
        for _ in range(args.batch_size):
            update = request.updates.add()
            update.type = p4runtime_pb2.Update.INSERT
            update.entity.table_entry.CopyFrom(table_entry)
        s1.connection.client_stub.Write(request)
