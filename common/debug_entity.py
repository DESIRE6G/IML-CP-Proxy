import base64
import json
from typing import Union, Optional

from google.protobuf.json_format import MessageToJson
from google.protobuf.text_format import MessageToString
from p4.v1 import p4runtime_pb2

from common.p4runtime_lib.convert import decodeMac, decodeIPv4
from common.p4runtime_lib.helper import P4InfoHelper


def decode_value(b64: str) -> Union[str, int]:
    value_bytes = base64.b64decode(b64)
    if len(value_bytes) == 6:
        return decodeMac(value_bytes)
    if len(value_bytes) == 4:
        return decodeIPv4(value_bytes)
    else:
        return int.from_bytes(value_bytes, 'big')


def format_table_entry(entry: p4runtime_pb2.TableEntry) -> str:
    table_entry = entry['tableEntry']
    output = [f"TableEntry {table_entry['tableName']} ({table_entry['tableId']})"]

    for m in table_entry['match']:
        match_type = next(k for k in m.keys() if k != 'fieldId')
        match_content = m[match_type]

        if match_type == 'lpm':
            val_str = f"{match_content['value']}/{match_content['prefixLen']}"
        else:
            val_str = f"{match_content['value']}"

        output.append(f"   {match_type}: {val_str}")

    action_data = table_entry['action']['action']
    action_name = action_data['actionName']

    param_values = []
    if 'params' in action_data:
        sorted_params = sorted(action_data['params'], key=lambda x: x['paramId'])
        for p in sorted_params:
            if isinstance(p['value'], str):
                param_values.append(f'"{p["value"]}"')
            else:
                param_values.append(str(p['value']))

    output.append(f"   {action_name}({', '.join(param_values)})")

    return "\n".join(output)


def debug_entity(entity: p4runtime_pb2.Entity, p4_info_helper: Optional[P4InfoHelper] = None) -> None:
    which_one = entity.WhichOneof('entity')
    if which_one == 'table_entry':
        parsed_json = json.loads(MessageToJson(entity))
        if p4_info_helper is not None:
            table_id = parsed_json['tableEntry']['tableId']
            parsed_json['tableEntry']['tableName'] = p4_info_helper.get_tables_name(table_id)

        if 'match' in parsed_json['tableEntry']:
            match_list = parsed_json['tableEntry']['match']
            for match in match_list:
                if 'lpm' in match:
                    match['lpm']['value'] = decode_value(match['lpm']['value'])

        if 'action' in parsed_json['tableEntry']:
            action = parsed_json['tableEntry']['action']
            if 'action' in action:
                if 'params' in action['action']:
                    for param in action['action']['params']:
                        param['value'] = decode_value(param['value'])
                if p4_info_helper is not None:
                    action['action']['actionName'] = p4_info_helper.get_actions_name(action['action']['actionId'])
        print(format_table_entry(parsed_json))
    else:
        print(MessageToString(entity))
