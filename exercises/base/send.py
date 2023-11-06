#!/usr/bin/env python3
import random
import socket
import sys
from pathlib import Path
import logging

from scapy.all import IP, TCP, Ether, get_if_hwaddr, get_if_list, sendp, rdpcap

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/send.log"),
        logging.StreamHandler()
    ]
)


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
    logging.debug(f'Sent {repr(pkt)}')


Path('.pcap_send_finished').touch()
logging.debug('touch pcap_send_finished')
