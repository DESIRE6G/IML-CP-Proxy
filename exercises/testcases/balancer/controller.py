#!/usr/bin/env python3
from dataclasses import dataclass
from typing import Dict, List

from p4.v1 import p4runtime_pb2

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection

@dataclass
class BalancerNodeTarget:
    switch: HighLevelSwitchConnection
    port: int

@dataclass
class BalancerUser:
    target_node: int

class Balancer:
    def __init__(self,
        balancer_switch: HighLevelSwitchConnection
        ) -> None:
        self.balancer_switch = balancer_switch
        self.nodes: List[BalancerNodeTarget] = []
        self.user: Dict[str, BalancerUser] = {}

    def add_node(self, node_switch: HighLevelSwitchConnection, port: int) -> None:
        self.nodes.append(BalancerNodeTarget(switch=node_switch, port=port))

    def load_entries(self):
        for ip, user in self.user.items():
            node_target = self.nodes[user.target_node]
            s1 = self.balancer_switch

            table_entry = self.create_balancer_entry(ip, node_target.port)
            s1.connection.WriteTableEntry(table_entry)

    def create_balancer_entry(self, ip: str, target_port: int) -> p4runtime_pb2.TableEntry:
        return self.balancer_switch.p4info_helper.buildTableEntry(
            table_name="MyIngress.ipv4_lpm",
            match_fields={"hdr.ipv4.srcAddr": (ip, 32)},
            action_name="MyIngress.set_port",
            action_params={"port": target_port}
        )

    def set_target_node(self, ip: str, target_node: int) -> None:
        if ip not in self.user:
            self.user[ip] = BalancerUser(target_node=target_node)
        else:
            source_node = self.user[ip].target_node
            self.user[ip].target_node = target_node
            self.move_to_new_target(ip, source_node, target_node)

    def move_to_new_target(self, ip: str, source_node: int, target_node: int):
        source_switch = self.nodes[source_node].switch
        target_switch = self.nodes[target_node].switch

        entries = []
        for table_name in ["MyIngress.ipv4_lpm"]:
            request = p4runtime_pb2.ReadRequest()
            request.device_id = source_switch.device_id
            entity = request.entities.add()
            table_entry = entity.table_entry
            table_entry.table_id = source_switch.p4info_helper.get_tables_id(table_name)
            table_entry.match.extend([
                source_switch.p4info_helper.get_match_field_pb(table_name, "hdr.ipv4.srcAddr", (ip, 32))
            ])

            for response in source_switch.connection.client_stub.Read(request):
                for entity in response.entities:
                    entries.append(entity.table_entry)


        for entry in entries:
            target_switch.connection.WriteTableEntry(entry)

        target_port = self.nodes[target_node].port
        new_entry = self.create_balancer_entry(ip, target_port)
        self.balancer_switch.connection.WriteTableEntry(new_entry, update_type='MODIFY')

        for entry in entries:
            source_switch.connection.WriteTableEntry(entry, update_type='DELETE')




with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'balancer', '50051')
    s2 = HighLevelSwitchConnection(1, 'flagged_portfwd', '50052')
    s3 = HighLevelSwitchConnection(2, 'flagged_portfwd', '50053')

    balancer = Balancer(s1)
    balancer.add_node(s2, 2)
    balancer.add_node(s3, 3)

    balancer.set_target_node('10.0.1.13', 1)
    balancer.set_target_node('10.0.1.25', 0)

    balancer.load_entries()

    table_entry = s3.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.13', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 2
        })
    s3.connection.WriteTableEntry(table_entry)

    table_entry = s2.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.25', 32)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 2
        })
    s2.connection.WriteTableEntry(table_entry)

    balancer.set_target_node('10.0.1.13', 0)
    balancer.set_target_node('10.0.1.25', 1)

    # Fill Flagger for nodes
    table_entry = s2.p4info_helper.buildTableEntry(
        table_name="MyIngress.flagger",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.0', 24)
        },
        action_name="MyIngress.set_flag",
        action_params={
            "flag": 10
        })
    s2.connection.WriteTableEntry(table_entry)
    table_entry = s3.p4info_helper.buildTableEntry(
        table_name="MyIngress.flagger",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.0', 24)
        },
        action_name="MyIngress.set_flag",
        action_params={
            "flag": 11
        })
    s3.connection.WriteTableEntry(table_entry)

    # Fill last aggregator switch to forward everything to H2
    s4 = HighLevelSwitchConnection(3, 'portfwd', '50054')
    table_entry = s4.p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.srcAddr": ('10.0.1.0', 24)
        },
        action_name="MyIngress.set_port",
        action_params={
            "port": 3,
            "dstAddr": '08:00:00:00:02:22'
        })
    s4.connection.WriteTableEntry(table_entry)
