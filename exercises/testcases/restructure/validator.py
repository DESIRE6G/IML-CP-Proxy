#!/usr/bin/env python3
import sys

from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.redis_helper import compare_redis

if __name__ == '__main__':
    success = True
    
    success = success and compare_redis('redis.json')

    ShutdownAllSwitchConnections()

    if success:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
