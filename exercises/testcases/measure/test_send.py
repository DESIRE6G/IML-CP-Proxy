#!/usr/bin/env python3
import random
import sys
import time
from pathlib import Path
import logging
from typing import Union

from scapy.all import sendp, IP, TCP, Ether, wrpcap

from common.logging_helper import configure_logger_with_common_settings
from common.traffic_helper import get_eth0_interface

configure_logger_with_common_settings('send.log')

iface = get_eth0_interface()

source_mac = '08:00:00:00:01:11'
dst_mac = '08:00:00:00:02:22'


packet_index = 0

def send_packets_for_x_sec(main_flag: int, sending_time: float) -> None:
    global packet_index

    start_time = time.time()
    while time.time() - start_time < sending_time:
        pkt = Ether(src=source_mac, dst=dst_mac) /  bytes(list(time.time_ns().to_bytes(8, 'big')) + [0] * 8)
        sendp(pkt, iface=iface, verbose=False)
        packet_index += 1


pkt = Ether(src=source_mac, dst=dst_mac)

logging.info('Start sending')
Path('.pcap_send_started').touch()
logging.debug('touch .pcap_send_started')
send_packets_for_x_sec(1, 3)
logging.info('Finished sending')

Path('.pcap_send_finished').touch()
logging.debug('touch .pcap_send_finished')
