from typing import List
from .BaseStmnt import BaseStmnt, StmntType


class BreakStmnt(BaseStmnt):
    stmnt_type = StmntType.BRK
    # default pretty_repr
    # default __init__

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        del self, end, context
        c += 1
        if tokens[c].str != ";":
            raise ParsingError(tokens, c, "Expected ';' after 'break'")
        c += 1
        return c


from ..ParsingError import ParsingError
from ...lexer.lexer import Token
from ..context.CompileContext import CompileContext
