#!/usr/bin/env python3
import os
import sys
import time

import grpc

from common.high_level_switch_connection import HighLevelSwitchConnection

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../../utils/'))
from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections


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
    counters_id = p4info_helper.get_counters_id(counter_name)
    for response in sw.ReadCounters(counters_id, index):
        print(response.entities)
        for entity in response.entities:
            counter = entity.counter_entry
            print("%s %s %d: %d packets (%d bytes)" % (
                sw.name, counter_name, index,
                counter.data.packet_count, counter.data.byte_count
            ))

def main(aggregated = False):
    try:
        s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051')
        s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052')
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
        s1.connection.WriteTableEntry(table_entry)
        s2.connection.WriteTableEntry(table_entry)

        while True:
            time.sleep(2)
            print('\n----- Reading tunnel counters -----')
            printCounter(s1.p4info_helper, s1.connection, "MyIngress.packetCounter", 1)
            printCounter(s1.p4info_helper, s1.connection, "MyIngress.packetCounter2", 1)
            printCounter(s2.p4info_helper, s2.connection, "MyIngress.packetCounter", 1)
            printCounter(s2.p4info_helper, s2.connection, "MyIngress.packetCounter2", 1)

    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    main(aggregated=True)
