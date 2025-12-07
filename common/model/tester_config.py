from typing import Optional, Dict

from pydantic import BaseModel


# The fields have to be Optional, because of the extendable configs
# (we have to be able to distinguish if it overwritten or just not added)
class TestConfig(BaseModel):
    start_mininet: Optional[bool] = None
    start_proxy: Optional[bool] = None
    start_controller: Optional[bool] = None
    run_validator: Optional[bool] = None
    load_redis_json: Optional[bool] = None
    file_overrides: Optional[Dict[str, str]] = None
    ongoing_controller: Optional[bool] = None
    exact_ping_packet_num: Optional[int] = None
