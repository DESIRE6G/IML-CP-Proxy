import socket

from pydantic import BaseModel

class EnviromentSettings(BaseModel):
    production_mode: bool = False
    p4_config_support: bool = False

if socket.gethostname() == 'dpdk-switch':
    enviroment_settings = EnviromentSettings(
        production_mode = True,
        p4_config_support = False
    )
elif socket.gethostname() == 'mininet-vm':
    enviroment_settings = EnviromentSettings(
        production_mode = False,
        p4_config_support = True
    )
else:
    enviroment_settings = EnviromentSettings()
