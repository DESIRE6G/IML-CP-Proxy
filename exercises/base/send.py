#!/usr/bin/env python3
import random
import socket
import sys

from scapy.all import IP, TCP, Ether, get_if_hwaddr, get_if_list, sendp, rdpcap


def get_if():
    ifs=get_if_list()
    iface=None
    for i in get_if_list():
        if "eth0" in i:
            iface=i
            break
    if not iface:
        print("Cannot find eth0 interface")
        exit(1)
    return iface

if len(sys.argv)<2:
    print('pass 1 arguments: input_file')
    exit(1)

iface = get_if()

packets = rdpcap(sys.argv[1])
for pkt in packets:
    sendp(pkt, iface=iface, verbose=False)


