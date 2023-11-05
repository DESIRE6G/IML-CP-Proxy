import json

import redis

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
