#!/usr/bin/env python3
import argparse
import os
import sys
from time import sleep

import grpc

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../../utils/'))
import p4runtime_lib.bmv2
import p4runtime_lib.helper
from p4runtime_lib.error_utils import printGrpcError
from p4runtime_lib.switch import ShutdownAllSwitchConnections

SWITCH_TO_HOST_PORT = 1
SWITCH_TO_SWITCH_PORT = 2


def readTableRules(p4info_helper, sw):
    """
    Reads the table entries from all tables on the switch.

    :param p4info_helper: the P4Info helper
    :param sw: the switch connection
    """
    print('\n----- Reading tables rules for %s -----' % sw.name)
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            print(p4info_helper.get_tables_name(entry.table_id))
            print(entry)

            print('-----')


def printCounter(p4info_helper, sw, counter_name, index):
    """
    Reads the specified counter at the specified index from the switch. In our
    program, the index is the tunnel ID. If the index is 0, it will return all
    values from the counter.

    :param p4info_helper: the P4Info helper
    :param sw:  the switch connection
    :param counter_name: the name of the counter from the P4 program
    :param index: the counter index (in our case, the tunnel ID)
    """
    for response in sw.ReadCounters(p4info_helper.get_counters_id(counter_name), index):
        for entity in response.entities:
            counter = entity.counter_entry
            print("%s %s %d: %d packets (%d bytes)" % (
                sw.name, counter_name, index,
                counter.data.packet_count, counter.data.byte_count
            ))

class SwitchConnection():
    def __init__(self, device_id, filename, port=None):
        self.device_id = device_id
        self.filename = filename
        self.p4info_path = f'./build/{self.filename}.p4.p4info.txt'
        self.bmv2_file_path = f'./build/{self.filename}.json'
        self.p4info_helper = p4runtime_lib.helper.P4InfoHelper(self.p4info_path)

        self.port = f'5005{device_id+1}' if port is None else port

        self.connection = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name=f's{device_id+1}',
            address=f'127.0.0.1:{self.port}',
            device_id=device_id,
            proto_dump_file=f'logs/s{device_id+1}-p4runtime-requests.txt')

        self.connection.MasterArbitrationUpdate()

        self.connection.SetForwardingPipelineConfig(p4info=self.p4info_helper.p4info,
                                       bmv2_json_file_path=self.bmv2_file_path)

def main():
    try:
        s1 = SwitchConnection(0,'fwd')
        s2 = SwitchConnection(1,'fwd')
        s3 = SwitchConnection(2,'basic_part1')
        s4 = SwitchConnection(3,'basic_part2')

        print('writeTunnelRules')
        # PING response can come on this line (s1 and s2 has same p4info)
        table_entry = s1.p4info_helper.buildTableEntry(
            table_name="MyIngress.ipv4_lpm",
            match_fields={
                "hdr.ipv4.dstAddr": ('10.0.1.1', 32)
            },
            action_name="MyIngress.ipv4_forward",
            action_params={
                "dstAddr": '08:00:00:00:01:11',
                "port": 1
            })
        s1.connection.WriteTableEntry(table_entry)
        s2.connection.WriteTableEntry(table_entry)

        # s2 forwards packet to h2 if arrives
        table_entry = s2.p4info_helper.buildTableEntry(
            table_name="MyIngress.ipv4_lpm",
            match_fields={
                "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
            },
            action_name="MyIngress.ipv4_forward",
            action_params={
                "dstAddr": '08:00:00:00:02:22',
                "port": 2
            })
        s2.connection.WriteTableEntry(table_entry)


        # s1 forwards packet to the experimental track
        table_entry = s1.p4info_helper.buildTableEntry(
            table_name="MyIngress.ipv4_lpm",
            match_fields={
                "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
            },
            action_name="MyIngress.ipv4_forward",
            action_params={
                "dstAddr": '08:00:00:00:02:22',
                "port": 3
            })
        s1.connection.WriteTableEntry(table_entry)

        table_entry = s3.p4info_helper.buildTableEntry(
            table_name="MyIngress.ipv4_lpm1",
            match_fields={
                "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
            },
            action_name="MyIngress.chg_addr",
            action_params={
                "dstAddr": '08:00:00:00:02:22',
                "port": 2
            })
        s3.connection.WriteTableEntry(table_entry)


        table_entry = s4.p4info_helper.buildTableEntry(
            table_name="MyIngress.ipv4_lpm2",
            match_fields={
                "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
            },
            action_name="MyIngress.set_port",
            )
        s4.connection.WriteTableEntry(table_entry)




        readTableRules(s1.p4info_helper, s1.connection)
        readTableRules(s1.p4info_helper, s1.connection)

    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    main()
