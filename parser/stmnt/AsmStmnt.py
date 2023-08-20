from typing import List, Optional
from .BaseStmnt import BaseStmnt, StmntType


class AsmStmnt(BaseStmnt):
    stmnt_type = StmntType.ASM

    def __init__(self, inner_asm: Optional[List[str]] = None):
        self.inner_asm = [] if inner_asm is None else inner_asm
        self.condition = None

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        assert tokens[c].str == "asm"
        c += 1
        if tokens[c].str == "(":
            self.condition = {}
            c += 1
            while tokens[c].str != ")":
                tok_key = tokens[c]
                tok_eq = tokens[c + 1]
                tok_val = tokens[c + 2]
                assert (
                    tok_key.type_id == TokenType.NAME
                    and tok_eq.str == "="
                    and LiteralExpr.is_literal_token(tok_val)
                ), "expected syntax <name>=<literal>\n got %r, %r, %r" % (
                    tok_key,
                    tok_eq,
                    tok_val,
                )
                self.condition[tok_key.str] = LiteralExpr.literal_to_value(tok_val)
                c += 3
                if tokens[c].str == ",":
                    c += 1
            c += 1
        print(self.condition)
        assert tokens[c].str == "{", tokens[c].str
        c += 1
        while c < end:
            assert tokens[c].type_id == TokenType.DBL_QUOTE, tokens[c]
            self.inner_asm.append(LiteralExpr.literal_to_value(tokens[c]))
            c += 1
            tok = tokens[c]
            if tok.str == ",":
                c += 1
                continue
            elif tok.str == "}":
                c += 1
                break
        assert tokens[c - 1].str == "}", tokens[c - 2 : c + 2]
        return c


from ...lexer.lexer import Token, TokenType
from ..expr.LiteralExpr import LiteralExpr
from ..type.types import CompileContext
