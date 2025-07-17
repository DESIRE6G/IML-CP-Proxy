import socket
from dataclasses import dataclass
from queue import Queue
from typing import Any, Optional, List, Union

from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2
from pydantic import BaseModel

import common.p4runtime_lib.bmv2
import common.p4runtime_lib.helper

from threading import Thread, Event, Lock


@dataclass
class QueueWithInfo:
    queue: Queue
    extra_information: Optional[Any] = None

@dataclass
class StreamMessageResponseWithInfo:
    message: p4runtime_pb2.StreamMessageResponse
    extra_information: Optional[Any] = None

class StreamHandlerWorkerThread(Thread):
    def __init__(self, switch: 'HighLevelSwitchConnection') -> None:
        Thread.__init__(self, daemon=True)
        self.stopped = Event()
        self.switch = switch

    def run(self) -> None:
        while not self.stopped.is_set():
            for x in self.switch.connection.stream_msg_resp:
                with self.switch.stream_subscribed_queues_lock:
                    # print('>>>>>>>>>>>>>')
                    # print(x)
                    # print(self.switch.stream_subscribed_queues)
                    for q in self.switch.stream_subscribed_queues:
                        copy = p4runtime_pb2.StreamMessageResponse()
                        copy.CopyFrom(x)
                        q.queue.put(StreamMessageResponseWithInfo(copy, q.extra_information))


    def stop(self) -> None:
        self.stopped.set()


class EnviromentSettins(BaseModel):
    production_mode: bool = False
    p4_config_support: bool = True

if socket.gethostname() == 'dpdk-switch':
    enviroment_settings = EnviromentSettins(
        production_mode = True,
        p4_config_support = False
    )
else:
    enviroment_settings = EnviromentSettins()

class HighLevelSwitchConnection:
    def __init__(self,
                 device_id: int,
                 filename: str,
                 port: Optional[Union[int, str]] = None,
                 send_p4info: bool = True,
                 reset_dataplane: bool = True,
                 election_id_low: int = 1,
                 p4info_path: Optional[str] = None,
                 bmv2_file_path: Optional[str] = None,
                 rate_limit: Optional[int] = None,
                 rate_limiter_buffer_size: Optional[int] = None,
                 production_mode: Optional[bool] = None,
                 p4_config_support: Optional[bool] = None,
                 batch_delay: Optional[float] = None,
                 host='127.0.0.1'):
        self.device_id = device_id
        self.filename = filename

        if p4info_path is not None:
            self.p4info_path = p4info_path
        else:
            self.p4info_path = f'./build/{self.filename}.p4.p4info.txt'

        if bmv2_file_path is not None:
            self.bmv2_file_path = bmv2_file_path
        else:
            self.bmv2_file_path = f'./build/{self.filename}.json'
        self.p4info_helper = common.p4runtime_lib.helper.P4InfoHelper(self.p4info_path)

        self.host = host
        self.port = f'5005{device_id+1}' if port is None else port

        self.connection = common.p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name=f's{device_id+1}',
            address=f'{self.host}:{self.port}',
            device_id=device_id,
            proto_dump_file=f'logs/port{self.port}-p4runtime-requests.txt',
            rate_limit=rate_limit,
            rate_limiter_buffer_size=rate_limiter_buffer_size,
            production_mode=enviroment_settings.production_mode if production_mode is None else production_mode,
            p4_config_support=enviroment_settings.p4_config_support if p4_config_support is None else p4_config_support,
            batch_delay=batch_delay
        )

        self.connection.MasterArbitrationUpdate(election_id_low=election_id_low)
        self.stream_subscribed_queues: List[QueueWithInfo] = []
        self.stream_subscribed_queues_lock = Lock()
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

    def subscribe_to_stream_with_queue(self, queue: Queue, extra_information: Optional[Any] = None) -> None:
        print("subscribe_to_stream_with_queue")
        with self.stream_subscribed_queues_lock:
            self.stream_subscribed_queues.append(QueueWithInfo(queue, extra_information))

        if len(self.stream_subscribed_queues) == 1:
            self.stream_handler_worker_thread = StreamHandlerWorkerThread(self)
            self.stream_handler_worker_thread.start()

    def unsubscribe_from_stream_with_queue(self, queue: Queue) -> None:
        with self.stream_subscribed_queues_lock:
            def filter_func(x: QueueWithInfo) -> bool:
                return x.queue == queue

            self.stream_subscribed_queues = filter(filter_func, self.stream_subscribed_queues)