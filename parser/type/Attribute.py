from dataclasses import dataclass, field
from typing import List


@dataclass
class Attribute:
    name: str
    args: List[str] = field(default_factory=list)
