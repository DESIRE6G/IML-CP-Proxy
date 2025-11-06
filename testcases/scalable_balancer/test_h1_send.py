#!/usr/bin/env python3
import random
import sys
import time
from pathlib import Path
import logging
from typing import Union

from scapy.all import sendp, IP, TCP, Ether, wrpcap

from common.logging_helper import configure_logger_with_common_settings
from common.traffic_helper import get_network_interface, PacketSender

configure_logger_with_common_settings('send.log')

iface = get_network_interface()

source_mac = '08:00:00:00:01:11'
dst_mac = '08:00:00:00:02:00'
destination_ips = ['10.0.2.13', '10.0.2.25', '10.0.2.33']
source_ips = ['10.0.1.13', '10.0.1.25', '10.0.1.33']

packet_index = 0

def send_one_packet(choosen_source_id: int) -> None:
    global packet_index
    source_ip = source_ips[choosen_source_id]
    destination_ip = destination_ips[choosen_source_id]
    pkt = Ether(src=source_mac, dst=dst_mac)
    pkt = pkt / IP(src=source_ip, dst=destination_ip) / bytes([packet_index, 0, 0])
    sendp(pkt, iface=iface, verbose=False)
    logging.debug(f'Sent {repr(pkt)}')

    packet_index += 1

with PacketSender():
    # packet index 0-2
    send_one_packet(0) # 0 packet_index -> only this goes, so 1. packet [0, 0, 2]
    send_one_packet(1) # 1 packet_index -> no route
    send_one_packet(2) # 2 packet_index -> no route
    # AT 0.5 sec: add route 3 at 0.5sec
    time.sleep(1)

    # packet index 3-5
    send_one_packet(0) # 3 packet_index -> this goes, so 2. packet [3, 0, 2]
    send_one_packet(1) # 4 packet_index -> this goes, so 3. packet [4, 0, 3]
    send_one_packet(2) # 5 packet_index -> no route

    # At 1.5 sec: add route 4 with filter only to source 2
    time.sleep(1)

    # packet index 6-8
    send_one_packet(0) # 6 packet_index -> 4. packet [6, 0, 2]
    send_one_packet(1) # 7 packet_index -> 5. packet [7, 0, 3]
    send_one_packet(2) # 8 packet_index -> 6. packet [8, 0, 4]

    # At 2.5 sec:
    #   redirect source 2 (33) -> route 2 it will work
    #   redirect source 1 (25) -> route 4 it won't work

    time.sleep(1)

    # packet index 9-11
    send_one_packet(0) # 9 packet_index -> 7. packet [9, 0, 2]
    send_one_packet(1) # 10 packet_index -> source 1 filtered out
    send_one_packet(2) # 11 packet_index -> 8. packet [11, 0, 2]

    # At 3.5 sec: allow source 1 on route 4 filter

    time.sleep(1) # allow 2 route redirected packet
    # packet index 12-14
    send_one_packet(0) # 12 packet_index -> 9. packet [12, 0, 2]
    send_one_packet(1) # 13 packet_index -> 10. packet [13, 0, 4]
    send_one_packet(2) # 14 packet_index -> 11. packet [14, 0, 2]

    # At 4.5 sec: remove_from_filter source 1
    time.sleep(1)
    # packet index 15-17
    send_one_packet(0) # 15 packet_index count -> 12. packet [15, 0, 2]
    send_one_packet(1) # 16 packet_index count -> source 1 filtered out
    send_one_packet(2) # 17 packet_index count -> 13. packet [17, 0, 2]

