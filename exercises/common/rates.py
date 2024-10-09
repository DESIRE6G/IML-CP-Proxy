from typing import List

from pydantic import BaseModel


class TickOutputJSON(BaseModel):
    tick_per_sec_list: List[float]
    average: float