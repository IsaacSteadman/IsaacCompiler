from typing import Optional, List
from .BaseStmnt import BaseStmnt, StmntType


class ForLoop(BaseStmnt):
    stmnt_type = StmntType.FOR
    # init-args added for __repr__

    def __init__(
        self,
        init: Optional[BaseStmnt] = None,
        cond: Optional["BaseExpr"] = None,
        incr: Optional["BaseExpr"] = None,
        stmnt: Optional[BaseStmnt] = None,
    ):
        self.init = init
        self.cond = None if cond is None else get_bool_expr(cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        self.incr = incr
        if self.incr is not None:
            self.incr.init_temps(None)
        self.stmnt = stmnt
        self.context = None

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (self.init, self.cond, self.incr, self.stmnt), pretty_repr_ctx
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        c += 1
        if tokens[c].str != "(":
            raise ParsingError(tokens, c, "Expected '(' to open for-loop")
        self.context = context.new_scope(LocalScope())
        c += 1
        # TODO: restrict self.init to be only semicolon, while still allowing 'int c = 0;'
        self.init, c = get_stmnt(tokens, c, end, self.context)
        if tokens[c - 1].str != ";":
            raise ParsingError(tokens, c, "Expected ';' to delimit [init] in for-loop")
        # c += 1 # not needed
        cond, c = get_expr(tokens, c, ";", end, self.context)
        if cond is None:
            cond = LiteralExpr(LiteralExpr.LIT_INT, "1")
        self.cond = get_bool_expr(cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        if tokens[c].str != ";":
            raise ParsingError(
                tokens, c, "Expected ';' to delimit [condition] in for-loop"
            )
        c += 1
        self.incr, c = get_expr(tokens, c, ")", end, self.context)
        if self.incr is not None:
            self.incr.init_temps(None)
        if tokens[c].str != ")":
            raise ParsingError(
                tokens, c, "Expected ')' to delimit [increment] in for-loop"
            )
        c += 1
        self.stmnt, c = get_stmnt(tokens, c, end, self.context)
        if self.stmnt.stmnt_type not in {StmntType.SEMI_COLON, StmntType.CURLY_STMNT}:
            cls_name = self.stmnt.__class__.__name__
            raise ParsingError(
                tokens, c, "Cannot directly use '%s' as body for for-loop" % cls_name
            )
        return c


from ..ParsingError import ParsingError
from ...PrettyRepr import get_pretty_repr
from ..expr.BaseExpr import BaseExpr
from ..expr.LiteralExpr import LiteralExpr
from ..expr.get_bool_expr import get_bool_expr
from ..expr.get_expr import get_expr
from ..stmnt.BaseStmnt import BaseStmnt, StmntType
from ..stmnt.get_stmnt import get_stmnt
from ..type.types import CompileContext, LocalScope
from ...lexer.lexer import Token
