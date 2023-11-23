#!/usr/bin/env python3
import os
import sys
import time

import grpc

from common.high_level_switch_connection import HighLevelSwitchConnection

from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

if __name__ == '__main__':
    try:
        s1 = HighLevelSwitchConnection(0, 'meter1', '60051')
        meter_entry = s1.p4info_helper.buildMeterConfigEntry('my_meter',cir=1,cburst=1,pir=2,pburst=2000000)
        s1.connection.WriteMeterEntry(meter_entry)
    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()
