from p4.v1 import p4runtime_pb2
from typing import Dict, Optional

from common.p4runtime_lib.helper import P4InfoHelper


RESTRICTED_P4_NAMES = ['NoAction']

def prefix_p4_name(original_p4_name : str, prefix : str) -> str:
    if original_p4_name in RESTRICTED_P4_NAMES:
        return original_p4_name

    if not '.' in original_p4_name:
        return f'{prefix}{original_p4_name}'

    namespace,table_name = original_p4_name.split('.')

    return f'{namespace}.{prefix}{table_name}'

class PrefixIsNotPresentException(Exception):
    pass

class EntityCannotHaveZeroId(Exception):
    pass

def remove_prefix_p4_name(prefixed_p4_name : str, prefix : str) -> str:
    if prefixed_p4_name in RESTRICTED_P4_NAMES:
        return prefixed_p4_name

    if prefixed_p4_name.startswith(prefix):
        return prefixed_p4_name[len(prefix):]

    if '.' not in prefixed_p4_name:
        raise PrefixIsNotPresentException()

    namespace,p4_name = prefixed_p4_name.split('.')
    if p4_name.startswith(prefix):
        return f'{namespace}.{p4_name[len(prefix):]}'
    else:
        raise Exception(f'Cannot find prefix "{prefix}" at the begining of the table name "{p4_name}"')


def get_pure_p4_name(original_table_name : str) -> str:
    namespace,p4_name = original_table_name.split('.')

    return f'{p4_name}'

