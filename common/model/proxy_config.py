from enum import Enum
from typing import Optional, Dict, Any, List, Union, Tuple

from pydantic import BaseModel, Field, AliasChoices

class RedisMode(Enum):
    READWRITE = 'READWRITE'
    ONLY_WRITE = 'ONLY_WRITE'
    ONLY_READ = 'ONLY_READ'
    OFF = 'OFF'

    @classmethod
    def is_reading(cls, redis_mode: 'RedisMode') -> bool:
        return redis_mode == RedisMode.READWRITE or redis_mode == RedisMode.ONLY_READ

    @classmethod
    def is_writing(cls, redis_mode: 'RedisMode') -> bool:
        return redis_mode == RedisMode.READWRITE or redis_mode == RedisMode.ONLY_WRITE


ProxyAllowedParamsDict = Dict[str, List[Union[str, float, Tuple[str, int]]]]

class ProxyConfigTarget(BaseModel):
    program_name: str
    port: int
    device_id: int
    reset_dataplane: Optional[bool] = False
    names: Optional[Dict[str,str]] = None
    rate_limit: Optional[int] = None
    rate_limiter_buffer_size: Optional[int] = None
    batch_delay: Optional[float] = None
    host: Optional[str] = '127.0.0.1'
    filter_params_allow_only: Optional[ProxyAllowedParamsDict] = None


class ProxyConfigSource(BaseModel):
    program_name: str
    prefix: str = ''
    port: int = Field(validation_alias=AliasChoices('controller_port', 'port'))
    worker_num: int = 10


class ProxyConfigPreloadEntry(BaseModel):
    type: str
    parameters: Dict[str, Any]
    target_index: int = 0


class ProxyConfigMapping(BaseModel):
    target: Optional[ProxyConfigTarget] = None
    targets: List[ProxyConfigTarget] = []
    source: Optional[ProxyConfigSource] = None
    sources: List[ProxyConfigSource] = []
    preload_entries: List[ProxyConfigPreloadEntry] = []


class ProxyConfig(BaseModel):
    redis: RedisMode
    mappings: List[ProxyConfigMapping]
