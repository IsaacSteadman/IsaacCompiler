from typing import Optional, List
from .BaseStmnt import BaseStmnt, StmntType


class SemiColonStmnt(BaseStmnt):
    stmnt_type = StmntType.SEMI_COLON
    # init-args added for __repr__

    def __init__(self, expr: Optional["BaseExpr"] = None):
        self.expr = expr
        if self.expr is not None:
            self.expr.init_temps(None)

    def pretty_repr(self, pretty_repr_ctx=None):
        return (
            [self.__class__.__name__, "("]
            + get_pretty_repr(self.expr, pretty_repr_ctx)
            + [")"]
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        self.expr, c = get_expr(tokens, c, ";", end, context)
        if self.expr is not None:
            self.expr.init_temps(None)
        else:
            print("WARN: expr is None: " + get_user_str_parse_pos(tokens, c))
        c += 1
        return c


from ..expr.get_expr import get_expr
from ..expr.BaseExpr import BaseExpr
from ..get_user_str_parse_pos import get_user_str_parse_pos
from ...PrettyRepr import get_pretty_repr
from ..type.types import CompileContext
from ...lexer.lexer import Token
