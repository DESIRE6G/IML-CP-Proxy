#!/usr/bin/env python3
import sys
import time

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.redis_helper import compare_redis, wait_heartbeats_in_redis

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'part1', '60051')
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.state_set",
        action_params={
            "newState":66
        })
    for i in range(2000 * 5):
        s1.connection.WriteTableEntry(table_entry)
        time.sleep(1/10000)
