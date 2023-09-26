#!/usr/bin/env python3
import sys
import redis
import json

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

redis = redis.Redis()


def compare_redis(redis_file):
    success = True
    with open(redis_file, 'r') as f:
        target_redis_content = json.load(f)
        for table_obj in target_redis_content:
            redis_key = table_obj['key']
            if "list" in table_obj:
                for index, data_one_record in enumerate(table_obj["list"]):
                    if redis.lindex(redis_key, index).decode('utf8') != data_one_record:
                        print(f'{redis_key} differs from the expected!')
                        success = False

            if "string" in table_obj:
                if(redis.get(redis_key).decode('utf8')) != table_obj['string']:
                    print(f'{redis_key} differs from the expected!')
                    success = False


    return success


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
    
    success = success and compare_redis('../testcases/l2fwd/subtests/load_from_redis/redis.json')

    ShutdownAllSwitchConnections()

    if success:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
