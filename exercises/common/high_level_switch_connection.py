import time
from queue import Queue
from typing import Callable

from google.protobuf.json_format import Parse
from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2

import common.p4runtime_lib.bmv2
import common.p4runtime_lib.helper

from threading import Thread, Event

class StreamHandlerWorkerThread(Thread):
    def __init__(self, switch) -> None:
        Thread.__init__(self, daemon=True)
        self.stopped = Event()
        self.switch = switch

    def run(self) -> None:
        while not self.stopped.is_set():
            for x in self.switch.connection.stream_msg_resp:
                print('>>>>>>>>>>>>>')
                print(x)
                print(self.switch.stream_subscribed_queues)
                for q in self.switch.stream_subscribed_queues:
                    copy = p4runtime_pb2.StreamMessageResponse()
                    copy.CopyFrom(x)
                    q.put(copy)


    def stop(self) -> None:
        self.stopped.set()



class HighLevelSwitchConnection():
    def __init__(self, device_id: int, filename: str, port=None, send_p4info = True, reset_dataplane=True, election_id_low=1):
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
            proto_dump_file=f'logs/port{self.port}-p4runtime-requests.txt')

        self.connection.MasterArbitrationUpdate(election_id_low=election_id_low)
        self.stream_subscribed_queues = []
        self.stream_handler_worker_thread = None

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

    def stop(self) -> None:
        if self.stream_handler_worker_thread is not None:
            self.stream_handler_worker_thread.stop()

    def subscribe_to_stream_with_queue(self, queue: Queue) -> None:
        print("subscribe_to_stream_with_queue")
        self.stream_subscribed_queues.append(queue)
        if len(self.stream_subscribed_queues) == 1:
            self.stream_handler_worker_thread = StreamHandlerWorkerThread(self)
            self.stream_handler_worker_thread.start()