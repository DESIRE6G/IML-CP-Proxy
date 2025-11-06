#!/usr/bin/env python3
import json
import logging
import sys
from enum import Enum

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

        for i, arrived_packet in enumerate(packets_arrived):
            message(f'----- {i+1}. packet')
            src = arrived_packet[IP].src
            payload = bytes(arrived_packet[IP].payload)
            message(f'Ip: {src} Payload: {payload} = {[int(x) for x in payload]}')
            packet_index = bytes(arrived_packet[IP].payload)[0]
            route_index = bytes(arrived_packet[IP].payload)[2]


            if src == '10.0.1.13' and route_index == 2 and packet_index in [0,3,6,9,12,15]:
                message('OK')
                continue

            if src == '10.0.1.25':
                if packet_index in [4, 7] and route_index == 3:
                    message('OK')
                    continue

                if packet_index in [13] and route_index == 4:
                    message('OK')
                    continue

            if src == '10.0.1.33':
                if packet_index in [8] and route_index == 4:
                    message('OK')
                    continue

                if packet_index in [11, 14, 17] and route_index == 2:
                    message('OK')
                    continue


            message('failed')

            output_object['success'] = False
            break

        if len(packets_arrived) != 13:
            message(f'failed, not correct packet num. Arrived packet num: {len(packets_arrived)}')
            output_object['success'] = False

        with open(f'test_output{host_postfix}.json','w') as f:
            json.dump(output_object, f, indent = 4)
