from typing import Optional, Dict

from pydantic import BaseModel


class TestConfig(BaseModel):
    file_overrides: Optional[Dict[str, str]] = None
    load_redis_json: Optional[bool] = None
    start_mininet: Optional[bool] = None
    ongoing_controller: Optional[bool] = None
    run_validator: Optional[bool] = None
    start_proxy: Optional[bool] = None
    start_controller: Optional[bool] = None
    exact_ping_packet_num: Optional[int] = None
