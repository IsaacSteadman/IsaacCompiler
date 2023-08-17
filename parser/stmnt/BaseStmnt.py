from enum import Enum
from typing import Optional
from ...PrettyRepr import PrettyRepr


class StmntType(Enum):
    CURLY_STMNT = 0
    IF = 1
    WHILE = 2
    FOR = 3
    RTN = 4
    BRK = 5
    CONTINUE = 6
    NAMESPACE = 7
    TYPEDEF = 8
    DECL = 9
    ASM = 10
    SEMI_COLON = 11  # always at end ('expr;' expression)


STMNT_KEY_TO_ID = {
    "{": StmntType.CURLY_STMNT,
    "if": StmntType.IF,
    "while": StmntType.WHILE,
    "for": StmntType.FOR,
    "return": StmntType.RTN,
    "break": StmntType.BRK,
    "continue": StmntType.CONTINUE,
    "namespace": StmntType.NAMESPACE,
    "typedef": StmntType.TYPEDEF,
    "<DECL_STMNT>": StmntType.DECL,
    "asm": StmntType.ASM,
}


class BaseStmnt(PrettyRepr):
    stmnt_type: Optional[StmntType] = None
    position = (-1, -1)
