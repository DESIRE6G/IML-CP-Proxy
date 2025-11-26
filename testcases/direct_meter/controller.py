#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection

with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'direct_meter', '60051')

    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.m_read",
        match_fields={
            "hdr.ethernet.srcAddr": '08:00:00:00:01:11'
        },
        action_name="MyIngress.m_action")
    s1.connection.WriteTableEntry(table_entry)

    table_entry = s1.p4info_helper.build_table_entry(
        table_name="MyIngress.m_filter",
        match_fields={
            "meta.meter_tag": 0
        },
        action_name="NoAction")
    s1.connection.WriteTableEntry(table_entry)

    meter_entry = s1.p4info_helper.build_direct_meter_config_entry('MyIngress.m_read',
                                                                   {
            "hdr.ethernet.srcAddr": '08:00:00:00:01:11'
        }, cir=0, cburst=1, pir=5, pburst=50)
    s1.connection.WriteDirectMeterEntry(meter_entry)