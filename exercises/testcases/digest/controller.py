#!/usr/bin/env python3
import sys
import time

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection
import queue
import threading

from common.validator_tools import Validator

recv_queue = queue.Queue()

def recv_handler(responses):
    for response in responses:
        recv_queue.put(response)

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'mac-learn', '60051')


    recv_thread = threading.Thread(target=recv_handler, args=(s1.connection.stream_msg_resp,), daemon=True)
    recv_thread.start()
    s1.connection.WriteDigest(s1.p4info_helper.get_digests_id('mac_learn_digest_t'))

    # Important message for the testing system, do not remove :)
    print('Controller is ready')

    validator = Validator()

    for i in range(10):
        stream_message_response = recv_queue.get(block=True, timeout=10)
        validator.should_be_equal(s1.p4info_helper.get_digests_id('mac_learn_digest_t'), stream_message_response.digest.digest_id)

    if not validator.was_successful():
        raise Exception('Validation Failed')