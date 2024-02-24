from p4.v1 import p4runtime_pb2

from common.p4runtime_lib.helper import P4InfoHelper


class P4NameIdHelper:
    @staticmethod
    def get_entity_name(p4info_helper: P4InfoHelper, entity: p4runtime_pb2.Entity) -> str:
        which_one = entity.WhichOneof('entity')
        if which_one == 'table_entry':
            return p4info_helper.get_tables_name(entity.table_entry.table_id)
        elif which_one == 'counter_entry':
            return p4info_helper.get_counters_name(entity.counter_entry.counter_id)
        elif which_one == 'direct_counter_entry':
            return p4info_helper.get_tables_name(entity.direct_counter_entry.table_entry.table_id)
        elif which_one == 'meter_entry':
            return p4info_helper.get_meters_name(entity.meter_entry.meter_id)
        elif which_one == 'direct_meter_entry':
            return p4info_helper.get_tables_name(entity.direct_meter_entry.table_entry.table_id)
        else:
            raise Exception(f'Not implemented type for get_entity_name "{which_one}"')

    @staticmethod
    def get_p4_name_from_id(from_p4info_helper_inner: P4InfoHelper, id_type: str, original_id: int) -> str:
        if id_type == 'table':
            name = from_p4info_helper_inner.get_tables_name(original_id)
        elif id_type == 'meter':
            name = from_p4info_helper_inner.get_meters_name(original_id)
        elif id_type == 'action':
            name = from_p4info_helper_inner.get_actions_name(original_id)
        elif id_type == 'counter':
            name = from_p4info_helper_inner.get_counters_name(original_id)
        elif id_type == 'register':
            name = from_p4info_helper_inner.get_registers_name(original_id)
        elif id_type == 'digest':
            name = from_p4info_helper_inner.get_digests_name(original_id)
        else:
            raise Exception(f'convert_id cannot handle "{id_type}" id_type')
        return name