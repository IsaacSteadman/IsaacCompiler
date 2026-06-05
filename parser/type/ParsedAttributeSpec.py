from dataclasses import dataclass, field
from typing import List


@dataclass
class ParsedAttributeSpec:
    attribute: "Attribute"
    arg_tokens: List[List["Token"]] = field(default_factory=list)


from .Attribute import Attribute
from ...lexer.lexer import Token
