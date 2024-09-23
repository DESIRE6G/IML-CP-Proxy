# Copyright 2017-present Open Networking Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import functools
import re

import google.protobuf.text_format
from p4.config.v1 import p4info_pb2
from p4.v1 import p4runtime_pb2

from .convert import encode


class P4InfoHelper(object):
    def __init__(self, p4_info_filepath = None, raw_p4info = None):
        if p4_info_filepath is None and raw_p4info is None:
            raise Exception('For P4InfoHelper constructor p4_info_filepath and p4_info parameters cannot be None in the same time')

        p4info = p4info_pb2.P4Info()
        # Load the p4info file into a skeleton P4Info object
        if p4_info_filepath is not None:
            with open(p4_info_filepath) as p4info_f:
                google.protobuf.text_format.Merge(p4info_f.read(), p4info)

        if raw_p4info is not None:
            google.protobuf.text_format.Merge(raw_p4info, p4info)

        self.p4info = p4info

        for entity_name in ['tables', 'meters', 'actions', 'counters', 'registers', 'digests']:
            setattr(self, f'get_{entity_name}_id', functools.partial(self.get_id, entity_name))
            setattr(self, f'get_{entity_name}_name', functools.partial(self.get_name, entity_name))

    def get(self, entity_type, name=None, id=None):
        if name is not None and id is not None:
            raise AssertionError("name or id must be None")

        for o in getattr(self.p4info, entity_type):
            pre = o.preamble
            if name:
                if (pre.name == name or pre.alias == name):
                    return o
            else:
                if pre.id == id:
                    return o

        if name:
            raise AttributeError("Could not find %r of type %s" % (name, entity_type))
        else:
            raise AttributeError("Could not find id %r of type %s" % (id, entity_type))

    def get_id(self, entity_type, name):
        return self.get(entity_type, name=name).preamble.id

    def get_name(self, entity_type, id):
        return self.get(entity_type, id=id).preamble.name

    def get_alias(self, entity_type, id):
        return self.get(entity_type, id=id).preamble.alias

    def get_match_field(self, table_name, name=None, id=None):
        for t in self.p4info.tables:
            pre = t.preamble
            if pre.name == table_name:
                if name is None and id is None:
                    if len(t.match_fields) == 1:
                        return t.match_fields[0]
                    else:
                        raise Exception('You have to set id or name for match field if there are multiple match_fields')

                for mf in t.match_fields:
                    if name is not None:
                        if mf.name == name:
                            return mf
                    elif id is not None:
                        if mf.id == id:
                            return mf
        raise AttributeError("%r has no attribute %r" % (table_name, name if name is not None else id))

    def get_match_field_id(self, table_name, match_field_name):
        return self.get_match_field(table_name, name=match_field_name).id

    def get_match_field_name(self, table_name, match_field_id):
        return self.get_match_field(table_name, id=match_field_id).name

    def get_match_field_pb(self, table_name, match_field_name, value):
        p4info_match = self.get_match_field(table_name, match_field_name)
        bitwidth = p4info_match.bitwidth
        p4runtime_match = p4runtime_pb2.FieldMatch()
        p4runtime_match.field_id = p4info_match.id
        match_type = p4info_match.match_type
        if match_type == p4info_pb2.MatchField.EXACT:
            exact = p4runtime_match.exact
            exact.value = encode(value, bitwidth)
        elif match_type == p4info_pb2.MatchField.LPM:
            lpm_entry = p4runtime_match.lpm
            lpm_entry.value = encode(value[0], bitwidth)
            lpm_entry.prefix_len = value[1]
        elif match_type == p4info_pb2.MatchField.TERNARY:
            ternary_entry = p4runtime_match.ternary
            ternary_entry.value = encode(value[0], bitwidth)
            ternary_entry.mask = encode(value[1], bitwidth)
        elif match_type == p4info_pb2.MatchField.RANGE:
            range_entry = p4runtime_match.range
            range_entry.low = encode(value[0], bitwidth)
            range_entry.high = encode(value[1], bitwidth)
        else:
            raise Exception("Unsupported match type with type %r" % match_type)
        return p4runtime_match

    def get_match_field_value(self, match_field):
        match_type = match_field.WhichOneof("field_match_type")
        if match_type == 'valid':
            return match_field.valid.value
        elif match_type == 'exact':
            return match_field.exact.value
        elif match_type == 'lpm':
            return (match_field.lpm.value, match_field.lpm.prefix_len)
        elif match_type == 'ternary':
            return (match_field.ternary.value, match_field.ternary.mask)
        elif match_type == 'range':
            return (match_field.range.low, match_field.range.high)
        else:
            raise Exception("Unsupported match type with type %r" % match_type)

    def get_action_param(self, action_name, name=None, id=None):
        for a in self.p4info.actions:
            pre = a.preamble
            if pre.name == action_name:
                for p in a.params:
                    if name is not None:
                        if p.name == name:
                            return p
                    elif id is not None:
                        if p.id == id:
                            return p
        raise AttributeError("action %r has no param %r, (has: %r)" % (action_name, name if name is not None else id, a.params))

    def get_action_param_id(self, action_name, param_name):
        return self.get_action_param(action_name, name=param_name).id

    def get_action_param_name(self, action_name, param_id):
        return self.get_action_param(action_name, id=param_id).name

    def get_action_param_pb(self, action_name, param_name, value):
        p4info_param = self.get_action_param(action_name, param_name)
        p4runtime_param = p4runtime_pb2.Action.Param()
        p4runtime_param.param_id = p4info_param.id
        p4runtime_param.value = encode(value, p4info_param.bitwidth)
        return p4runtime_param

    def buildTableEntry(self,
                        table_name,
                        match_fields=None,
                        default_action=False,
                        action_name=None,
                        action_params=None,
                        priority=None):
        table_entry = p4runtime_pb2.TableEntry()
        table_entry.table_id = self.get_tables_id(table_name)

        if priority is not None:
            table_entry.priority = priority

        if match_fields:
            table_entry.match.extend([
                self.get_match_field_pb(table_name, match_field_name, value)
                for match_field_name, value in match_fields.items()
            ])

        if default_action:
            table_entry.is_default_action = True

        if action_name:
            action = table_entry.action.action
            action.action_id = self.get_actions_id(action_name)
            if action_params:
                action.params.extend([
                    self.get_action_param_pb(action_name, field_name, value)
                    for field_name, value in action_params.items()
                ])
        return table_entry

    def buildCounterEntry(self,
                        counter_name,
                          index,
                          packet_count,
                          byte_count):
        counter_entry = p4runtime_pb2.CounterEntry()
        counter_entry.counter_id = self.get_counters_id(counter_name)
        counter_entry.index.index = index
        counter_entry.data.byte_count = byte_count
        counter_entry.data.packet_count = packet_count
        return counter_entry

    def buildDirectCounterEntry(self,
                          table_name,
                          match_fields,
                          packet_count,
                          byte_count):

        direct_counter_entry = p4runtime_pb2.DirectCounterEntry()
        direct_counter_entry.table_entry.table_id = self.get_tables_id(table_name)
        table_entry = direct_counter_entry.table_entry
        if match_fields:
            table_entry.match.extend([
                self.get_match_field_pb(table_name, match_field_name, value)
                for match_field_name, value in match_fields.items()
            ])
        direct_counter_entry.data.byte_count = byte_count
        direct_counter_entry.data.packet_count = packet_count
        return direct_counter_entry

    def buildMeterConfigEntry(self,
                              meter_name,
                              cir,
                              cburst,
                              pir,
                              pburst,
                              index=0):
        meter_entry = p4runtime_pb2.MeterEntry()
        meter_entry.meter_id = self.get_meters_id(meter_name)
        meter_entry.index.index = index
        meter_entry.config.cir = cir
        meter_entry.config.cburst = cburst
        meter_entry.config.pir = pir
        meter_entry.config.pburst = pburst

        return meter_entry

    def buildDirectMeterConfigEntry(self,
                              table_name,
                              match_fields,
                              cir,
                              cburst,
                              pir,
                              pburst):
        direct_meter_entry = p4runtime_pb2.DirectMeterEntry()
        direct_meter_entry.table_entry.table_id = self.get_tables_id(table_name)
        table_entry = direct_meter_entry.table_entry
        if match_fields:
            table_entry.match.extend([
                self.get_match_field_pb(table_name, match_field_name, value)
                for match_field_name, value in match_fields.items()
            ])
        direct_meter_entry.config.cir = cir
        direct_meter_entry.config.cburst = cburst
        direct_meter_entry.config.pir = pir
        direct_meter_entry.config.pburst = pburst

        return direct_meter_entry


    def buildMulticastGroupEntry(self, multicast_group_id, replicas):
        mc_entry = p4runtime_pb2.PacketReplicationEngineEntry()
        mc_entry.multicast_group_entry.multicast_group_id = multicast_group_id
        for replica in replicas:
            r = p4runtime_pb2.Replica()
            r.egress_port = replica['egress_port']
            r.instance = replica['instance']
            mc_entry.multicast_group_entry.replicas.extend([r])
        return mc_entry

    def buildCloneSessionEntry(self, clone_session_id, replicas, packet_length_bytes=0):
        clone_entry = p4runtime_pb2.PacketReplicationEngineEntry()
        clone_entry.clone_session_entry.session_id = clone_session_id
        clone_entry.clone_session_entry.packet_length_bytes = packet_length_bytes
        clone_entry.clone_session_entry.class_of_service = 0  # PI currently supports only CoS=0 for clone session entry
        for replica in replicas:
            r = p4runtime_pb2.Replica()
            r.egress_port = replica['egress_port']
            r.instance = replica['instance']
            clone_entry.clone_session_entry.replicas.extend([r])
        return clone_entry

    def buildUpdate(self, entry, update_type = 'INSERT'):
        update = p4runtime_pb2.Update()
        if update_type == 'MODIFY':
            update.type = p4runtime_pb2.Update.MODIFY
        elif update_type == 'DELETE':
            update.type = p4runtime_pb2.Update.DELETE
        else:
            update.type = p4runtime_pb2.Update.INSERT

        if isinstance(entry, p4runtime_pb2.TableEntry):
            update.entity.table_entry.CopyFrom(entry)

        return update
