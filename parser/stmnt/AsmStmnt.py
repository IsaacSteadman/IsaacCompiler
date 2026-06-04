from typing import List, Optional, Set, Tuple
from .BaseStmnt import BaseStmnt, StmntType


class AsmStmnt(BaseStmnt):
    stmnt_type = StmntType.ASM
    _GNU_QUALIFIERS = {"goto", "inline", "volatile", "__inline__", "__volatile__"}

    def __init__(self, inner_asm: Optional[List[str]] = None):
        self.inner_asm = [] if inner_asm is None else inner_asm
        self.condition = None
        self.qualifiers: Set[str] = set()
        self.is_goto = False
        self.goto_labels: List[str] = []
        self.goto_label_operand_base = 0

    @staticmethod
    def _skip_gnu_section(
        tokens: List["Token"], c: int, end: int, section_name: str
    ) -> Tuple[int, int]:
        """Skip one GNU asm operand section and count its top-level entries."""
        closing = {"(": ")", "[": "]", "{": "}"}
        stack = []
        entry_count = 0
        entry_has_tokens = False
        while c < end:
            tok = tokens[c]
            if not stack and tok.str == ":":
                if entry_has_tokens:
                    entry_count += 1
                return c, entry_count
            if not stack and tok.str == ",":
                if not entry_has_tokens:
                    raise ParsingError(
                        tokens, c, "Expected an operand before ',' in %s" % section_name
                    )
                entry_count += 1
                entry_has_tokens = False
                c += 1
                continue
            if tok.str in closing:
                stack.append(closing[tok.str])
            elif tok.str in closing.values():
                if not stack or stack[-1] != tok.str:
                    raise ParsingError(
                        tokens,
                        c,
                        "Mismatched delimiter in asm goto %s" % section_name,
                    )
                stack.pop()
            entry_has_tokens = True
            c += 1
        raise ParsingError(
            tokens, c, "Expected ':' after asm goto %s" % section_name
        )

    def _build_gnu_goto(
        self, tokens: List["Token"], c: int, end: int
    ) -> int:
        if c >= end or tokens[c].str != "(":
            raise ParsingError(tokens, c, "Expected '(' after asm goto")
        c += 1

        template_parts = []
        while c < end and tokens[c].type_id == TokenType.DBL_QUOTE:
            template_parts.append(LiteralExpr.literal_to_value(tokens[c]))
            c += 1
        if not template_parts:
            raise ParsingError(tokens, c, "Expected string template in asm goto")
        self.inner_asm = ["".join(template_parts)]

        operand_count = 0
        for section_name in ("output operands", "input operands", "clobber list"):
            if c >= end or tokens[c].str != ":":
                raise ParsingError(
                    tokens, c, "Expected ':' before asm goto %s" % section_name
                )
            c, count = self._skip_gnu_section(tokens, c + 1, end, section_name)
            if section_name != "clobber list":
                operand_count += count

        self.goto_label_operand_base = operand_count
        if c >= end or tokens[c].str != ":":
            raise ParsingError(tokens, c, "Expected ':' before asm goto label list")
        c += 1
        expect_label = True
        while c < end and tokens[c].str != ")":
            if expect_label:
                if tokens[c].type_id != TokenType.NAME:
                    raise ParsingError(tokens, c, "Expected C label in asm goto label list")
                self.goto_labels.append(tokens[c].str)
                expect_label = False
            else:
                if tokens[c].str != ",":
                    raise ParsingError(tokens, c, "Expected ',' between asm goto labels")
                expect_label = True
            c += 1
        if not self.goto_labels:
            raise ParsingError(tokens, c, "asm goto requires at least one C label")
        if expect_label:
            raise ParsingError(tokens, c, "Expected C label after ',' in asm goto")
        if c >= end or tokens[c].str != ")":
            raise ParsingError(tokens, c, "Expected ')' after asm goto label list")
        c += 1
        if c >= end or tokens[c].str != ";":
            raise ParsingError(tokens, c, "Expected ';' after asm goto")
        return c + 1

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        del context
        assert tokens[c].str == "asm"
        c += 1
        while (
            c < end
            and tokens[c].type_id == TokenType.NAME
            and tokens[c].str in self._GNU_QUALIFIERS
        ):
            qualifier = tokens[c].str
            self.qualifiers.add(qualifier)
            self.is_goto = self.is_goto or qualifier == "goto"
            c += 1
        if self.is_goto:
            return self._build_gnu_goto(tokens, c, end)
        if self.qualifiers:
            raise ParsingError(
                tokens, c, "GNU asm qualifiers are currently supported only with asm goto"
            )
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
from ..ParsingError import ParsingError
from ..type.types import CompileContext
