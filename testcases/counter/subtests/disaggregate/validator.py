#!/usr/bin/env python3
from pprint import pprint
import sys

from p4.v1 import p4runtime_pb2

from common.controller_helper import get_counter_objects, get_direct_counter_objects, get_counter_objects_by_id, CounterObject
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.redis_helper import wait_heartbeats_in_redis, compare_redis
from common.validator_tools import Validator

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(0, 'fwd_with_counting_aggregated', '60051', send_p4info=False)


    counter1_objects = get_counter_objects(s1, 'MyIngress.NF1_packetCounter')
    counter2_objects = get_counter_objects(s1, 'MyIngress.NF2_packetCounter')
    node1_direct_counter = get_direct_counter_objects(s1, 'MyIngress.NF1_ipv4_lpm')
    all_counters = get_counter_objects_by_id(s1.connection, None)

    print('counter1_objects object:')
    pprint(counter1_objects)

    print('counter2_objects object:')
    pprint(counter2_objects)

    print('node1_direct_counter')
    pprint(node1_direct_counter)

    print('all_counters')
    pprint(all_counters)

    counter1_id = s1.p4info_helper.get_counters_id('MyIngress.NF1_packetCounter')
    counter2_id = s1.p4info_helper.get_counters_id('MyIngress.NF2_packetCounter')
    counter1_packet_only_id = s1.p4info_helper.get_counters_id('MyIngress.NF1_packetCounterOnlyPacket')
    counter2_bytes_only_id = s1.p4info_helper.get_counters_id('MyIngress.NF2_packetCounterOnlyBytes')

    validator = Validator()

    validator.should_be_equal(all_counters[:3], counter1_objects)
    validator.should_be_equal(all_counters[3].counter_id, counter1_packet_only_id)
    validator.should_be_equal(all_counters[4:7], counter2_objects)
    validator.should_be_equal(all_counters[7].counter_id, counter2_bytes_only_id)

    validator.should_be_not_equal(counter1_objects[0].packet_count, 0)
    validator.should_be_not_equal(counter1_objects[0].byte_count, 0)
    validator.should_be_equal(node1_direct_counter[0].packet_count,counter1_objects[0].packet_count / 2)
    validator.should_be_equal(node1_direct_counter[1].packet_count,counter1_objects[0].packet_count / 2)

    validator.should_be_equal(counter1_objects[0].packet_count * 2, counter2_objects[0].packet_count)
    validator.should_be_equal(counter1_objects[0].byte_count * 2, counter2_objects[0].byte_count)

    validator.should_be_equal(counter1_id, counter1_objects[0].counter_id)
    validator.should_be_equal(counter2_id, counter2_objects[0].counter_id)

    validator.should_be_equal(counter1_objects[1].packet_count, 0)
    validator.should_be_equal(counter2_objects[1].packet_count, counter1_objects[0].packet_count)

    validator.should_be_equal(counter2_objects[2].packet_count, 0)
    validator.should_be_equal(counter1_objects[2].packet_count, counter1_objects[0].packet_count * 2)

    counter1packet_objects = get_counter_objects(s1, 'MyIngress.NF1_packetCounterOnlyPacket')
    counter2bytes_objects = get_counter_objects(s1, 'MyIngress.NF2_packetCounterOnlyBytes')

    print('counter1packet_objects object:')
    pprint(counter1packet_objects)

    print('counter2bytes_objects object:')
    pprint(counter2bytes_objects)

    validator.should_be_equal(counter1packet_objects[0].packet_count, counter1_objects[0].packet_count)
    # BMV looks counts packets and bytes regardless of CounterType
    # validator.should_be_equal(counter1packet_objects[0].byte_count, 0)
    validator.should_be_equal(counter2bytes_objects[0].byte_count, counter2_objects[0].byte_count)
    # validator.should_be_equal(counter2bytes_objects[0].packet_count, 0)


    request = p4runtime_pb2.ReadRequest()
    request.device_id = s1.device_id
    entity = request.entities.add()
    entity.counter_entry.counter_id = counter1_id
    entity = request.entities.add()
    entity.counter_entry.counter_id = counter2_id
    response_list = []
    for response in s1.connection.client_stub.Read(request):
        for entity in response.entities:
            response_list.append(CounterObject.from_proto_entry(entity.counter_entry))

    validator.should_be_equal(response_list[:3], counter1_objects)
    validator.should_be_equal(response_list[3:], counter2_objects)


    wait_heartbeats_in_redis(['fwd_with_counting_aggregated_'])
    validator.should_be_true(compare_redis('redis.json'))

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)