class P4NameConverter:
    def __init__(self, from_p4info_helper: P4InfoHelper, to_p4info_helper: P4InfoHelper, prefix: str, converts: Optional[Dict[str, str]] = None) -> None:
        self.source_p4info_helper = from_p4info_helper
        self.target_p4info_helper = to_p4info_helper
        self.prefix = prefix
        self.converts = converts
        if self.converts is not None:
            self.reverse_converts = {value: key for key,value in converts.items()}

    def convert_id(self,
                   id_type:str,
                   original_id: int,
                   reverse = False,
                   verbose=True) -> int:

        if not reverse:
           from_p4info_helper_inner = self.source_p4info_helper
           target_p4info_helper = self.target_p4info_helper
        else:
           from_p4info_helper_inner = self.target_p4info_helper
           target_p4info_helper = self.source_p4info_helper
        name = P4NameConverter.get_p4_name_from_id(from_p4info_helper_inner, id_type, original_id)


        if self.converts is not None:
            if verbose:
                print(f'before convert name={name}')
            if reverse and name in self.reverse_converts:
                name = self.reverse_converts[name]
            elif not reverse and name in self.converts:
                name = self.converts[name]

        if verbose:
            print(f'name={name}')
        if reverse:
            new_name = remove_prefix_p4_name(name, self.prefix)
        else:
            new_name = prefix_p4_name(name, self.prefix)
        if verbose:
            print(f'new_name={new_name}')

        if id_type == 'table':
            return target_p4info_helper.get_tables_id(new_name)
        if id_type == 'meter':
            return target_p4info_helper.get_meters_id(new_name)
        elif id_type == 'action':
            return target_p4info_helper.get_actions_id(new_name)
        elif id_type == 'counter':
            return target_p4info_helper.get_counters_id(new_name)
        elif id_type == 'register':
            return target_p4info_helper.get_registers_id(new_name)
        elif id_type == 'digest':
            return target_p4info_helper.get_digests_id(new_name)
        else:
            raise Exception(f'convert_id cannot handle "{id_type}" id_type')


    def convert_table_entry(self,
                            table_entry: p4runtime_pb2.TableEntry,
                            reverse: bool=False,
                            verbose: bool=True) -> None:
        if table_entry.table_id != 0:
            table_entry.table_id = self.convert_id('table', table_entry.table_id,
                                                          reverse, verbose)
        if table_entry.HasField('action'):
            if table_entry.action.WhichOneof('type') == 'action':
                table_entry.action.action.action_id = self.convert_id('action', table_entry.action.action.action_id,
                                                  reverse, verbose)
            else:
                raise Exception(f'Unhandled action type {table_entry.action.type}')

    def convert_meter_entry(self,
                            meter_entry: p4runtime_pb2.MeterEntry,
                            reverse: bool=False,
                            verbose: bool=True) -> None:
        if meter_entry.meter_id != 0:
            meter_entry.meter_id = self.convert_id('meter', meter_entry.meter_id,
                                                          reverse, verbose)
    def convert_direct_meter_entry(self,
                                   direct_meter_entry: p4runtime_pb2.DirectMeterEntry,
                                   reverse: bool=False,
                                   verbose: bool=True) -> None:
        if direct_meter_entry.table_entry.table_id != 0:
            direct_meter_entry.table_entry.table_id = self.convert_id('table', direct_meter_entry.table_entry.table_id,
                                                          reverse, verbose)


    def convert_counter_entry(self,
                              counter_entry: p4runtime_pb2.CounterEntry,
                              reverse: bool=False,
                              verbose: bool=True) -> None:
        if counter_entry.counter_id != 0:
            counter_entry.counter_id = self.convert_id('counter', counter_entry.counter_id,
                                                      reverse, verbose)


    def convert_direct_counter_entry(self,
                                     direct_counter_entry: p4runtime_pb2.DirectCounterEntry,
                                     reverse: bool=False,
                                     verbose: bool=True) -> None:
        if direct_counter_entry.table_entry.table_id != 0:
            direct_counter_entry.table_entry.table_id = self.convert_id('table', direct_counter_entry.table_entry.table_id,
                                                      reverse, verbose)

    def convert_register_entry(self,
                               register_entry: p4runtime_pb2.RegisterEntry,
                               reverse: bool=False,
                               verbose: bool=True) -> None:
        if register_entry.register_id != 0:
            register_entry.register_id = self.convert_id('counter', register_entry.register_id,
                                                      reverse, verbose)
    def convert_digest_entry(self,
                              digest_entry: p4runtime_pb2.DigestEntry,
                              reverse: bool=False,
                              verbose: bool=True) -> None:
        if digest_entry.digest_id != 0:
            digest_entry.digest_id = self.convert_id('digest', digest_entry.digest_id,
                                                      reverse, verbose,)

    def convert_entity(self,
                       entity: p4runtime_pb2.Entity,
                       reverse: bool=False,
                       verbose: bool=True) -> None:
        which_one = entity.WhichOneof('entity')
        if which_one == 'table_entry':
            self.convert_table_entry(entity.table_entry, reverse, verbose)
        elif which_one == 'counter_entry':
            self.convert_counter_entry( entity.counter_entry, reverse, verbose)
        elif which_one == 'direct_counter_entry':
            self.convert_direct_counter_entry( entity.direct_counter_entry, reverse, verbose)
        elif which_one == 'meter_entry':
            self.convert_meter_entry(entity.meter_entry, reverse, verbose)
        elif which_one == 'direct_meter_entry':
            self.convert_direct_meter_entry(entity.direct_meter_entry, reverse, verbose)
        elif which_one == 'register_entry':
            self.convert_register_entry(entity.register_entry, reverse, verbose)
        elif which_one == 'digest_entry':
            self.convert_digest_entry(entity.digest_entry, reverse, verbose)
        else:
            raise Exception(f'Not implemented type for convert_entity "{which_one}"')

    def convert_read_request(self,
                             request: p4runtime_pb2.ReadRequest,
                             verbose: bool=True) -> None:
        for entity in request.entities:
            self.convert_entity(entity, reverse=False,verbose=verbose)


    def convert_digest_list(self, digest: p4runtime_pb2.DigestList) -> None:
        digest.digest_id = self.convert_id('digest', digest.digest_id, reverse=True)

    def convert_stream_response(self, stream_response: p4runtime_pb2.StreamMessageResponse) -> None:
        which_one = stream_response.WhichOneof('update')
        if which_one == 'digest':
            self.convert_digest_list(stream_response.digest)
        else:
            raise Exception(f'Not implemented type for convert_stream_response "{which_one}"')

    def get_target_entity_name(self, entity: p4runtime_pb2.Entity) -> str:
        return self.__class__.get_entity_name(self.target_p4info_helper, entity)

    def get_source_entity_name(self, entity: p4runtime_pb2.Entity) -> str:
        return self.__class__.get_entity_name(self.source_p4info_helper, entity)

    def get_target_p4_name_from_id(self, id_type: str, original_id: int) -> str:
        return self.__class__.get_p4_name_from_id(self.target_p4info_helper, id_type, original_id)

    @staticmethod
    def get_entity_name(p4info_helper: P4InfoHelper, entity: p4runtime_pb2.Entity) -> str:
        def assert_non_zero_entity_id_and_return(entity_id: int):
            if entity_id == 0:
                raise EntityCannotHaveZeroId()

            return entity_id

        which_one = entity.WhichOneof('entity')
        if which_one == 'table_entry':
            return p4info_helper.get_tables_name(assert_non_zero_entity_id_and_return(entity.table_entry.table_id))
        elif which_one == 'counter_entry':
            return p4info_helper.get_counters_name(assert_non_zero_entity_id_and_return(entity.counter_entry.counter_id))
        elif which_one == 'direct_counter_entry':
            return p4info_helper.get_tables_name(assert_non_zero_entity_id_and_return(entity.direct_counter_entry.table_entry.table_id))
        elif which_one == 'meter_entry':
            return p4info_helper.get_meters_name(assert_non_zero_entity_id_and_return(entity.meter_entry.meter_id))
        elif which_one == 'direct_meter_entry':
            return p4info_helper.get_tables_name(assert_non_zero_entity_id_and_return(entity.direct_meter_entry.table_entry.table_id))
        elif which_one == 'digest_entry':
            return p4info_helper.get_digests_name(assert_non_zero_entity_id_and_return(entity.digest_entry.digest_id))
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