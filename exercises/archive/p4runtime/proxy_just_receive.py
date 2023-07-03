import logging
import time
from concurrent import futures
from pprint import pprint

import grpc
from p4.v1.p4runtime_pb2 import StreamMessageRequest, StreamMessageResponse, SetForwardingPipelineConfigResponse, \
    Update, WriteResponse, ReadResponse
from p4.v1.p4runtime_pb2_grpc import P4RuntimeServicer, add_P4RuntimeServicer_to_server


logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)

class ProxyP4RuntimeServicer(P4RuntimeServicer):

    def __init__(self):
        self.table_entries = []

    def Write(self, request, context):
        """Update one or more P4 entities on the target.
        """
        print('Write')
        for update in request.updates:
            if update.type == Update.INSERT:
                if update.entity.WhichOneof('entity') == 'table_entry':
                    self.table_entries.append(update.entity.table_entry)
                    print(update.entity.table_entry)
                else:
                    raise Exception(f'Unhandled update type {update.type}')
            else:
                raise Exception(f'Unhandled update type {update.type}')

        return WriteResponse()


    def Read(self, request, context):
        """Read one or more P4 entities from the target.
        """
        ret = ReadResponse()

        for stored_entity in self.table_entries:
            entity = ret.entities.add()
            print(dir(stored_entity))
            entity.table_entry.CopyFrom(stored_entity)

        yield ret

    def SetForwardingPipelineConfig(self, request, context):
        """Sets the P4 forwarding-pipeline config.
        """
        print('SetForwardingPipelineConfig')
        return SetForwardingPipelineConfigResponse()

    def GetForwardingPipelineConfig(self, request, context):
        """Gets the current P4 forwarding-pipeline config.
        """
        print('GetForwardingPipelineConfig')
        print(request)
        print(context)
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def StreamChannel(self, request_iterator, context):
        for request in request_iterator:
            logger.info('StreamChannel message arrived')
            logger.info(request)
            which_one = request.WhichOneof('update')
            if which_one == 'arbitration':
                response = StreamMessageResponse()
                response.arbitration.device_id = request.arbitration.device_id
                response.arbitration.election_id.high = 0
                response.arbitration.election_id.low = 1
                yield response
            else:
                raise Exception(f'Unhandled Stream field type {request.WhichOneof}')


    def Capabilities(self, request, context):
        # missing associated documentation comment in .proto file
        print('Capabilities')
        print(request)
        print(context)
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

servers = []
def serve(port):
    global servers
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    servicer = ProxyP4RuntimeServicer()
    add_P4RuntimeServicer_to_server(servicer, server)
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    servers.append(server)

serve('50051')
serve('50052')

try:
    while True:
        time.sleep(60 * 60)
except KeyboardInterrupt:
    for server in servers:
        server.stop(0)

