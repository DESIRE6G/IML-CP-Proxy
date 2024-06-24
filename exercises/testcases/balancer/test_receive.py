#!/usr/bin/env python3
import json
import logging
import sys
from enum import Enum

from common.logging_helper import configure_logger_with_common_settings
from common.traffic_helper import compare_packet_lists, PacketReceiver

configure_logger_with_common_settings('receive.log')
from scapy.all import (
    IP,
)

if __name__ == '__main__':
    with PacketReceiver() as packets_arrived:
        class Phase(Enum):
            NOT_ARRIVED = 0
            NODE1_ARRIVED = 1
            MOVED_TO_NODE2 = 2
            MOVED_BACK_TO_NODE1 = 3

        phase = Phase.NOT_ARRIVED

        output_object = {'success':True, 'message': ''}

        def message(msg):
            logging.debug(msg)
            output_object['message'] += f'{msg}\n'

        for i, arrived_packet in enumerate(packets_arrived):
            message(f'----- Packet {i}')
            message(f'Ip: {arrived_packet[IP].src} Payload: {bytes(arrived_packet[IP].payload)}')
            if arrived_packet[IP].src == '10.0.1.25':
                if bytes(arrived_packet[IP].payload)[1] == 10:
                    message('10.0.1.25 IP with 10 route flag. OK')
                    continue

            if arrived_packet[IP].src == '10.0.1.13':
                if bytes(arrived_packet[IP].payload)[1] == 10 and (phase == Phase.NOT_ARRIVED or phase == Phase.NODE1_ARRIVED):
                    message('10.0.1.13 IP with 10 route flag ON START. OK')
                    phase = Phase.NODE1_ARRIVED
                    continue

                if bytes(arrived_packet[IP].payload)[1] == 11 and (phase == Phase.NODE1_ARRIVED or phase == Phase.MOVED_TO_NODE2):
                    message('10.0.1.13 IP with 11 route, move succeed. OK')
                    phase = Phase.MOVED_TO_NODE2
                    continue

                if bytes(arrived_packet[IP].payload)[1] == 10 and (phase == Phase.MOVED_TO_NODE2 or phase == Phase.MOVED_BACK_TO_NODE1):
                    message('10.0.1.13 IP with 10 route again, move back suceed. OK')
                    phase = Phase.MOVED_BACK_TO_NODE1
                    continue

            message('failed')

            output_object['success'] = False
            break

        if phase != Phase.MOVED_BACK_TO_NODE1:
            message('Did not moved back to node 1, so failed')
            output_object['success'] = False


        with open('test_output.json','w') as f:
            json.dump(output_object, f, indent = 4)
