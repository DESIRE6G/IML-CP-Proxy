#!/usr/bin/env python3
import random

from scapy.all import IP, TCP, Ether, wrpcap
from scapy.layers.inet import UDP
from scapy.packet import Raw

source_mac = '08:00:00:00:01:11'
router_mac = '00:11:22:33:44:55'
destination_mac =  '08:00:00:00:02:22'

input = []
expected = []


for packet_index in range(10):
    inner_ip = IP(src='112.225.4.126', dst='10.1.0.1')
    inner_udp = UDP(sport=1234, dport=2152) # 2152 is the GTP tunneling port
    inner_packet = inner_ip / inner_udp / packet_index.to_bytes(2, 'big')

    outer_ip = IP(src='11.11.11.11', dst='10.1.0.1')

    outer_udp = UDP(sport=45149, dport=2152)

    gpt_header = Raw(b"\x30\xff\x00\x1e\x00\x00\x00\x64")

    outer_packet = outer_ip / outer_udp / gpt_header / inner_packet

    input.append(Ether(src=source_mac, dst=router_mac) / outer_packet)
    expected.append(Ether(src=source_mac, dst=destination_mac) / inner_packet)

wrpcap('test_h1_input.pcap', input)
wrpcap('test_h2_expected.pcap', expected)