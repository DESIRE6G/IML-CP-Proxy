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
            message(f'----- Packet {i}')
            message(f'Ip: {arrived_packet[IP].src} Payload: {bytes(arrived_packet[IP].payload)}')

            if arrived_packet[IP].src == '10.0.1.13':
                if bytes(arrived_packet[IP].payload)[2] == 2:
                    message('OK')
                    continue
            if arrived_packet[IP].src == '10.0.1.25':
                if bytes(arrived_packet[IP].payload)[2] == 3:
                    message('OK')
                    continue
            if arrived_packet[IP].src == '10.0.1.33':
                if bytes(arrived_packet[IP].payload)[2] == 4:
                    message('OK')
                    continue

            message('failed')

            output_object['success'] = False
            break

        if len(packets_arrived) != 7:
            message(f'failed, not correct packet num. Arrived packet num: {len(packets_arrived)}')
            output_object['success'] = False

        with open(f'test_output{host_postfix}.json','w') as f:
            json.dump(output_object, f, indent = 4)
