import asyncio
import os
import time
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional

from common.high_level_switch_connection_async import HighLevelSwitchConnection
from common.proxy_config import RedisMode, ProxyConfigSource
from proxy import TargetSwitchConfig, ProxyServer


@dataclass
class NodeHolder:
    host: str
    port: int
    device_id: int
    connection: Optional[HighLevelSwitchConnection] = None
    flagged_to_remove: bool = False

class ReplicatedNodeBalancerManager:
    def __init__(self, program_name: str) -> None:
        self.program_name = program_name
        self._nodes: List[NodeHolder] = []
        self.proxy_server: Optional[ProxyServer] = None

    async def add_node(self, host: str, port: int, device_id: int, do_init: bool=True) -> None:
        self._nodes.append(NodeHolder(host=host, port=port, device_id=device_id))
        if do_init:
            await self.init()

    async def init(self) -> None:
        new_target_switch_configs: List[TargetSwitchConfig] = []
        for node in self._nodes:
            if node.connection is None:
                print(f'initializing node connection {node.host}:{node.port}, {self.program_name=} {node.device_id=}')
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

if __name__ == "__main__":
    async def amain():
        manager = ReplicatedNodeBalancerManager('fwd')
        await manager.add_node(host="127.0.0.1", port=50052, device_id=1, do_init=True)
        await manager.add_node(host="127.0.0.1", port=50053, device_id=2, do_init=True)

        balancer_connection = HighLevelSwitchConnection(0,'scalable_simple_balancer',50051, send_p4info=True, reset_dataplane=False, host='127.0.0.1')
        await balancer_connection.init()

        table_entry = balancer_connection.p4info_helper.buildTableEntry(
            table_name="MyIngress.ipv4_lpm",
            match_fields={
                "hdr.ipv4.srcAddr": ('10.0.1.13', 32)
            },
            action_name="MyIngress.set_port",
            action_params={
                "port": 2
            })
        await balancer_connection.connection.WriteTableEntry(table_entry)
        table_entry = balancer_connection.p4info_helper.buildTableEntry(
            table_name="MyIngress.ipv4_lpm",
            match_fields={
                "hdr.ipv4.srcAddr": ('10.0.1.25', 32)
            },
            action_name="MyIngress.set_port",
            action_params={
                "port": 3
            })
        await balancer_connection.connection.WriteTableEntry(table_entry)

        merger_node_connection = HighLevelSwitchConnection(4,'fwd2p1',50055, send_p4info=True, reset_dataplane=False, host='127.0.0.1')
        await merger_node_connection.init()
        print('Proxy is ready')

        while not os.path.exists('.pcap_send_started_h1'):
            await asyncio.sleep(0.25)
        await asyncio.sleep(2)

        await manager.add_node(host="127.0.0.1", port=50054, device_id=3)
        table_entry = balancer_connection.p4info_helper.buildTableEntry(
            table_name="MyIngress.ipv4_lpm",
            match_fields={
                "hdr.ipv4.srcAddr": ('10.0.1.33', 32)
            },
            action_name="MyIngress.set_port",
            action_params={
                "port": 4
            })
        await balancer_connection.connection.WriteTableEntry(table_entry)

        await asyncio.sleep(10)
        # await asyncio.sleep(1)

    asyncio.run(amain())
