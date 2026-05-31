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
        """Parse {expr, ...} with optional designated-initialiser syntax.

        Struct designator  :  .field_name = expr
        Array designator   :  [const_int] = expr
        """
        start = c
        lvl = 1
        c += 1  # skip '{'
        # Find the matching '}'
        while c < end and lvl > 0:
            s = tokens[c].str
            if s in OPEN_GROUPS:
                lvl += 1
            elif s in CLOSE_GROUPS:
                lvl -= 1
            c += 1
        end_t = c  # one past '}'
        end_p = end_t - 1  # index of '}'
        c = start + 1  # first token inside '{'
        lst_expr = []
        while c < end_p:
            # ── struct designated initialiser:  .field_name = expr ──────────
            if (
                tokens[c].str == "."
                and c + 2 < end_p
                and tokens[c + 1].type_id == TokenType.NAME
                and tokens[c + 2].str == "="
            ):
                field_name = tokens[c + 1].str
                c += 3  # consume '.', name, '='
                expr, c = get_expr(tokens, c, ",", end_p, context)
                lst_expr.append(
                    DesigInitExpr(DesigInitExpr.KIND_FIELD, field_name, expr)
                )

            # ── array designated initialiser:  [const_int] = expr ───────────
            elif tokens[c].str == "[":
                # Locate the matching ']' at the same brace level
                blvl = 1
                bend = c + 1
                while bend < end_p and blvl > 0:
                    if tokens[bend].str in OPEN_GROUPS:
                        blvl += 1
                    elif tokens[bend].str in CLOSE_GROUPS:
                        blvl -= 1
                    bend += 1
                bend -= 1  # points to ']'
                if (
                    tokens[bend].str == "]"
                    and bend + 1 < end_p
                    and tokens[bend + 1].str == "="
                ):
                    # Parse the index as a constant expression
                    idx_expr, _ = get_expr(tokens, c + 1, "]", bend + 1, context)
                    assert (
                        isinstance(idx_expr, LiteralExpr)
                        and idx_expr.t_lit == LiteralExpr.LIT_INT
                    ), "Array designator index must be an integer constant"
                    index = idx_expr.l_val
                    c = bend + 2  # consume past ']' and '='
                    expr, c = get_expr(tokens, c, ",", end_p, context)
                    lst_expr.append(
                        DesigInitExpr(DesigInitExpr.KIND_INDEX, index, expr)
                    )
                else:
                    # Not a designator – ordinary expression beginning with '['
                    expr, c = get_expr(tokens, c, ",", end_p, context)
                    lst_expr.append(expr)

            # ── normal expression ────────────────────────────────────────────
            else:
                expr, c = get_expr(tokens, c, ",", end_p, context)
                lst_expr.append(expr)

            # Consume the ',' separator between elements
            if c < end_p and tokens[c].str == ",":
                c += 1

        self.lst_expr = lst_expr
        return end_t


from .DesigInitExpr import DesigInitExpr
from .LiteralExpr import LiteralExpr
from .get_expr import get_expr
from ...ParseConstants import CLOSE_GROUPS, OPEN_GROUPS
from ...PrettyRepr import get_pretty_repr
from ..type.types import CompileContext
from ...lexer.lexer import Token, TokenType
