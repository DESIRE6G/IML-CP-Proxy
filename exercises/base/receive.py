#!/usr/bin/env python3
import json
import os
import sys
import logging
import time
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/receive.log"),
        logging.StreamHandler()
    ]
)


from scapy.all import (
    IP,
    Ether,
    IPOption,
    ShortField,
    get_if_list,
    sniff,
    rdpcap,
    wrpcap,
    AsyncSniffer
)

def get_if():
    ifs=get_if_list()
    iface=None
    for i in get_if_list():
        if "eth0" in i:
            iface=i
            break;
    if not iface:
        logging.error("Cannot find eth0 interface")
        exit(1)
    return iface

packets_arrived = []
def handle_pkt(pkt):
    packets_arrived.append(pkt)
    packet_readable = pkt.show2(dump=True)
    logging.debug(f'Arrived {repr(pkt)}')
    with open("output.txt", "a") as f:
        f.write(packet_readable)

    sys.stdout.flush()


def convert_packet_to_dump_object(pkt):
    return {'raw':str(pkt), 'dump':pkt.__repr__()}


def are_packets_equal(packet1, packet2) -> bool:
    if IP in packet1 and IP in packet2:
        packet1[IP].ttl = 64
        packet2[IP].ttl = 64
        packet1[IP].chksum = 0
        packet2[IP].chksum = 0

    return packet1.payload == packet2.payload


def is_packet_in(packet_to_find, packet_list) -> bool:
    return any([are_packets_equal(packet, packet_to_find) for packet in packet_list])


def compare_packet_lists(packets_arrived, packets_expected):
    output_object = {'success':None,'extra_packets':[], 'missing_packets':[]}
    for pkt_arrived in packets_arrived:
        if not is_packet_in(pkt_arrived, packets_expected):
            output_object['extra_packets'].append(convert_packet_to_dump_object(pkt_arrived))
            logging.debug(f'Extra packet arrived {pkt_arrived}')

    for pkt_expected in packets_expected:
        if not is_packet_in(pkt_expected, packets_arrived):
            output_object['missing_packets'].append(convert_packet_to_dump_object(pkt_expected))
            logging.debug(f'Missing packet {pkt_expected}')

    output_object['success'] = len(output_object['extra_packets']) == 0 and len(output_object['missing_packets']) == 0

    with open('test_output.json','w') as f:
        json.dump(output_object, f, indent = 4)


if __name__ == '__main__':
    ifaces = [i for i in os.listdir('/sys/class/net/') if 'eth' in i]
    iface = ifaces[0]
    logging.debug(f"sniffing on {iface}")
    sys.stdout.flush()

    t = AsyncSniffer(iface = iface, prn = lambda x: handle_pkt(x), timeout=10)
    t.start()
    while not hasattr(t, 'stop_cb'):
        time.sleep(0.1)
    while t.running and not os.path.exists('.pcap_send_finished'):
        logging.debug('Waiting for .pcap_send_finished')
        time.sleep(0.25)

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