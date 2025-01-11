#!/usr/bin/env python3
import json
import sys

from common.logging_helper import configure_logger_with_common_settings
from common.traffic_helper import compare_packet_lists, PacketReceiver

configure_logger_with_common_settings('receive.log')
from scapy.all import (
    rdpcap,
)

if __name__ == '__main__':
    host_postfix = sys.argv[2] if len(sys.argv) > 2 else ''
    with PacketReceiver(host_postfix) as pr:
        packets_expected = rdpcap(sys.argv[1])
        output_object = compare_packet_lists(pr, packets_expected)

        with open(f'test_output{host_postfix}.json','w') as f:
            json.dump(output_object, f, indent = 4)


    '''
    packets_arrived = rdpcap('test_arrived.pcap')
    packets_expected = rdpcap('test_h2_expected.pcap')
    compare_packet_lists(packets_arrived, packets_expected)
    '''