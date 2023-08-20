from typing import List, Optional
from .BaseExpr import BaseExpr, ExprType


class CurlyExpr(BaseExpr):
    expr_id = ExprType.CURLY

    def __init__(self, lst_expr: Optional[List["BaseExpr"]] = None):
        self.lst_expr = lst_expr

    def init_temps(self, main_temps):
        main_temps = super(CurlyExpr, self).init_temps(main_temps)
        assert self.lst_expr is not None
        for expr in self.lst_expr:
            main_temps = expr.init_temps(main_temps)
        return main_temps

    def pretty_repr(self, pretty_repr_ctx=None):
        return (
            [self.__class__.__name__, "("]
            + get_pretty_repr(self.lst_expr, pretty_repr_ctx)
            + [")"]
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        lvl = 1
        start = c
        c += 1
        comma_count = 0
        while c < end and lvl > 0:
            s = tokens[c].str
            if s in OPEN_GROUPS:
                lvl += 1
            elif s in CLOSE_GROUPS:
                lvl -= 1
            elif s == ",":
                comma_count += 1
            c += 1
        self.lst_expr = [None] * (comma_count + 1)
        n_expr = 0
        end_t = c
        end_p = end_t - 1
        c = start + 1
        while c < end_p and n_expr < len(self.lst_expr):
            self.lst_expr[n_expr], c = get_expr(tokens, c, ",", end_p, context)
            n_expr += 1
            c += 1
        for i in range(c - 5, c + 5):
            print("%03u: %s" % (i, tokens[i].str))
        assert c == end_t, "You need to verify this code, c = %u, end_t = %u" % (
            c,
            end_t,
        )
        return c


from .get_expr import get_expr
from ...ParseConstants import CLOSE_GROUPS, OPEN_GROUPS
from ...PrettyRepr import get_pretty_repr
from ..type.types import CompileContext
from ...lexer.lexer import Token
