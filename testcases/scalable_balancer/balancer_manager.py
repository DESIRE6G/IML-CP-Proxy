import asyncio
import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional, Callable, Awaitable, Type

from pydantic import BaseModel

from common.high_level_switch_connection_async import HighLevelSwitchConnection
from common.proxy_config import RedisMode, ProxyAllowedParamsDict
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


def get_actual_time_to_log() -> str:
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]

manager: Optional[ReplicatedNodeBalancerManager] = None
balancer_connection: Optional[HighLevelSwitchConnection] = None
source_address_data: Dict[str, int] = {}


api_routes: List[web.RouteDef] = []

def api_endpoint(method: str, endpoint: str, parameter_model: Type[BaseModel]):
    def decorator(function: Callable[[any], Awaitable[web.Response]]) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
        async def wrapper(request: web.Request) -> web.StreamResponse:
            params = parameter_model.model_validate(await request.json())
            print(f'API::{function.__name__} request arrived {params}')
            return await function(params)
        wrapper.__name__ = function.__name__

        method_lower = method.lower()
        if method_lower in ['get', 'post']:
            api_routes.append(getattr(web, method_lower)(endpoint, wrapper))
        else:
            raise NotImplementedError(f'Unknown method for api_endpoint decorator: {method}')

        return wrapper
    return decorator

class AddNodeParameters(BaseModel):
    host: str
    port: int
    device_id: int
    filter_params_allow_only: Optional[ProxyAllowedParamsDict] = None

@api_endpoint('post', '/add_node', AddNodeParameters)
async def add_node(params: AddNodeParameters) -> web.Response:
    global manager
    await manager.add_node(params.host, params.port, int(params.device_id), filter_params_allow_only=params.filter_params_allow_only)
    return web.json_response({'status': 'OK'})

class SetRouteParameters(BaseModel):
    source_address: str
    target_port: int
    subnet: int = 32

@api_endpoint('post', '/set_route', SetRouteParameters)
async def set_route(params: SetRouteParameters) -> web.Response:
    global manager, balancer_connection, source_address_data
    source_key = f'{params.source_address}/{params.subnet}'

    is_new_record = source_key not in source_address_data
    print(source_key, source_address_data, is_new_record)
    source_address_data[source_key] = params.target_port

    table_entry = balancer_connection.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": (params.source_address, params.subnet)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": params.target_port
        })
    await balancer_connection.connection.WriteTableEntry(table_entry, 'INSERT' if is_new_record else 'MODIFY')
    return web.json_response({'status': 'OK'})


class SetFilterParameters(BaseModel):
    host: str
    port: int
    filter: ProxyAllowedParamsDict

@api_endpoint('post', '/set_filter', SetFilterParameters)
async def set_filter(params: SetFilterParameters) -> web.Response:
    global manager, balancer_connection, source_address_data
    await manager.add_filter_params_allow_only_to_host(params.host, params.port, params.filter)

    return web.json_response({'status': 'OK'})


if __name__ == "__main__":
    async def amain():
        runner = None
        try:
            app = web.Application()
            app.add_routes(api_routes)

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
            while True:
                await asyncio.sleep(1)
        finally:
            print('Proxy stopping')
            if runner is not None:
                await runner.cleanup()

    asyncio.run(amain())
