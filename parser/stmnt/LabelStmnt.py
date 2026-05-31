from typing import List
from .BaseStmnt import BaseStmnt, StmntType


class LabelStmnt(BaseStmnt):
    stmnt_type = StmntType.LABEL

    def __init__(self, label_name: str = ""):
        self.label_name = label_name

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        del end, context
        self.label_name = tokens[c].str  # the identifier
        c += 1
        assert tokens[c].str == ":", "Expected ':' in label statement"
        c += 1  # consume ':'
        return c


from ...lexer.lexer import Token
from ..type.types import CompileContext
