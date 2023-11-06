import dataclasses
import json
from dataclasses import dataclass
from enum import Enum
from pprint import pprint
from typing import List, Dict

import redis

redis = redis.Redis()

class RedisFieldType(Enum):
    LIST = 'LIST'
    STRING = 'STRING'

@dataclass
class RedisRecord:
    postfix: str
    type: RedisFieldType

@dataclass
class RedisRecords:
    TABLE_ENTRIES: RedisRecord = RedisRecord(postfix='TABLE_ENTRIES', type=RedisFieldType.LIST)
    P4INFO: RedisRecord = RedisRecord(postfix='P4INFO', type=RedisFieldType.STRING)
    COUNTER: RedisRecord = RedisRecord(postfix='COUNTER', type=RedisFieldType.LIST)

@dataclass
class RedisKeys:
    TABLE_ENTRIES: str
    P4INFO: str
    COUNTER: str

def compare_redis(redis_file: str) -> bool:
    success = True
    with open(redis_file, 'r') as f:
        target_redis_content = json.load(f)
        for table_obj in target_redis_content:
            redis_key = table_obj['key']
            if "list" in table_obj:
                for index, data_one_record in enumerate(table_obj["list"]):
                    raw_result = redis.lindex(redis_key, index)
                    if raw_result is None:
                        print(f'{redis_key} key not exists!')
                        success = False
                    elif raw_result.decode('utf8') != data_one_record:
                        print(f'{redis_key} at {index} index differs from the expected!')
                        success = False
                    else:
                        print(f'{redis_key} OK')

            if "string" in table_obj:
                raw_result = redis.get(redis_key)
                if raw_result is None:
                    print(f'{redis_key} key not exists!')
                    success = False
                elif raw_result.decode('utf8') != table_obj['string']:
                    print(f'{redis_key} differs from the expected!')
                    success = False
                else:
                    print(f'{redis_key} OK')

    return success


def save_redis_to_json_file(redis_file: str) -> None:
    redis_records_fields = dataclasses.fields(RedisRecords())

    output = []

    redis_keys: List[str] = [x.decode('ascii') for x in redis.keys()]
    print(f'redis_keys = {redis_keys}')
    for redis_record_field in redis_records_fields:
        for redis_key in redis_keys:
            if redis_record_field.default.postfix in redis_key:
                print(redis_key, redis_record_field.default)
                output_row = {'key':redis_key}
                if redis_record_field.default.type == RedisFieldType.STRING:
                    output_row['string'] = redis.get(redis_key).decode('utf8')
                elif redis_record_field.default.type == RedisFieldType.LIST:
                    output_row['list'] = [x.decode('utf8') for x in redis.lrange(redis_key, 0, -1)]
                else:
                    raise Exception(f'Cannot store {redis_key} field, because of unknown type of {redis_record_field.default.type}')

                output.append(output_row)
    pprint(output)
    with open(redis_file, 'w') as f:
        json.dump(output, f, indent=4)
