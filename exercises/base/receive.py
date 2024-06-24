#!/usr/bin/env python3
import logging
import sys

from common.logging_helper import configure_logger_with_common_settings
from common.traffic_helper import compare_packet_lists, PacketReceiver

configure_logger_with_common_settings('receive.log')
from scapy.all import (
    rdpcap,
)

if __name__ == '__main__':
    with PacketReceiver() as pr:
        packets_expected = rdpcap(sys.argv[1])
        compare_packet_lists(pr, packets_expected)

    '''
    packets_arrived = rdpcap('test_arrived.pcap')
    packets_expected = rdpcap('test_h2_expected.pcap')
    compare_packet_lists(packets_arrived, packets_expected)
    '''