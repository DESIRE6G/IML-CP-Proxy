#!/usr/bin/env python3
import json
import logging
from datetime import datetime

from common.logging_helper import configure_logger_with_common_settings
from common.traffic_helper import PacketReceiver

configure_logger_with_common_settings('receive.log')
from scapy.all import (
    IP, Raw
)

def ns_ts_to_iso(ns_ts: int) -> str:
    return datetime.fromtimestamp(ns_ts / 10**9).isoformat()

if __name__ == '__main__':
    with PacketReceiver(attach_timestamps=True) as packets_arrived:
        output_object = {'success':True, 'message': '', 'latencies': []}


        def message(msg):
            #logging.debug(msg)
            output_object['message'] += f'{msg}\n'

        measured_table_write_time_passed_list = []
        last_table_write_time = 0
        for i, arrived_packet_tuple in enumerate(packets_arrived):
            arrived_packet, arrived_packet_ts = arrived_packet_tuple
            message(f'----- Packet {i}')
            send_time = int.from_bytes(bytes(arrived_packet[Raw])[:8], 'big')
            table_write_time = int.from_bytes(bytes(arrived_packet[Raw])[8:], 'big')
            transfer_time_sec = (arrived_packet_ts - send_time) / 10 ** 9
            table_write_time_passed = (arrived_packet_ts - table_write_time) / 10 ** 9
            message(f'{send_time=} {table_write_time=} {arrived_packet_ts=}')
            message(f'{ns_ts_to_iso(send_time)=} {ns_ts_to_iso(table_write_time)=} {ns_ts_to_iso(arrived_packet_ts)=}')
            message(f'{transfer_time_sec=}')
            message(f'{table_write_time_passed=}')
            if table_write_time != last_table_write_time:
                message(f'>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> {table_write_time_passed=}')
                measured_table_write_time_passed_list.append(table_write_time_passed)
                last_table_write_time = table_write_time
        print(measured_table_write_time_passed_list)
        output_object['latencies'] = measured_table_write_time_passed_list
        with open('test_output.json','w') as f:
            json.dump(output_object, f, indent = 4)
