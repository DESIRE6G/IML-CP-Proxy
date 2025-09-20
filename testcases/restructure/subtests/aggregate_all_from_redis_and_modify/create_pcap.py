#!/usr/bin/env python3
import random

from scapy.all import IP, TCP, Ether, wrpcap

source_mac = '08:00:00:00:01:11'
destination_mac = '08:00:00:00:02:22'
input = []
expected = []


def i24b(val: int) -> bytes:
    return val.to_bytes(4, 'big')

for packet_index in range(10):
    expected.append( Ether(src=source_mac, dst=destination_mac) / (i24b(66) + i24b(80) + i24b(89) + i24b(61)))

wrpcap('test_h2_expected.pcap', expected)