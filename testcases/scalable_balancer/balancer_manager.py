import asyncio
import datetime
import os
import time
from dataclasses import dataclass
from typing import List, Dict, Optional

from common.high_level_switch_connection_async import HighLevelSwitchConnection
from common.proxy_config import RedisMode, ProxyConfigSource
from proxy import TargetSwitchConfig, ProxyServer
from aiohttp import web

@dataclass
class NodeHolder:
    host: str
    port: int
    device_id: int
    connection: Optional[HighLevelSwitchConnection] = None
    flagged_to_remove: bool = False


def get_address_from_host_and_port(host: str, port: int) -> str:
    return f'{host}:{port}'

class ReplicatedNodeBalancerManager:
    def __init__(self, program_name: str) -> None:
        self.program_name = program_name
        self._nodes: Dict[str, NodeHolder] = {}
        self.proxy_server: Optional[ProxyServer] = None

    async def add_node(self, host: str, port: int, device_id: int, do_init: bool=True) -> None:
        self._nodes[get_address_from_host_and_port(host, port)] = NodeHolder(host=host, port=port, device_id=device_id)
        if do_init:
            await self.init()

    async def remove_node(self, host: str, port: int) -> None:
        address = get_address_from_host_and_port(host, port)
        self._nodes.pop(address)
        await self.proxy_server.remove_target_switch(host, port)


    async def init(self) -> None:
        new_target_switch_configs: List[TargetSwitchConfig] = []
        for node in self._nodes.values():
            if node.connection is None:
                address = get_address_from_host_and_port(node.host, node.port)
                print(f'initializing node connection {address}, {self.program_name=} {node.device_id=}')
                connection = HighLevelSwitchConnection(
                    node.device_id,
                    self.program_name,
                    node.port,
                    send_p4info=True,
                    reset_dataplane=False,
                    host=node.host
                )
                await connection.init()
                node.connection = connection
                target_switch_config = TargetSwitchConfig(node.connection, None)
                new_target_switch_configs.append(target_switch_config)

        if self.proxy_server is None:
            p4info_path = f"build/{self.program_name}.p4.p4info.txt"
            print(new_target_switch_configs)
            self.proxy_server = ProxyServer(60051, '', p4info_path, new_target_switch_configs, RedisMode.READWRITE)

            await self.proxy_server.start()
        else:
            for new_target_switch_config in new_target_switch_configs:
                await self.proxy_server.add_target_switch(new_target_switch_config)



async def handle(request):
    print('HANDLE function called, HELLOOO')
    name = request.match_info.get('name', "Anonymous")
    text = "Hello, " + name
    return web.Response(text=text)

def get_actual_time_to_log():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
manager: Optional[ReplicatedNodeBalancerManager] = None
balancer_connection: Optional[HighLevelSwitchConnection] = None
BALANCER_MAPPING = {
    2: '10.0.1.13',
    3: '10.0.1.25',
    4: '10.0.1.33',
}
async def add_node(request):
    global manager
    data = await request.json()
    print(f'add_node request arrived: {data} {get_actual_time_to_log()}')
    await manager.add_node(data['host'], int(data['port']), int(data['device_id']))

    s1_output_port = int(data['device_id']) + 1
    table_entry = balancer_connection.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": (BALANCER_MAPPING[s1_output_port], 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": s1_output_port
        })
    await balancer_connection.connection.WriteTableEntry(table_entry)
    print(f'add_node finished {data}: {get_actual_time_to_log()}')
    return web.json_response({'status': 'OK'})

if __name__ == "__main__":
    async def amain():
        runner = None
        try:
            app = web.Application()
            app.add_routes([web.get('/hello', handle), (web.post('/add_node', add_node))])
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 8080)
            await site.start()
            global manager
            manager = ReplicatedNodeBalancerManager('scalable_balancer_fwd')
            await manager.init()

            global balancer_connection
            balancer_connection = HighLevelSwitchConnection(0,'scalable_simple_balancer',50051, send_p4info=True, reset_dataplane=False, host='127.0.0.1')
            await balancer_connection.init()


            merger_node_connection = HighLevelSwitchConnection(4,'fwd2p1',50055, send_p4info=True, reset_dataplane=False, host='127.0.0.1')
            await merger_node_connection.init()

            print('Proxy is ready')
            while not os.path.exists('.pcap_send_started_h1'):
                await asyncio.sleep(0.05)
            start_time = time.time()
            while time.time() - start_time < 2.5:
                await asyncio.sleep(0.1)

            # reroute 33 to port 2
            table_entry = balancer_connection.p4info_helper.buildTableEntry(
                    table_name="MyIngress.ipv4_lpm",
                    match_fields={
                        "hdr.ipv4.srcAddr": ('10.0.1.33', 32)
                    },
                    action_name="MyIngress.set_port",
                    action_params={
                        "port": 2
                    })
            await balancer_connection.connection.WriteTableEntry(table_entry, 'MODIFY')
            # reroute 25 to port 4
            table_entry = balancer_connection.p4info_helper.buildTableEntry(
                    table_name="MyIngress.ipv4_lpm",
                    match_fields={
                        "hdr.ipv4.srcAddr": ('10.0.1.25', 32)
                    },
                    action_name="MyIngress.set_port",
                    action_params={
                        "port": 4
                    })
            await balancer_connection.connection.WriteTableEntry(table_entry, 'MODIFY')

            while True:
                await asyncio.sleep(1)
        finally:
            print('Proxy stopping')
            if runner is not None:
                await runner.cleanup()

    asyncio.run(amain())
