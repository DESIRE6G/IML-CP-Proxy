#!/usr/bin/env python3
import sys

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.redis_helper import compare_redis
from common.validator_tools import Validator

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'direct_meter', '60051', send_p4info=False)
    validator = Validator()
    result = s1.connection.ReadDirectMeters(s1.p4info_helper.get_tables_id('m_read'))
    config = next(result).entities[0].direct_meter_entry.config
    validator.should_be_equal(0, config.cir)
    validator.should_be_equal(1, config.cburst)
    validator.should_be_equal(5, config.pir)
    validator.should_be_equal(50, config.pburst)

    validator.should_be_true(compare_redis('redis.json'))

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
