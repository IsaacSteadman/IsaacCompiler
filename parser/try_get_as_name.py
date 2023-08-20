from typing import List, Optional, Tuple


def try_get_as_name(
    tokens: List["Token"], c: int, end: int, context: "CompileContext"
) -> Tuple[Optional[List["Token"]], int]:
    del context
    start = c
    if tokens[c].type_id != TokenType.NAME and tokens[c].str != "::":
        return None, start
    c += 1
    while c < end:
        if tokens[c - 1].type_id == TokenType.NAME:
            if tokens[c].str != "::":
                return tokens[start:c], c
            c += 1
        elif tokens[c - 1].str == "::":
            if tokens[c].type_id != TokenType.NAME or tokens[c].str in KEYWORDS:
                return tokens[start:c], c
            c += 1
    return tokens[start:c], c


from ..lexer.lexer import Token, TokenType
from .constants import KEYWORDS
from .type.types import CompileContext
