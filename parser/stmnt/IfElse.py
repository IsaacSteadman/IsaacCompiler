from typing import List, Union, Optional
from .BaseStmnt import BaseStmnt, StmntType


class IfElse(BaseStmnt):
    stmnt_type = StmntType.IF
    # init-args added for __repr__

    def __init__(
        self,
        cond: Optional["BaseExpr"] = None,
        stmnt: Optional[BaseStmnt] = None,
        else_stmnt: Optional[BaseStmnt] = None,
    ):
        self.cond = None if cond is None else get_bool_expr(cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        self.stmnt = stmnt
        self.else_stmnt = else_stmnt

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (self.cond, self.stmnt, self.else_stmnt), pretty_repr_ctx
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        c += 1
        if tokens[c].str != "(":
            raise ParsingError(tokens, c, "Expected '(' to open if-statement")
        c += 1
        self.cond, c = get_expr(tokens, c, ")", end, context)
        self.cond = get_bool_expr(self.cond)
        if self.cond is not None:
            self.cond.init_temps(None)
        if tokens[c].str != ")":
            raise ParsingError(
                tokens, c, "Expected ')' to delimit [condition] in while-loop"
            )
        c += 1
        self.stmnt, c = get_stmnt(tokens, c, end, context)
        if self.stmnt.stmnt_type == StmntType.DECL:
            raise ParsingError(
                tokens, c, "Cannot directly use 'DeclStmnt' as body for if statement"
            )
        if tokens[c].type_id == TokenType.NAME and tokens[c].str == "else":
            c += 1
            self.else_stmnt, c = get_stmnt(tokens, c, end, context)
            if self.else_stmnt.stmnt_type == StmntType.DECL:
                raise ParsingError(
                    tokens,
                    c,
                    "Cannot directly use 'DeclStmnt' as body for if statement",
                )
        return c


from ...PrettyRepr import get_pretty_repr
from ..type.types import CompileContext
from ..expr.BaseExpr import BaseExpr
from ...lexer.lexer import Token, TokenType
from ..ParsingError import ParsingError
from ..stmnt.get_stmnt import get_stmnt
from ..expr.get_bool_expr import get_bool_expr
from ..expr.get_expr import get_expr
