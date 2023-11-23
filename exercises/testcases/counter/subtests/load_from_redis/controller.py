#!/usr/bin/env python3

import grpc

from common.controller_helper import init_l2fwd_table_rules_for_both_directions
from common.high_level_switch_connection import HighLevelSwitchConnection

from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

if __name__ == '__main__':
    try:
        s1 = HighLevelSwitchConnection(0, 'fwd_with_counting', '60051')
        s2 = HighLevelSwitchConnection(1, 'fwd_with_counting2', '60052')
        # PING response can come on this line (s1 and s2 has same p4info)
        init_l2fwd_table_rules_for_both_directions(s1, s2)

        counter_entry = s1.p4info_helper.buildCounterEntry('packetCounter', 1, 1234, 6443)
        s1.connection.WriteCountersEntry(counter_entry)
    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()
