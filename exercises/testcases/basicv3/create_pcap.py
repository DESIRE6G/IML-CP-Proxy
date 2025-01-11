#!/usr/bin/env python3
import random

from scapy.all import IP, TCP, Ether, wrpcap
from scapy.layers.inet import UDP
from scapy.packet import Raw

source_mac = '08:00:00:00:01:11'
destination_mac = '08:00:00:00:02:22'
final_mac = '08:00:00:00:02:00'

input = []
expected = []


for packet_index in range(20):
    type_of_message = random.choice(['eth', 'eth_drop', 'ipv4','ipv4_drop'])
    if type_of_message == 'eth':
        input.append(Ether(src=source_mac, dst=destination_mac) / Raw(bytes([packet_index])))
        # TODO: test on h1 the bounce
    elif type_of_message == 'eth_drop':
        input.append(Ether(src=source_mac, dst='08:00:00:00:02:23') / Raw(bytes([packet_index])))
    elif type_of_message == 'ipv4':
        input.append(Ether(src=source_mac, dst=destination_mac) / IP(src='10.0.1.10', dst='10.0.2.20', ttl=64) / Raw(bytes([packet_index])))
        expected.append(Ether(src=destination_mac, dst=final_mac) / IP(src='10.0.1.10', dst='10.0.2.20', ttl=63) / Raw(bytes([packet_index])))
    elif type_of_message == 'ipv4_drop':
        input.append(Ether(src=source_mac, dst=destination_mac) / IP(src='10.0.1.10', dst='10.0.2.2', ttl=64) / Raw(bytes([packet_index])))


wrpcap('test_h1_input.pcap', input)
wrpcap('test_h2_expected.pcap', expected)