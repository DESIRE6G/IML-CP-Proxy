#!/usr/bin/env python3
import json
import os
import sys
import logging
import time
from pathlib import Path

from common.logging_helper import configure_logger_with_common_settings
from common.traffic_helper import get_eth0_interface
from common.validator_tools import diff_strings

configure_logger_with_common_settings('receive.log')

from scapy.all import (
    IP,
    Ether,
    IPOption,
    rdpcap,
    wrpcap,
    AsyncSniffer
)

iface = get_eth0_interface()

def convert_packet_to_dump_object(pkt):
    return {'raw':str(pkt), 'dump':pkt.__repr__()}


def are_packets_equal(packet1, packet2) -> bool:
    if packet1[Ether].type == 0xffff or packet2[Ether].type == 0xffff:
        return True

    if IP in packet1 and IP in packet2:
        packet1[IP].ttl = 64
        packet2[IP].ttl = 64
        packet1[IP].chksum = 0
        packet2[IP].chksum = 0

    return packet1.payload == packet2.payload


def is_packet_in(packet_to_find, packet_list) -> bool:
    return any([are_packets_equal(packet, packet_to_find) for packet in packet_list])

def compare_packet_lists(packets_arrived, packets_expected):
    output_object = {'success':None,'extra_packets':[], 'missing_packets':[], 'ordered_compare': []}
    for pkt_arrived in packets_arrived:
        if not is_packet_in(pkt_arrived, packets_expected):
            output_object['extra_packets'].append(convert_packet_to_dump_object(pkt_arrived))
            logging.debug(f'Extra packet arrived {pkt_arrived}')

    for pkt_expected in packets_expected:
        if not is_packet_in(pkt_expected, packets_arrived):
            output_object['missing_packets'].append(convert_packet_to_dump_object(pkt_expected))
            logging.debug(f'Missing packet {pkt_expected}')


    for packet_index in range(len(packets_arrived)):
        actual_packet_arrived = packets_arrived[packet_index]
        actual_packet_arrived_str = str(actual_packet_arrived)
        wildcard_expected = False
        if packet_index < len(packets_expected):
            actual_packet_expected = packets_expected[packet_index]
            wildcard_expected = actual_packet_expected[Ether].type == 0xffff
            actual_packet_expected_str = str(packets_expected[packet_index])
        else:
            actual_packet_expected = None
            actual_packet_expected_str = ''

        if not wildcard_expected:
            actual_packet_arrived_colored, diff_flags = diff_strings(actual_packet_arrived_str, actual_packet_expected_str)
            dump_actual_packet_arrived_colored, dump_diff_flags = diff_strings(repr(actual_packet_arrived), repr(actual_packet_expected))
        else:
            actual_packet_arrived_colored, diff_flags = actual_packet_arrived_str, ''
            dump_actual_packet_arrived_colored, dump_diff_flags = repr(actual_packet_arrived), ''
            actual_packet_expected_str = actual_packet_arrived_str

        logging.debug(f'--- [Packet {packet_index}] ---')
        logging.debug(f'Expected: {actual_packet_expected_str}')
        logging.debug(f'Arrived:  {actual_packet_arrived_str}')
        logging.debug(f'          {diff_flags}')

        output_object['ordered_compare'].append({
            'expected':actual_packet_expected_str,
            'arrived':actual_packet_arrived_str,
            'arrived_colored':actual_packet_arrived_colored,
            'diff_string': diff_flags,
            'dump_expected': repr(actual_packet_expected),
            'dump_arrived': repr(actual_packet_arrived),
            'dump_arrived_colored': dump_actual_packet_arrived_colored,
            'dump_diff_string': dump_diff_flags,
            'ok': actual_packet_expected_str == actual_packet_arrived_str
        })

    output_object['success'] = len(output_object['extra_packets']) == 0 and len(output_object['missing_packets']) == 0

    with open('test_output.json','w') as f:
        json.dump(output_object, f, indent = 4)


if __name__ == '__main__':
    ifaces = [i for i in os.listdir('/sys/class/net/') if 'eth' in i]
    iface = ifaces[0]
    logging.debug(f"sniffing on {iface}")
    sys.stdout.flush()
    packets_arrived = []
    def handle_pkt(pkt):
        packets_arrived.append(pkt)
        packet_readable = pkt.show2(dump=True)
        logging.debug(f'Arrived {repr(pkt)}')
        with open("output.txt", "a") as f:
            f.write(packet_readable)

        sys.stdout.flush()

    t = AsyncSniffer(iface = iface, prn = lambda x: handle_pkt(x))
    t.start()
    while not hasattr(t, 'stop_cb'):
        time.sleep(0.1)

    logging.debug('Touch .pcap_receive_started')
    Path('.pcap_receive_started').touch()
    logging.debug('Waiting for .pcap_send_finished')
    while t.running and not os.path.exists('.pcap_send_finished'):
        time.sleep(0.25)

    logging.debug('Waiting to arrive one package')
    wait_counter = 0
    while len(packets_arrived) == 0 and wait_counter < 50:
        wait_counter += 1
        time.sleep(0.1)

    time.sleep(1)

    logging.debug('Done, removing .pcap_send_finished')
    os.remove('.pcap_send_finished')
    if t.running:
        t.stop()

    logging.debug('--------------------------------')
    logging.debug('SNIFFING FINISHED')
    packets_expected = rdpcap(sys.argv[1])
    wrpcap('test_arrived.pcap', packets_arrived)

    compare_packet_lists(packets_arrived, packets_expected)

    logging.debug('touch .pcap_receive_finished')
    Path('.pcap_receive_finished').touch()
    '''
    packets_arrived = rdpcap('test_arrived.pcap')
    packets_expected = rdpcap('test_h2_expected.pcap')
    compare_packet_lists(packets_arrived, packets_expected)
    '''