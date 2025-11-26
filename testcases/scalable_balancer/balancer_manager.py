import asyncio
from typing import List, Dict, Optional, Callable, Awaitable, Type

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.high_level_switch_connection_async import HighLevelSwitchConnection
from common.model.proxy_config import ProxyAllowedParamsDict
from common.replicated_node_balancer import ReplicatedNodeBalancerManager
from aiohttp import web

manager: Optional[ReplicatedNodeBalancerManager] = None

class SourceAddressData(BaseModel):
    port: int

source_address_data: Dict[str, SourceAddressData] = {}

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


class RemoveNodeParameters(BaseModel):
    host: str
    port: int

@api_endpoint('post', '/remove_node', RemoveNodeParameters)
async def remove_node(params: RemoveNodeParameters) -> web.Response:
    global manager
    await manager.remove_node(params.host, params.port)
    return web.json_response({'status': 'OK'})


class SetRouteParameters(BaseModel):
    source_address: str
    target_port: int

@api_endpoint('post', '/set_route', SetRouteParameters)
async def set_route(params: SetRouteParameters) -> web.Response:
    global manager, source_address_data
    source_address = params.source_address

    is_new_record = source_address not in source_address_data
    print(source_address, source_address_data, is_new_record)
    source_address_data[source_address] = SourceAddressData(port=params.target_port)
    balancer_connection = manager.get_balancer_connection()
    table_entry = balancer_connection.p4info_helper.build_table_entry(
        table_name="MyIngress.ipv4_exact",
        match_fields={
            "hdr.ipv4.srcAddr": source_address
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": params.target_port
        })
    await manager.balancer_connection.connection.WriteTableEntry(table_entry, 'INSERT' if is_new_record else 'MODIFY')
    return web.json_response({'status': 'OK'})


class AddFilterParameters(BaseModel):
    host: str
    port: int
    filter: ProxyAllowedParamsDict

@api_endpoint('post', '/add_to_filter', AddFilterParameters)
async def add_to_filter(params: AddFilterParameters) -> web.Response:
    global manager, source_address_data
    await manager.add_filter_params_allow_only_to_host(params.host, params.port, params.filter)

    return web.json_response({'status': 'OK'})

class RemoveFromFilterParameters(BaseModel):
    host: str
    port: int
    filter: ProxyAllowedParamsDict

@api_endpoint('post', '/remove_from_filter', AddFilterParameters)
async def remove_from_filter(params: AddFilterParameters) -> web.Response:
    global manager, source_address_data
    await manager.remove_from_filter_params_allow_only_to_host(params.host, params.port, params.filter)

    return web.json_response({'status': 'OK'})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')
    api_host: str = '127.0.0.1'
    api_port: int = 8080

    node_p4_program_name: str = 'scalable_balancer_fwd'

    balancer_host: str = '127.0.0.1'
    balancer_port: int = 50051
    balancer_device_id: int = 0
    balancer_p4_program_name: str = 'scalable_simple_balancer'


if __name__ == "__main__":
    settings = Settings()
    async def amain():
        runner = None
        try:
            app = web.Application()
            app.add_routes(api_routes)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, settings.api_host, settings.api_port)
            await site.start()

            global manager
            manager = ReplicatedNodeBalancerManager(
                settings.node_p4_program_name,
                settings.balancer_host,
                settings.balancer_port,
                settings.balancer_device_id,
                settings.balancer_p4_program_name
            )
            await manager.init()

            print('Proxy is ready')
            while True:
                await asyncio.sleep(1)
        finally:
            print('Proxy stopping')
            if runner is not None:
                await runner.cleanup()

    asyncio.run(amain())
