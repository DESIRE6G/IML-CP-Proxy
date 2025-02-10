import json
import logging
import os
import sys
import time
from pathlib import Path

from scapy.arch import get_if_list
from scapy.all import (
    IP,
    Ether,
    IPOption,
    rdpcap,
    wrpcap,
    AsyncSniffer
)

from common.validator_tools import diff_strings

def get_eth0_interface():
    for interface in get_if_list():
        if "eth0" in interface:
            return interface
    else:
        print("Cannot find eth0 interface")
        exit(1)


def convert_packet_to_dump_object(pkt):
    return {'raw':str(pkt), 'dump':pkt.__repr__()}


def are_packets_equal(packet1, packet2) -> bool:
    if packet1[Ether].type == 0xffff or packet2[Ether].type == 0xffff:
        return True

    if IP in packet1 and IP in packet2:
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
    return output_object


class PacketReceiver:
    def __init__(self, host_postfix='', attach_timestamps=False):
        self.host_postfix = host_postfix
        self.attach_timestamps = attach_timestamps

    def __enter__(self):
        iface = get_eth0_interface()
        logging.debug(f"sniffing on {iface}")
        sys.stdout.flush()
        packets_arrived = []
        packets_arrived_ts = []
        def handle_pkt(pkt):
            packets_arrived.append(pkt)
            packets_arrived_ts.append(time.time_ns())
            packet_readable = pkt.show2(dump=True)
            logging.debug(f'Arrived {repr(pkt)}')
            with open(f"output{self.host_postfix}.txt", "a") as f:
                f.write(packet_readable)

            sys.stdout.flush()

        t = AsyncSniffer(iface = iface, filter="inbound", prn = lambda x: handle_pkt(x))
        t.start()
        while not hasattr(t, 'stop_cb'):
            time.sleep(0.1)

        logging.debug(f'Touch .pcap_receive_started{self.host_postfix}')
        Path(f'.pcap_receive_started{self.host_postfix}').touch()
        logging.debug('Waiting for .pcap_send_finished_h1')
        while t.running and not os.path.exists('.pcap_send_finished_h1'):
            time.sleep(0.25)

        logging.debug('Waiting to arrive one package')

        last_time = time.time()
        last_packet_arrived_count = 0
        while time.time() - last_time < 2:
            if last_packet_arrived_count != len(packets_arrived):
                last_packet_arrived_count = len(packets_arrived)
                last_time = time.time()

            time.sleep(0.1)

        time.sleep(1)

        logging.debug('Done, removing .pcap_send_finished_h1')
        try:
            os.remove('.pcap_send_finished_h1')
        except OSError: # If multiple receiver runs may the other deleted the flag file
            pass
        if t.running:
            t.stop()

        logging.debug('--------------------------------')
        logging.debug('SNIFFING FINISHED')
        wrpcap(f'test_arrived{self.host_postfix}.pcap', packets_arrived)
        if self.attach_timestamps:
            return zip(packets_arrived, packets_arrived_ts)
        else:
            return packets_arrived

    def __exit__(self, exc_type, exc_value, exc_tb):
        logging.debug('touch .pcap_receive_finished')
        if exc_type is not None:
            logging.exception('Exception occurred')
        Path('.pcap_receive_finished').touch()