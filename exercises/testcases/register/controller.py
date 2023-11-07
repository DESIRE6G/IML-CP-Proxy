#!/usr/bin/env python3
import grpc
from p4.v1 import p4runtime_pb2

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections




if __name__ == '__main__':
    try:
        s1 = HighLevelSwitchConnection(0, 'register', '60051')
        '''
        register_entry = buildRegisterEntry(
            index=0
        )
        s1.connection.WriteRegister(register_entry)
        '''

    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

