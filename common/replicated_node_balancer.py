from dataclasses import dataclass
from typing import Dict, Optional, List

from common.high_level_switch_connection_async import HighLevelSwitchConnection
from common.model.proxy_config import ProxyAllowedParamsDict, RedisMode
from proxy import ProxyServer, TargetSwitchConfig

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
    def __init__(self, program_name: str,
                           balancer_host: str,
                           balancer_port: int,
                           balancer_device_id: int,
                           balancer_program_name: str) -> None:
        self.program_name = program_name
        self._nodes: Dict[str, NodeHolder] = {}
        self.proxy_server: Optional[ProxyServer] = None

        self.balancer_host = balancer_host
        self.balancer_port = balancer_port
        self.balancer_device_id = balancer_device_id
        self.balancer_program_name = balancer_program_name
        self.balancer_connection: Optional[HighLevelSwitchConnection] = None

        self.balancer_proxy_server: Optional[ProxyServer] = None

    async def add_node(self, host: str, port: int, device_id: int, do_init: bool=True, filter_params_allow_only: Optional[ProxyAllowedParamsDict] = None) -> None:
        self._nodes[get_address_from_host_and_port(host, port)] = NodeHolder(
            host=host,
            port=port,
            device_id=device_id,
            filter_params_allow_only=filter_params_allow_only
        )

        if do_init:
            await self.init()

    def get_balancer_connection(self) -> HighLevelSwitchConnection:
        return self.balancer_connection

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

        if self.balancer_connection is None:
            self.balancer_connection = HighLevelSwitchConnection(
                self.balancer_device_id,
                self.balancer_program_name,
                self.balancer_port,
                send_p4info=True,
                reset_dataplane=False,
                host=self.balancer_host
            )
            await self.balancer_connection.init()

            p4info_path = f"build/{self.balancer_program_name}.p4.p4info.txt"
            self.balancer_proxy_server = ProxyServer(60059, '', p4info_path, self.balancer_connection, RedisMode.OFF)
            await self.balancer_proxy_server.start()


    async def add_filter_params_allow_only_to_host(self, host: str, port: int, filters_to_add: ProxyAllowedParamsDict) -> None:
        await self.proxy_server.add_filter_params_allow_only_to_host(host, port, filters_to_add)

    async def remove_from_filter_params_allow_only_to_host(self, host: str, port: int, filters_to_remove: ProxyAllowedParamsDict) -> None:
        await self.proxy_server.remove_from_filter_params_allow_only_to_host(host, port, filters_to_remove)
