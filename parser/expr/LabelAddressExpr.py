from typing import List

from .BaseExpr import BaseExpr, ExprType
from ..ParsingError import ParsingError
from ..type.PrimitiveType import void_t
from ..type.QualType import QualType
from ...lexer.lexer import Token, TokenType


class LabelAddressExpr(BaseExpr):
    expr_id = ExprType.LABEL_ADDRESS

    def __init__(self, label_name: str = ""):
        self.label_name = label_name
        self.t_anot = QualType(QualType.QUAL_PTR, void_t)

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        del context
        if c >= end or tokens[c].str != "&&":
            raise ParsingError(tokens, c, "Expected '&&' for label address")
        c += 1
        if c >= end or tokens[c].type_id != TokenType.NAME:
            raise ParsingError(tokens, c, "Expected label name after '&&'")
        self.label_name = tokens[c].str
        c += 1
        return c


from ..type.CompileContext import CompileContext
