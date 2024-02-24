#!/usr/bin/env python3
import sys

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.redis_helper import compare_redis

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(2, 'basic_part1', '60053', send_p4info=False)
    s2 = HighLevelSwitchConnection(3, 'basic_part2', '60054', send_p4info=False)

    success = True
    def check_table_rules(p4info_helper, connection):
        for response in connection.ReadTableEntries():
            for entity in response.entities:
                entry = entity.table_entry
                try:
                   print(f'Table name: {p4info_helper.get_tables_name(entry.table_id)}')
                except AttributeError as e:
                    print(e)
                    return False

        return True

    success = success and check_table_rules(s1.p4info_helper, s1.connection)
    success = success and check_table_rules(s2.p4info_helper, s2.connection)
    success = success and compare_redis('redis.json')

    ShutdownAllSwitchConnections()

    if success:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
