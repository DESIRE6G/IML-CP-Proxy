#!/usr/bin/env python3
import random
import sys
import time
from pathlib import Path
import logging
from typing import Union

from scapy.all import sendp, IP, TCP, Ether, wrpcap

from common.logging_helper import configure_logger_with_common_settings
from common.traffic_helper import get_eth0_interface, PacketSender

configure_logger_with_common_settings('send.log')

iface = get_eth0_interface()

source_mac = '08:00:00:00:01:11'
dst_mac = '08:00:00:00:02:00'
destination_ip = '10.0.2.2'
source_ips = ['10.0.1.13', '10.0.1.25', '10.0.1.33']

packet_index = 0

def send_one_packet(choosen_source_id: int) -> None:
    global packet_index
    source_ip = source_ips[choosen_source_id]
    pkt = Ether(src=source_mac, dst=dst_mac)
    pkt = pkt / IP(src=source_ip, dst=destination_ip) / bytes([packet_index, 0, 0])
    sendp(pkt, iface=iface, verbose=False)
    logging.debug(f'Sent {repr(pkt)}')

    packet_index += 1

with PacketSender():
    send_one_packet(0)
    send_one_packet(1)
    send_one_packet(2)
    time.sleep(1)
    send_one_packet(0)
    send_one_packet(1)
    # at absolute 2 sec add third node
    time.sleep(2)
    send_one_packet(0)
    send_one_packet(1)
    send_one_packet(2)