#!/usr/bin/env python3
import json
import logging

from common.logging_helper import configure_logger_with_common_settings
from common.traffic_helper import PacketReceiver

configure_logger_with_common_settings('receive.log')
from scapy.all import (
    IP,
)

if __name__ == '__main__':
    host_postfix = '_h2'
    with PacketReceiver(host_postfix) as packets_arrived:
        output_object = {'success':True, 'message': ''}

        def message(msg):
            logging.debug(msg)
            output_object['message'] += f'{msg}\n'

        WANTED_PACKETS = [
            [0,2, '10.0.1.13'],
            [1,2, '10.0.1.25'],

            [2,2, '10.0.1.13'],
            [3,2, '10.0.1.13'],
            [4,2, '10.0.1.25'],

            [5,[2,3], '10.0.1.13'],
            [6,[2,3], '10.0.1.13'],
            [7,2, '10.0.1.25'],

            [8,3, '10.0.1.13'],
            [9,2, '10.0.1.25'],

            [10,2, '10.0.1.13'],
            [11,2, '10.0.1.25']
        ]

        wanted_packet_iterator = 0
        for i, arrived_packet in enumerate(packets_arrived):
            message(f'----- {i+1}. packet')
            src = arrived_packet[IP].src
            payload = bytes(arrived_packet[IP].payload)
            message(f'Ip: {src} Payload: {payload} = {[int(x) for x in payload]}')
            packet_index = bytes(arrived_packet[IP].payload)[0]
            route_index = bytes(arrived_packet[IP].payload)[2]

            actual_wanted_packet = WANTED_PACKETS[wanted_packet_iterator]
            wanted_packet_iterator += 1

            if isinstance(actual_wanted_packet[1], list):
                route_ok = route_index in actual_wanted_packet[1]
            else:
                route_ok = route_index == actual_wanted_packet[1]

            if actual_wanted_packet[0] == packet_index and route_ok and src == actual_wanted_packet[2]:
                message('OK')
                continue

            message(f'failed, should be {actual_wanted_packet}')

            output_object['success'] = False
            break

        if output_object['success'] == True and len(packets_arrived) != len(WANTED_PACKETS):
            message(f'failed, not correct packet num. Arrived packet num: {len(packets_arrived)}, Wanted: {len(WANTED_PACKETS)}')
            output_object['success'] = False

        with open(f'test_output{host_postfix}.json','w') as f:
            json.dump(output_object, f, indent = 4)
