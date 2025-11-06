from typing import List, Union, Dict

from google.protobuf.json_format import MessageToJson
from p4.v1 import p4runtime_pb2

def calculate_read_entity_custom_identifier(entity: p4runtime_pb2.Entity) -> Union[str, int]:
    which_one = entity.WhichOneof('entity')
    if which_one == 'table_entry':
        return entity.table_entry.table_id
    if which_one == 'meter_entry':
        return entity.meter_entry.meter_id
    if which_one == 'direct_meter_entry':
        return entity.direct_meter_entry.table_entry.table_id
    if which_one == 'counter_entry':
        return f'{entity.counter_entry.counter_id}-{entity.counter_entry.index}'
    if which_one == 'direct_counter_entry':
        return MessageToJson(entity.direct_counter_entry.table_entry) #table and match are both in
    raise NotImplementedError(f'{which_one} is not handled by read feedback')


class EntityHelper:
    @staticmethod
    def is_entity_mergable_to_entity_list(entity: p4runtime_pb2.Entity, entities: List[p4runtime_pb2.Entity]) -> bool:
        to_add_cid = calculate_read_entity_custom_identifier(entity)
        for entity_merge_to in entities:
            if to_add_cid == calculate_read_entity_custom_identifier(entity_merge_to):
                return True

        return False

    @staticmethod
    def merge_duplicates_for_read_answer(received_entries: List[p4runtime_pb2.Entity]) -> List[p4runtime_pb2.Entity]:
        groupped_entries: Dict[Union[str, int], p4runtime_pb2.Entity] = {}
        for entity in received_entries:
            identifier = calculate_read_entity_custom_identifier(entity)
            if identifier not in groupped_entries:
                groupped_entries[identifier] = []

            groupped_entries[identifier].append(entity)

        ret: List[p4runtime_pb2.Entity] = []
        def are_all_same_entity(entities: List[p4runtime_pb2.Entity]) -> bool:
            json_dump = None
            for entity in entities:
                if json_dump is None:
                    json_dump = MessageToJson(entity)
                elif json_dump != MessageToJson(entity):
                    return False
            return True

        for group in groupped_entries.values():
            first_entity = group[0]
            which_one = first_entity.WhichOneof('entity')
            if which_one in ['table_entry', 'meter_entry', 'direct_meter_entry']:
                if not are_all_same_entity(group):
                    raise Exception(f'Cannot merge, because responses are differs on different targets {group}')
            elif which_one == 'counter_entry':
                for entity in group[1:]:
                    first_entity.counter_entry.data.byte_count += entity.counter_entry.data.byte_count
                    first_entity.counter_entry.data.packet_count += entity.counter_entry.data.packet_count
            elif which_one == 'direct_counter_entry':
                for entity in group[1:]:
                    first_entity.direct_counter_entry.data.byte_count += entity.direct_counter_entry.data.byte_count
                    first_entity.direct_counter_entry.data.packet_count += entity.direct_counter_entry.data.packet_count
            else:
                raise NotImplementedError(f'{which_one} is not handled by read feedback')
            ret.append(first_entity)

        return ret

    @staticmethod
    def is_counter_entity_data_empty(entity: p4runtime_pb2) -> bool:
        which_one = entity.WhichOneof('entity')
        if which_one == 'direct_counter_entry':
            data = entity.direct_counter_entry.data
        elif which_one == 'counter_entry':
            data = entity.counter_entry.data
        else:
            raise Exception(f'Here only counter entry should arrive: {which_one}')

        return data.packet_count == 0 and data.byte_count == 0

    @classmethod
    def is_table_id_and_match_equals(cls, table_entry1: p4runtime_pb2.TableEntry, table_entry2: p4runtime_pb2.TableEntry) -> bool:
        if table_entry1.table_id != table_entry2.table_id:
            return False

        for match1, match2 in zip(table_entry1.match, table_entry2.match):
            if MessageToJson(match1) != MessageToJson(match2):
                return False

        return True


