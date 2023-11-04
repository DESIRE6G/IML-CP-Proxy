#!/usr/bin/env python3
import grpc

from common.controller_helper import create_experimental_model_forwards
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections


if __name__ == '__main__':
    try:
        s1 = HighLevelSwitchConnection(0, 'part1', '60051')
        s2 = HighLevelSwitchConnection(1, 'part2', '60052')
        s3 = HighLevelSwitchConnection(2, 'part3', '60053')
    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

