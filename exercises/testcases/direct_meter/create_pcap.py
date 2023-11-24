#!/usr/bin/env python3
import random

from scapy.all import IP, TCP, Ether, wrpcap

source_mac = '08:00:00:00:01:11'
destination_mac = '08:00:00:00:02:22'
input = []
expected = []
for packet_index in range(10):
    input.append( Ether(src=source_mac, dst=destination_mac) / bytes([packet_index]))
    if packet_index < 1:
        expected.append( Ether(src=source_mac, dst=destination_mac) / bytes([packet_index]))

wrpcap('test_h1_input.pcap', input)
wrpcap('test_h2_expected.pcap', expected)