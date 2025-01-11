#!/usr/bin/env python3
import random

from scapy.all import IP, TCP, Ether, wrpcap
from scapy.layers.inet import UDP
from scapy.packet import Raw

source_mac = '08:00:00:00:01:11'
destination_mac = '08:00:00:00:02:22'
final_mac = '08:00:00:00:02:00'

input = []
h1_expected = []
h2_expected = []

message_types = ['eth', 'eth_drop', 'ipv4','ipv4_drop']

for packet_index in range(20):
    if packet_index < 4:
        type_of_message = message_types[packet_index]
    else:
        type_of_message = random.choice(message_types)
    print(packet_index, type_of_message)
    if type_of_message == 'eth':
        input.append(Ether(src=source_mac, dst=destination_mac) / Raw(bytes([packet_index])))
        h1_expected.append(Ether(src=source_mac, dst=destination_mac) / Raw(bytes([packet_index])))
    elif type_of_message == 'eth_drop':
        input.append(Ether(src=source_mac, dst='08:00:00:00:02:23') / Raw(bytes([packet_index])))
    elif type_of_message == 'ipv4':
        input.append(Ether(src=source_mac, dst=destination_mac) / IP(src='10.0.1.10', dst='10.0.2.20', ttl=64) / Raw(bytes([packet_index])))
        h2_expected.append(Ether(src=destination_mac, dst=final_mac) / IP(src='10.0.1.10', dst='10.0.2.20', ttl=63) / Raw(bytes([packet_index])))
    elif type_of_message == 'ipv4_drop':
        input.append(Ether(src=source_mac, dst=destination_mac) / IP(src='10.0.1.10', dst='10.0.2.2', ttl=64) / Raw(bytes([packet_index])))


wrpcap('test_h1_input.pcap', input)
#wrpcap('test_h1_expected.pcap', h1_expected)
wrpcap('test_h2_expected.pcap', h2_expected)