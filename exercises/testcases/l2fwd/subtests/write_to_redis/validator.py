#!/usr/bin/env python3
import sys

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.redis_helper import compare_redis

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(2, 'basic_part1', '60053', send_p4info=False)
    s2 = HighLevelSwitchConnection(3, 'basic_part2', '60054', send_p4info=False)

    success = True
    
    success = success and compare_redis('redis.json')

    ShutdownAllSwitchConnections()

    if success:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
