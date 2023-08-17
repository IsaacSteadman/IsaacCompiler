from typing import List, Optional
from .BaseStmnt import BaseStmnt
from .constants import StmntType


class WhileLoop(BaseStmnt):
    stmnt_type = StmntType.WHILE
    # init-args added for __repr__

    def __init__(self, cond: Optional["BaseExpr"] = None, stmnt: Optional[BaseStmnt] = None):
        self.cond = None if cond is None else get_bool_expr(cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        self.stmnt = stmnt

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.cond, self.stmnt))

    def build(self, tokens: List["Token"], c: int, end: int, context: "CompileContext") -> int:
        c += 1
        if tokens[c].str != "(":
            raise ParsingError(tokens, c, "Expected '(' to open while-loop")
        c += 1
        self.cond, c = get_expr(tokens, c, ")", end, context)
        self.cond = get_bool_expr(self.cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        if tokens[c].str != ")":
            raise ParsingError(tokens, c, "Expected ')' to delimit [condition] in while-loop")
        c += 1
        self.stmnt, c = get_stmnt(tokens, c, end, context)
        if self.stmnt.stmnt_type not in {StmntType.SEMI_COLON, StmntType.CURLY_STMNT}:
            cls_name = self.stmnt.__class__.__name__
            raise ParsingError(tokens, c, "Cannot directly use '%s' as body for while-loop" % cls_name)
        return c


from .get_stmnt import get_stmnt
from ..ParsingError import ParsingError
from ...PrettyRepr import get_pretty_repr
from ..context.CompileContext import CompileContext
from ..expr.BaseExpr import BaseExpr
from ..expr.get_bool_expr import get_bool_expr
from ..expr.get_expr import get_expr
from ...lexer.lexer import Token
