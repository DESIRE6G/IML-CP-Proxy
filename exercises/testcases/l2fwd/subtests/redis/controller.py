#!/usr/bin/env python3
import os
import sys

import grpc

from common.controller_helper import create_experimental_model_forwards

from common.p4runtime_lib.error_utils import printGrpcError
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

if __name__ == '__main__':
    try:
        create_experimental_model_forwards()
    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()