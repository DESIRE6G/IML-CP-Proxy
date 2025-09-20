#!/usr/bin/env python3
import queue
import sys
from pathlib import Path

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.validator_tools import Validator

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'mac-and-state-learn-aggregated', '60051')

    validator = Validator()
    s1_recv_queue = queue.Queue()
    s1.subscribe_to_stream_with_queue(s1_recv_queue)

    mac_digest_id = s1.p4info_helper.get_digests_id('NF1_mac_learn_digest_t')
    state_digest_id = s1.p4info_helper.get_digests_id('NF2_state_learn_digest_t')

    s1.connection.WriteDigest(mac_digest_id)
    s1.connection.WriteDigest(state_digest_id)
    Path('.controller_ready').touch()

    valid_ids = {mac_digest_id: False, state_digest_id: False}

    for i in range(5):
        stream_message_response = s1_recv_queue.get(block=True, timeout=10)
        digest_id = stream_message_response.message.digest.digest_id
        validator.should_be_true(digest_id in valid_ids)
        valid_ids[digest_id] = True

    validator.should_be_true(all(valid_ids.values()))

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)