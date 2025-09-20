#!/usr/bin/env python3

from common.controller_helper import ControllerExceptionHandling
from common.high_level_switch_connection import HighLevelSwitchConnection


with ControllerExceptionHandling():
    s1 = HighLevelSwitchConnection(0, 'register', '60051')
    '''
    register_entry = buildRegisterEntry(
        index=0
    )
    s1.connection.WriteRegister(register_entry)
    '''
