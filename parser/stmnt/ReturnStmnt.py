from typing import List, Optional
from .BaseStmnt import BaseStmnt, StmntType


class ReturnStmnt(BaseStmnt):
    stmnt_type = StmntType.RTN

    def __init__(self, expr=None):
        """
        :param BaseExpr|None expr:
        """
        self.expr = expr
        if self.expr is not None:
            self.expr.init_temps(None)

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.expr) + [")"]

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        c += 1
        self.expr, c = get_expr(tokens, c, ";", end, context)
        if self.expr is not None:
            self.expr.init_temps(None)
        if tokens[c].str != ";":
            raise ParsingError(
                tokens, c, "Expected ';' to terminate 'return' Statement"
            )
        c += 1
        return c


from ..ParsingError import ParsingError
from ..type.types import CompileContext
from ...lexer.lexer import Token
from ...PrettyRepr import get_pretty_repr
from ..expr.get_expr import get_expr
