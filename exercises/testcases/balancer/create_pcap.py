#!/usr/bin/env python3
import random

from scapy.all import IP, TCP, Ether, wrpcap

source_mac = '08:00:00:00:01:11'
dst_mac = '08:00:00:00:02:22'
destination_ip = '10.0.2.2'
source_ips = ['10.0.1.13', '10.0.1.25']

input = []
output = []
for packet_index in range(5):
    choosen_source_id = random.randint(0,len(source_ips) - 1)

    source_ip = source_ips[choosen_source_id]
    pkt =  Ether(src=source_mac, dst=dst_mac)
    pkt = pkt /IP(src=source_ip, dst=destination_ip) / bytes([packet_index, 0])
    input.append(pkt)

    pkt =  Ether(src=source_mac, dst=dst_mac)
    pkt = pkt /IP(src=source_ip, dst=destination_ip) / bytes([packet_index, choosen_source_id + 10])
    output.append(pkt)

wrpcap('test_h1_input.pcap', input)
wrpcap('test_h2_expected.pcap', output)