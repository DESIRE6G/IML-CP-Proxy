#!/usr/bin/env python3
import random

from scapy.all import IP, TCP, Ether, wrpcap, ARP, ICMP
from scapy.layers.inet import UDP
from scapy.packet import Raw

source_mac = '08:00:00:00:01:11'
source_ip = '10.0.1.10'
target_mac = '08:00:00:00:02:22'
target_ip = '10.0.2.20'

broadcast_mac = 'ff:ff:ff:ff:ff:ff'

input = []
expected = []

for packet_index in range(20):
    type_of_message = random.choice(['arp', 'arp-no-response', 'icmp', 'icmp-no-response'])
    if type_of_message == 'arp':
        input.append(Ether(src=source_mac, dst=broadcast_mac) / ARP(op=1, hwsrc=source_mac, psrc=str(source_ip), pdst=str(target_ip)))
        expected.append(Ether(src=target_mac, dst=source_mac) /
                        ARP(op=2, hwsrc=target_mac, psrc=str(target_ip), hwdst=source_mac, pdst=str(source_ip)))
    elif type_of_message == 'arp-no-response':
        input.append(Ether(src=source_mac, dst=broadcast_mac) / ARP(op=1, hwsrc=source_mac, psrc=str(source_ip), pdst=str('10.0.2.55')))
    elif type_of_message == 'icmp':
        ping_payload =  b"Hello ICMP"
        icmp_request = IP(src=source_ip, dst=target_ip) / ICMP(type=8, code=0) / ping_payload
        input.append(Ether(src=source_mac, dst=broadcast_mac) / icmp_request)

        expected_icmp_reply = IP(src=target_ip, dst=source_ip) / ICMP(type=0, code=0) / ping_payload
        expected.append(Ether(src=target_mac, dst=broadcast_mac) / expected_icmp_reply)
    elif type_of_message == 'icmp-no-response':
        ping_payload =  b"Hello ICMP"
        icmp_request = IP(src=source_ip, dst='10.0.2.1') / ICMP(type=8, code=0) / ping_payload
        input.append(Ether(src=source_mac, dst='11:22:33:44:55:66') / icmp_request)



wrpcap('test_h1_input.pcap', input)
wrpcap('test_h1_expected.pcap', expected)