#!/usr/bin/env python3
import sys
import time

from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.redis_helper import compare_redis, wait_heartbeats_in_redis

if __name__ == '__main__':
    success = True

    wait_heartbeats_in_redis(['part1_','part2_','part3_','part4_'])
    success = success and compare_redis('redis.json')

    ShutdownAllSwitchConnections()

    if success:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
