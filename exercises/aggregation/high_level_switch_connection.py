import p4runtime_lib.bmv2
import p4runtime_lib.helper


class HighLevelSwitchConnection():
    def __init__(self, device_id, filename, port=None, send_p4info = True):
        self.device_id = device_id
        self.filename = filename
        self.p4info_path = f'./build/{self.filename}.p4.p4info.txt'
        self.bmv2_file_path = f'./build/{self.filename}.json'
        self.p4info_helper = p4runtime_lib.helper.P4InfoHelper(self.p4info_path)

        self.port = f'5005{device_id+1}' if port is None else port

        self.connection = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name=f's{device_id+1}',
            address=f'127.0.0.1:{self.port}',
            device_id=device_id,
            proto_dump_file=f'logs/s{device_id+1}-p4runtime-requests.txt')

        self.connection.MasterArbitrationUpdate()

        if send_p4info:
            self.connection.SetForwardingPipelineConfig(p4info=self.p4info_helper.p4info,
                                           bmv2_json_file_path=self.bmv2_file_path)
