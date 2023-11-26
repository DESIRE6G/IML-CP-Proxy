#!/usr/bin/env python3
import random

from scapy.all import IP, TCP, Ether, wrpcap

source_mac = '08:00:00:00:01:11'
destination_ip = '10.0.2.2'
destination_port = 1234

output = []
for packet_index in range(5):
    pkt =  Ether(src=source_mac, dst='ff:ff:ff:ff:ff:ff')
    pkt = pkt /IP(dst=destination_ip) / TCP(dport=destination_port, sport=random.randint(49152,65535))/ bytes([packet_index])
    output.append(pkt)

wrpcap('test_h1_input.pcap', output)
wrpcap('test_h2_expected.pcap', output)