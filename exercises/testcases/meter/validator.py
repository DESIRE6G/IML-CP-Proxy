#!/usr/bin/env python3
import sys

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.redis_helper import compare_redis
from common.validator_tools import Validator

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'meter1', '60051')
    validator = Validator()

    config = next(s1.connection.ReadMeters(s1.p4info_helper.get_meters_id('my_meter'))).entities[0].meter_entry.config
    validator.should_be_equal(0, config.cir)
    validator.should_be_equal(1, config.cburst)
    validator.should_be_equal(2, config.pir)
    validator.should_be_equal(200, config.pburst)

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
