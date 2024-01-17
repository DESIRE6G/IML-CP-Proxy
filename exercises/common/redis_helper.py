import dataclasses
import json
import time
from dataclasses import dataclass
from enum import Enum
from pprint import pprint
from typing import List

import redis

from common.sync import wait_for_condition_blocking

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
    ENTRIES: RedisRecord = RedisRecord(postfix='ENTRIES', type=RedisFieldType.LIST)
    HEARTBEAT: RedisRecord = RedisRecord(postfix='HEARTBEAT', type=RedisFieldType.STRING)

@dataclass
class RedisKeys:
    TABLE_ENTRIES: str
    P4INFO: str
    ENTRIES: str
    HEARTBEAT: str

def json_equals(json1: str, json2: str) -> bool:
    return json.dumps(json.loads(json1)) == json.dumps(json.loads(json1))


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
                    elif not json_equals(raw_result.decode('utf8'), data_one_record):
                        print(f'{redis_key} at {index} index differs from the expected!')
                        print('------ REDIS DATA')
                        print(raw_result.decode('utf8'))
                        print('------ EXPECTED')
                        print(data_one_record)
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


def wait_heartbeats_in_redis(prefixes, verbose: bool = False):
    def wait_function():
        redis_key = f'{prefix}{RedisRecords.HEARTBEAT.postfix}'

        redis_value = redis.get(redis_key)
        if verbose:
            print(f'redis_key={redis_key}, redis_value={redis_value}')

        if redis_value is None:
            return False


        return float(redis_value) > start_time

    start_time = time.time()
    for prefix in prefixes:
        wait_for_condition_blocking(wait_function)

def save_redis_to_json_file(redis_file: str) -> None:
    redis_records_fields = dataclasses.fields(RedisRecords())

    output = []

    redis_keys: List[str] = [x.decode('ascii') for x in redis.keys() if not x.decode('ascii').endswith(RedisRecords.HEARTBEAT.postfix)]
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
