from dataclasses import dataclass
from typing import Dict


@dataclass
class AggregateLayout:
    size: int
    alignment: int
    offsets: Dict[str, int]
    bit_field_info: Dict[str, "BitFieldInfo"]


from .BitFieldInfo import BitFieldInfo
