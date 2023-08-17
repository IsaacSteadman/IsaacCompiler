from typing import List
from .BaseStmnt import BaseStmnt, StmntType


class ContinueStmnt(BaseStmnt):
    stmnt_type = StmntType.CONTINUE

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        del self, end, context
        c += 1
        if tokens[c].str != ";":
            raise ParsingError(tokens, c, "Expected ';' after 'continue'")
        c += 1
        return c

    # default pretty_repr
    # default __init__


from ..ParsingError import ParsingError
from ...lexer.lexer import Token
from ..context.CompileContext import CompileContext
