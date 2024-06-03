#!/usr/bin/env python3
import sys
from pathlib import Path
import logging

from scapy.all import sendp, rdpcap

from common.logging_helper import configure_logger_with_common_settings
from common.traffic_helper import get_eth0_interface

configure_logger_with_common_settings('send.log')

if len(sys.argv)<2:
    print('pass 1 arguments: input_file')
    exit(1)

iface = get_eth0_interface()

packets = rdpcap(sys.argv[1])
for pkt in packets:
    sendp(pkt, iface=iface, verbose=False)
    logging.debug(f'Sent {repr(pkt)}')


Path('.pcap_send_finished').touch()
logging.debug('touch pcap_send_finished')
