#!/usr/bin/env python3
import queue
import sys

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.validator_tools import Validator

with ControllerExceptionHandling():
    '''
    s1 = HighLevelSwitchConnection(0, 'mac-learn', '60051', send_p4info=False, reset_dataplane=False, election_id_low=10)
    s2 = HighLevelSwitchConnection(1, 'state-learn', '60052', send_p4info=False, reset_dataplane=False, election_id_low=10)

    validator = Validator()
    s1_recv_queue = queue.Queue()
    s1.subscribe_to_stream_with_queue(s1_recv_queue)
    s2_recv_queue = queue.Queue()
    s2.subscribe_to_stream_with_queue(s2_recv_queue)
    '''

    s1 = HighLevelSwitchConnection(0, 'mac-learn', '60051')
    s2 = HighLevelSwitchConnection(1, 'state-learn', '60052')

    validator = Validator()
    s1_recv_queue = queue.Queue()
    s1.subscribe_to_stream_with_queue(s1_recv_queue)
    s2_recv_queue = queue.Queue()
    s2.subscribe_to_stream_with_queue(s2_recv_queue)

    #s1.connection.WriteDigest(s1.p4info_helper.get_digests_id('mac_learn_digest_t'))
    s2.connection.WriteDigest(s2.p4info_helper.get_digests_id('state_learn_digest_t'))
    # Important message for the testing system, do not remove :)
    print('Controller is ready')


    for i in range(5):
        #stream_message_response = s1_recv_queue.get(block=True, timeout= 5)
        #print('SIKERES RECEIVE')
        #print(stream_message_response)
        #validator.should_be_equal(s1.p4info_helper.get_digests_id('mac_learn_digest_t'), stream_message_response.digest.digest_id)
        stream_message_response2 = s2_recv_queue.get(block=True, timeout=10)
        validator.should_be_equal(s2.p4info_helper.get_digests_id('state_learn_digest_t'), stream_message_response2.digest.digest_id)

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)