from typing import List
from .BaseStmnt import BaseStmnt, StmntType


class GotoStmnt(BaseStmnt):
    stmnt_type = StmntType.GOTO

    def __init__(self, label_name: str = ""):
        self.label_name = label_name

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        del end, context
        c += 1  # consume 'goto'
        if tokens[c].type_id != TokenType.NAME:
            raise ParsingError(tokens, c, "Expected label name after 'goto'")
        self.label_name = tokens[c].str
        c += 1
        if tokens[c].str != ";":
            raise ParsingError(tokens, c, "Expected ';' after goto label name")
        c += 1
        return c


from ..ParsingError import ParsingError
from ...lexer.lexer import Token, TokenType
from ..type.CompileContext import CompileContext
