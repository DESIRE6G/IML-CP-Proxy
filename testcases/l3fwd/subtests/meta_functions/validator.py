#!/usr/bin/env python3
import sys

from p4.v1 import p4runtime_pb2

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections
from common.validator_tools import Validator

if __name__ == '__main__':
    s1 = HighLevelSwitchConnection(2, 'basic_part1', '60053', send_p4info=False)
    s2 = HighLevelSwitchConnection(3, 'basic_part2', '60054', send_p4info=False)

    validator = Validator()

    request = p4runtime_pb2.CapabilitiesRequest()
    api1 = s1.connection.client_stub.Capabilities(request)
    api2 = s2.connection.client_stub.Capabilities(request)

    validator.should_be_equal(api1, api2)


    request = p4runtime_pb2.GetForwardingPipelineConfigRequest()

    pipeline_config1 = s1.connection.client_stub.GetForwardingPipelineConfig(request)
    validator.should_be_equal(pipeline_config1.config.p4info, s1.p4info_helper.p4info)

    pipeline_config2 = s2.connection.client_stub.GetForwardingPipelineConfig(request)
    validator.should_be_equal(pipeline_config2.config.p4info, s2.p4info_helper.p4info)

    ShutdownAllSwitchConnections()

    if validator.was_successful():
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
