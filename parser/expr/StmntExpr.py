from typing import List, Optional
from .BaseExpr import BaseExpr, ExprType


class StmntExpr(BaseExpr):
    """GNU statement expression: ({ stmt; ...; last_expr; })

    The type of the statement expression is the type of the final expression
    statement inside the braces.  The final statement must be a SemiColonStmnt.
    """

    expr_id = ExprType.STMNT_EXPR

    def __init__(self, stmnt: Optional["CurlyStmnt"] = None):
        self.stmnt = stmnt

    def init_temps(self, main_temps):
        # Inner statement expressions own their own temporaries; don't propagate.
        return super(StmntExpr, self).init_temps(main_temps)

    def pretty_repr(self, pretty_repr_ctx=None):
        return (
            [self.__class__.__name__, "("]
            + get_pretty_repr(self.stmnt, pretty_repr_ctx)
            + [")"]
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        """Parse the ``{ ... }`` body of a statement expression.

        On entry ``tokens[c].str == '{'`` and ``end`` points at (or just past)
        the closing ``)``.  Returns ``c`` positioned at the closing ``)``.
        """
        stmnt = CurlyStmnt()
        c = stmnt.build(tokens, c, end, context)
        self.stmnt = stmnt
        # Derive the result type from the last expression statement.
        if stmnt.stmnts:
            last = stmnt.stmnts[-1]
            if isinstance(last, SemiColonStmnt) and last.expr is not None:
                self.t_anot = last.expr.t_anot
        if self.t_anot is None:
            self.t_anot = void_t
        return c


from ...PrettyRepr import get_pretty_repr
from ..stmnt.CurlyStmnt import CurlyStmnt
from ..stmnt.SemiColonStmnt import SemiColonStmnt
from ..type.CompileContext import CompileContext
from ..type.PrimitiveType import void_t
from ...lexer.lexer import Token
