#!/usr/bin/env python3
import os
import sys

import grpc

from high_level_switch_connection import HighLevelSwitchConnection

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../../utils/'))
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


def config_response_simple_forward():
    s1 = HighLevelSwitchConnection(0, 'fwd')
    s2 = HighLevelSwitchConnection(1, 'fwd')
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

def config_not_aggregated_controller(aggregated_dataplane = False):

    s3 = HighLevelSwitchConnection(2, 'basic_part1', '60053' if aggregated_dataplane else None)
    s4 = HighLevelSwitchConnection(3, 'basic_part2', '60054' if aggregated_dataplane else None)

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


def config_aggregated_controller():
    s3 = HighLevelSwitchConnection(2, 'basic')

    table_entry = s3.p4info_helper.buildTableEntry(
        table_name="MyIngress.NF1_ipv4_lpm1",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.NF1_chg_addr",
        action_params={
            "dstAddr": '08:00:00:00:02:22',
            "port": 2
        })
    s3.connection.WriteTableEntry(table_entry)


    table_entry = s3.p4info_helper.buildTableEntry(
        table_name="MyIngress.NF2_ipv4_lpm2",
        match_fields={
            "hdr.ipv4.dstAddr": ('10.0.2.2', 32)
        },
        action_name="MyIngress.NF2_set_port",
        )
    s3.connection.WriteTableEntry(table_entry)



def main(aggregated = False):
    try:
        s3 = HighLevelSwitchConnection(2, 'basic_part1', '60053',send_p4info=False)
        config_response_simple_forward()
        config_not_aggregated_controller(aggregated_dataplane=True)
        readTableRules(s3.p4info_helper, s3.connection)
        #config_aggregated_controller()
    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    main(aggregated=True)
