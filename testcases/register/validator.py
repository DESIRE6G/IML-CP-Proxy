#!/usr/bin/env python3
import sys

from common.high_level_switch_connection import HighLevelSwitchConnection
from common.p4runtime_lib.switch import ShutdownAllSwitchConnections

if __name__ == '__main__':
    success = True

    s1 = HighLevelSwitchConnection(0, 'register', '60051', send_p4info=False)
    def check_table_rules(p4info_helper, connection):
        for response in connection.ReadRegisterEntries():
            for entity in response.entities:
                entry = entity.register_entry
                print(entry)

        return True

    success = success and check_table_rules(s1.p4info_helper, s1.connection)

    ShutdownAllSwitchConnections()

    if success:
        print('Validation succeed')
    else:
        print('Validation failed')
        sys.exit(1)
