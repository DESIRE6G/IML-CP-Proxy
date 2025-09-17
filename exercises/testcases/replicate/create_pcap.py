#!/usr/bin/env python3
import random

from scapy.all import IP, TCP, Ether, wrpcap

source_mac = '08:00:00:00:01:11'
router_dst_mac = '08:00:00:00:02:00'
dst_mac = '08:00:00:00:02:22'
source_ip = '10.0.2.2'
destination_ips = ['10.0.1.13', '10.0.1.25', '10.0.1.33', '10.0.1.44']
forwarded_ips = [True, True, False, False]

input = []
output = []
for packet_index in range(10):
    choosen_source_id = random.randint(0, len(destination_ips) - 1)

    destination_ip = destination_ips[choosen_source_id]
    pkt =  Ether(src=source_mac, dst=router_dst_mac)
    pkt = pkt / IP(src=source_ip, dst=destination_ip, ttl=64) / bytes([packet_index, 0])
    input.append(pkt)

    if forwarded_ips[choosen_source_id]:
        pkt =  Ether(src=router_dst_mac, dst=dst_mac)
        pkt = pkt / IP(src=source_ip, dst=destination_ip, ttl=63) / bytes([packet_index, 1 if packet_index % 2 == 0 else 2])
        output.append(pkt)

wrpcap('test_h1_input.pcap', input)
wrpcap('test_h2_expected.pcap', output)