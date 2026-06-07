from typing import List, Optional
from .BaseStmnt import BaseStmnt, StmntType


class GotoStmnt(BaseStmnt):
    stmnt_type = StmntType.GOTO

    def __init__(
        self,
        label_name: str = "",
        indirect_expr: Optional["BaseExpr"] = None,
    ):
        self.label_name = label_name
        self.indirect_expr = indirect_expr
        if self.indirect_expr is not None:
            self.indirect_expr.init_temps(None)

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        c += 1  # consume 'goto'
        if tokens[c].str == "*":
            self.indirect_expr, c = get_expr(tokens, c + 1, ";", end, context)
            if self.indirect_expr is None:
                raise ParsingError(tokens, c, "Expected expression after 'goto *'")
            if self.indirect_expr.t_anot is None:
                raise ParsingError(tokens, c, "Indirect goto target must be typed")
            target_type = get_value_type(self.indirect_expr.t_anot)
            if (
                not isinstance(target_type, QualType)
                or target_type.qual_id != QualType.QUAL_PTR
            ):
                raise ParsingError(tokens, c, "Indirect goto target must be a pointer")
            self.indirect_expr.init_temps(None)
            if c >= end or tokens[c].str != ";":
                raise ParsingError(tokens, c, "Expected ';' after indirect goto")
            c += 1
            return c
        if tokens[c].type_id != TokenType.NAME:
            raise ParsingError(tokens, c, "Expected label name after 'goto'")
        self.label_name = tokens[c].str
        c += 1
        if tokens[c].str != ";":
            raise ParsingError(tokens, c, "Expected ';' after goto label name")
        c += 1
        return c


from ..ParsingError import ParsingError
from ..expr.BaseExpr import BaseExpr
from ..expr.get_expr import get_expr
from ...lexer.lexer import Token, TokenType
from ..type.CompileContext import CompileContext
from ..type.QualType import QualType
from ..type.qual_atomic_type_util import get_value_type
