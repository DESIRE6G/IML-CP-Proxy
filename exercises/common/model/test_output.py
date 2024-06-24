from typing import List, Optional

from pydantic import BaseModel

class PacketDump(BaseModel):
    raw: str
    dump: str

class PacketCompare(BaseModel):
    expected: str
    arrived: str
    arrived_colored: str
    diff_string: str
    dump_expected: str
    dump_arrived: str
    dump_arrived_colored: str
    dump_diff_string: str
    ok: bool
    

class TestOutput(BaseModel):
    success: Optional[bool] = None
    extra_packets: Optional[List[PacketDump]] = []
    missing_packets: Optional[List[PacketDump]] = []
    ordered_compare: Optional[List[PacketCompare]] = []
    message: Optional[str] = None
