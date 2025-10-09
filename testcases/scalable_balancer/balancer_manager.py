import asyncio
import datetime
import os
import time
from dataclasses import dataclass
from typing import List, Dict, Optional

from common.high_level_switch_connection_async import HighLevelSwitchConnection
from common.proxy_config import RedisMode, ProxyConfigSource, ProxyAllowedParamsDict
from proxy import TargetSwitchConfig, ProxyServer
from aiohttp import web

@dataclass
class NodeHolder:
    host: str
    port: int
    device_id: int
    connection: Optional[HighLevelSwitchConnection] = None
    flagged_to_remove: bool = False
    filter_params_allow_only: Optional[ProxyAllowedParamsDict] = None


def get_address_from_host_and_port(host: str, port: int) -> str:
    return f'{host}:{port}'

class ReplicatedNodeBalancerManager:
    def __init__(self, program_name: str) -> None:
        self.program_name = program_name
        self._nodes: Dict[str, NodeHolder] = {}
        self.proxy_server: Optional[ProxyServer] = None

    async def add_node(self, host: str, port: int, device_id: int, do_init: bool=True, filter_params_allow_only: Optional[ProxyAllowedParamsDict] = None) -> None:
        self._nodes[get_address_from_host_and_port(host, port)] = NodeHolder(
            host=host,
            port=port,
            device_id=device_id,
            filter_params_allow_only=filter_params_allow_only
        )

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
                target_switch_config = TargetSwitchConfig(node.connection, None, node.filter_params_allow_only, fill_counter_from_redis=False)
                new_target_switch_configs.append(target_switch_config)

        if self.proxy_server is None:
            p4info_path = f"build/{self.program_name}.p4.p4info.txt"
            self.proxy_server = ProxyServer(60051, '', p4info_path, new_target_switch_configs, RedisMode.READWRITE)

            await self.proxy_server.start()
        else:
            for new_target_switch_config in new_target_switch_configs:
                await self.proxy_server.add_target_switch(new_target_switch_config)

    async def add_filter_params_allow_only_to_host(self, host: str, port: int, filters_to_add: ProxyAllowedParamsDict) -> None:
        await self.proxy_server.add_filter_params_allow_only_to_host(host, port, filters_to_add)


async def handle(request):
    print('HANDLE function called, HELLOOO')
    name = request.match_info.get('name', "Anonymous")
    text = "Hello, " + name
    return web.Response(text=text)

def get_actual_time_to_log():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]

manager: Optional[ReplicatedNodeBalancerManager] = None
balancer_connection: Optional[HighLevelSwitchConnection] = None
source_address_data: Dict[str, int] = {}
async def add_node(request):
    global manager
    data = await request.json()
    host = data['host']
    port = int(data['port'])
    filter_params_allow_only = data.get('filter_params_allow_only')

    print(f'add_node request arrived: {data} {get_actual_time_to_log()}')
    print(filter_params_allow_only)
    await manager.add_node(host, port, int(data['device_id']), filter_params_allow_only=filter_params_allow_only)

    print(f'add_node finished {data}: {get_actual_time_to_log()}')
    return web.json_response({'status': 'OK'})

async def set_route(request):
    global manager, balancer_connection, source_address_data
    data = await request.json()
    print(f'set_route request arrived {data}')
    source_address = data['source_address']
    target_port = int(data['target_port'])
    subnet = int(data.get('subnet', 32))

    source_key = f'{source_address}/{subnet}'

    is_new_record = source_key not in source_address_data
    print(source_key, source_address_data, is_new_record)
    source_address_data[source_key] = target_port

    table_entry = balancer_connection.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": (source_address, subnet)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": target_port
        })
    await balancer_connection.connection.WriteTableEntry(table_entry, 'INSERT' if is_new_record else 'MODIFY')
    return web.json_response({'status': 'OK'})

if __name__ == "__main__":
    async def amain():
        runner = None
        try:
            app = web.Application()
            app.add_routes([
                web.get('/hello', handle),
                web.post('/add_node', add_node),
                web.post('/set_route', set_route)
            ])

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

            while time.time() - start_time < 3.5:
                await asyncio.sleep(0.1)
            await manager.add_filter_params_allow_only_to_host('127.0.0.1', 50054, {'hdr.ipv4.dstAddr': ['10.0.2.25']})


            while True:
                await asyncio.sleep(1)
        finally:
            print('Proxy stopping')
            if runner is not None:
                await runner.cleanup()

    asyncio.run(amain())
