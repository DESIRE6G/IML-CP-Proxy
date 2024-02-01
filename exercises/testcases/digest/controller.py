#!/usr/bin/env python3
import time

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection
import queue
import threading

recv_queue = queue.Queue()

def recv_handler(responses):
    for response in responses:
        print('Receive response')
        print(response)
        recv_queue.put(response)

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'mac-learn', '60051')


    recv_thread = threading.Thread(target=recv_handler, args=(s1.connection.stream_msg_resp,))
    recv_thread.start()
    s1.connection.WriteDigest(402184575)

    # Important message for the testing system, do not remove :)
    print('Controller is ready')
    time.sleep(10)
    recv_thread.join()
