from dataclasses import dataclass
from typing import Optional


@dataclass
class StructLayoutEntry:
    member: Optional["ContextVariable"] = None
    bit_field_type: Optional["BaseType"] = None
    bit_field_width: Optional[int] = None


from .ContextVariable import ContextVariable
from .BaseType import BaseType
