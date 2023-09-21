#!/usr/bin/env python3
import random

from scapy.all import IP, TCP, Ether, wrpcap

source_mac = '08:00:00:00:01:11'
destination_ip = '10.0.2.2'
destination_port = 1234
payload_list = ['hello','lorem ipsum','yay','p4runtime','python']

output = []
for packet_index in range(10):
    message = f'packet{packet_index}: {random.choice(payload_list)}'
    pkt =  Ether(src=source_mac, dst='ff:ff:ff:ff:ff:ff')
    pkt = pkt /IP(dst=destination_ip) / TCP(dport=destination_port, sport=random.randint(49152,65535)) / message
    output.append(pkt)

wrpcap('test_h1_input.pcap', output)
wrpcap('test_h2_expected.pcap', output[0:5])