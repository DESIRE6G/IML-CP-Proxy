from typing import List, Dict

from pydantic import BaseModel


class TickOutputJSON(BaseModel):
    tick_per_sec_list: List[float]
    average: float
    stdev: float
    tick_per_sec_by_table: Dict[str, List[float]]
    average_by_table: Dict[str, float]
    stdev_by_table: Dict[str, float]
    delay_list: List[float]
    delay_average: float
    delay_stdev: float
    delay_list_by_table: Dict[str, List[float]]
    delay_average_by_table: Dict[str, float]
    delay_stdev_by_table: Dict[str, float]