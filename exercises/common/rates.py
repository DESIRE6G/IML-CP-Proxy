from typing import List

from pydantic import BaseModel


class TickOutputJSON(BaseModel):
    tick_per_sec_list: List[float]
    average: float
    stdev: float
    delay_list: List[float]
    delay_average: float
    delay_stdev: float
