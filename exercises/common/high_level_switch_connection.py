import sys

from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2

import common.p4runtime_lib.bmv2
import common.p4runtime_lib.helper


class HighLevelSwitchConnection():
    def __init__(self, device_id: int, filename: str, port=None, send_p4info = True, reset_dataplane=True):
        self.device_id = device_id
        self.filename = filename
        self.p4info_path = f'./build/{self.filename}.p4.p4info.txt'
        self.bmv2_file_path = f'./build/{self.filename}.json'
        self.p4info_helper = common.p4runtime_lib.helper.P4InfoHelper(self.p4info_path)

        self.port = f'5005{device_id+1}' if port is None else port

        self.connection = common.p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name=f's{device_id+1}',
            address=f'127.0.0.1:{self.port}',
            device_id=device_id,
            proto_dump_file=f'logs/s{device_id+1}-p4runtime-requests.txt')

        self.connection.MasterArbitrationUpdate()

        if send_p4info:
            send_p4info_second_level = True
            try:
                if not reset_dataplane:
                    request = p4runtime_pb2.GetForwardingPipelineConfigRequest()
                    request.device_id = self.device_id
                    actual_p4info_raw = self.connection.client_stub.GetForwardingPipelineConfig(request)
                    actual_p4info = MessageToString(actual_p4info_raw.config.p4info)

                    if actual_p4info == MessageToString(self.p4info_helper.p4info):
                        send_p4info_second_level = False
            except:
                pass

            if send_p4info_second_level:
                self.connection.SetForwardingPipelineConfig(p4info=self.p4info_helper.p4info,
                                               bmv2_json_file_path=self.bmv2_file_path)
