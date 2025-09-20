#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection


with ControllerExceptionHandling():
    s3 = HighLevelSwitchConnection(2, 'part3', '60053')
    table_entry = s3.p4info_helper.buildTableEntry(
        table_name="MyIngress.state_setter",
        match_fields={
            'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
        },
        action_name="MyIngress.state_set",
        action_params={
            "newState": 89
        })
    s3.connection.WriteTableEntry(table_entry, update_type= 'MODIFY')

