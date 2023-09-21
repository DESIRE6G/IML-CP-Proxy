#!/usr/bin/env python3
import json
import os
import sys
import pprint

from scapy.all import (
    TCP,
    FieldLenField,
    FieldListField,
    IntField,
    IPOption,
    ShortField,
    get_if_list,
    sniff,
    rdpcap
)
from scapy.layers.inet import _IPOption_HDR


def get_if():
    ifs=get_if_list()
    iface=None
    for i in get_if_list():
        if "eth0" in i:
            iface=i
            break;
    if not iface:
        print("Cannot find eth0 interface")
        exit(1)
    return iface

class IPOption_MRI(IPOption):
    name = "MRI"
    option = 31
    fields_desc = [ _IPOption_HDR,
                    FieldLenField("length", None, fmt="B",
                                  length_of="swids",
                                  adjust=lambda pkt,l:l+4),
                    ShortField("count", 0),
                    FieldListField("swids",
                                   [],
                                   IntField("", 0),
                                   length_from=lambda pkt:pkt.count*4) ]
def handle_pkt(pkt):
    if TCP in pkt and pkt[TCP].dport == 1234:
        print("got a packet")
        packet_readable = pkt.show2(dump=True)
        with open("output.txt", "a") as f:
            f.write(packet_readable)

        sys.stdout.flush()


def main():
    ifaces = [i for i in os.listdir('/sys/class/net/') if 'eth' in i]
    iface = ifaces[0]
    print("sniffing on %s" % iface)
    sys.stdout.flush()
    sniff(iface = iface,
          prn = lambda x: handle_pkt(x))

def convert_packet_to_dump_object(pkt):
    return {'raw':str(pkt), 'dump':pkt.__repr__()}

if __name__ == '__main__':
    #main()
    output_object = {'success':None,'extra_packets':[], 'missing_packets':[]}
    packets_arrived = rdpcap(sys.argv[1])
    packets_expected = rdpcap(sys.argv[2])
    for pkt_arrived in packets_arrived:
        if pkt_arrived not in packets_expected:
            output_object['extra_packets'].append(convert_packet_to_dump_object(pkt_arrived))
            print(f'Extra packet arrived {pkt_arrived}')

    for pkt_expected in packets_expected:
        if pkt_expected not in packets_arrived:
            output_object['missing_packets'].append(convert_packet_to_dump_object(pkt_expected))
            print(f'Missing packet {pkt_expected}')

    output_object['success'] = len(output_object['extra_packets']) == 0 and len(output_object['missing_packets']) == 0

    with open('test_output.json','w') as f:
        json.dump(output_object, f, indent = 4)