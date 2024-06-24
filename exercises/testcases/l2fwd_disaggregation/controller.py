#!/usr/bin/env python3
import queue
import sys
from pathlib import Path

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.validator_tools import Validator

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'l2fwd', '60051')

    validator = Validator()

    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.dmac",
        match_fields={
            "hdr.ethernet.dstAddr": '08:00:00:00:02:22'
        },
        action_name="MyIngress.forward",
        action_params={
            "port": 2
        })
    s1.connection.WriteTableEntry(table_entry)

    s1_recv_queue = queue.Queue()
    s1.subscribe_to_stream_with_queue(s1_recv_queue)

    mac_digest_id = s1.p4info_helper.get_digests_id('mac_learn_digest_t')
    s1.connection.WriteDigest(mac_digest_id)
    Path('.controller_ready').touch()

    valid_ids = {mac_digest_id: False}

    # ping arrives from h1 so learning
    stream_message_response = s1_recv_queue.get(block=True, timeout=10)
    print(stream_message_response)
    mac, port = [member.bitstring for member in stream_message_response.message.digest.data[0].struct.members]
    mac_hex = mac.hex()
    mac_str = ":".join([x+y for x,y in zip(mac_hex[::2],mac_hex[1::2])])
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.smac",
        match_fields={
            "hdr.ethernet.srcAddr": mac_str
        },
        action_name="NoAction")
    s1.connection.WriteTableEntry(table_entry)
    table_entry = s1.p4info_helper.buildTableEntry(
        table_name="MyIngress.dmac",
        match_fields={
            "hdr.ethernet.dstAddr": mac_str
        },
        action_name="MyIngress.forward",
        action_params={
            "port": int.from_bytes(port, 'big')
        })
    s1.connection.WriteTableEntry(table_entry)
    was_exception = False
    try:
        stream_message_response = s1_recv_queue.get(block=True, timeout=2)
    except queue.Empty:
        was_exception = True
    validator.should_be_true(was_exception)

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)