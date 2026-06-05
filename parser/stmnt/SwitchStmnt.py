"""
switch / case / default statement.

Grammar (simplified):
    switch ( expr ) {
        case const_expr : stmnt* ...
        default :         stmnt* ...
    }

The body is parsed into a flat list of *segments*.  Each segment is a tuple:

    (case_vals: List[Optional[int]], stmnts: List[BaseStmnt])

where ``case_vals`` is the ordered list of labels that precede the body
statements for this segment:

* ``int``  — a ``case N:`` label (N evaluated at parse time)
* ``None`` — a ``default:`` label

Fall-through is modelled naturally: segments are emitted sequentially in the
order they appear; the absence of ``break`` at the end of a segment causes
execution to continue into the next segment's body.
"""

from typing import List, Optional, Tuple
from .BaseStmnt import BaseStmnt, StmntType


class SwitchStmnt(BaseStmnt):
    stmnt_type = StmntType.SWITCH

    def __init__(
        self,
        expr: Optional["BaseExpr"] = None,
        segments: Optional[List[Tuple[List[Optional[int]], List[BaseStmnt]]]] = None,
    ):
        self.expr = expr
        self.segments: List[Tuple[List[Optional[int]], List[BaseStmnt]]] = (
            [] if segments is None else segments
        )
        self.context = None  # CompileContext scope for the body

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (self.expr, self.segments), pretty_repr_ctx
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        c += 1  # consume 'switch'
        if tokens[c].str != "(":
            raise ParsingError(tokens, c, "Expected '(' after 'switch'")
        c += 1
        self.expr, c = get_expr(tokens, c, ")", end, context)
        if self.expr is not None:
            self.expr.init_temps(None)
        if tokens[c].str != ")":
            raise ParsingError(tokens, c, "Expected ')' after switch expression")
        c += 1
        if tokens[c].str != "{":
            raise ParsingError(tokens, c, "Expected '{' to open switch body")

        self.context = context.new_scope(LocalScope("switch"))
        c += 1  # consume '{'

        self.segments = []
        current_labels: List[Optional[int]] = []
        current_stmnts: List[BaseStmnt] = []

        while c < end and tokens[c].str != "}":
            if tokens[c].type_id == TokenType.NAME and tokens[c].str == "case":
                # Commit any pending statements as a new segment.
                if current_stmnts:
                    self.segments.append((current_labels, current_stmnts))
                    current_labels = []
                    current_stmnts = []
                c += 1  # consume 'case'
                # Find the ':' that terminates the case constant expression.
                # Track bracket depth to avoid confusing a ':' inside a ternary.
                expr_start = c
                depth = 0
                while c < end:
                    s = tokens[c].str
                    if s in ("(", "{", "["):
                        depth += 1
                    elif s in (")", "}", "]"):
                        depth -= 1
                    elif s == ":" and depth == 0:
                        break
                    c += 1
                expr_end = c
                case_val = _try_eval_const(tokens, expr_start, expr_end, context)
                if case_val is None:
                    raise ParsingError(
                        tokens,
                        expr_start,
                        "case expression is not a compile-time integer constant",
                    )
                if tokens[c].str != ":":
                    raise ParsingError(tokens, c, "Expected ':' after case expression")
                c += 1  # consume ':'
                current_labels.append(int(case_val))
            elif tokens[c].type_id == TokenType.NAME and tokens[c].str == "default":
                # Commit any pending statements as a new segment.
                if current_stmnts:
                    self.segments.append((current_labels, current_stmnts))
                    current_labels = []
                    current_stmnts = []
                c += 1  # consume 'default'
                if tokens[c].str != ":":
                    raise ParsingError(tokens, c, "Expected ':' after 'default'")
                c += 1  # consume ':'
                current_labels.append(None)  # None signals the default label
            else:
                stmnt, c = get_stmnt(tokens, c, end, self.context)
                current_stmnts.append(stmnt)

        # Commit any trailing items.
        if current_labels or current_stmnts:
            self.segments.append((current_labels, current_stmnts))

        if tokens[c].str != "}":
            raise ParsingError(tokens, c, "Expected '}' to close switch body")
        c += 1  # consume '}'
        return c


# ---------------------------------------------------------------------------
# Imports (bottom to avoid circular-import issues, matching project style)
# ---------------------------------------------------------------------------
from ...PrettyRepr import get_pretty_repr
from ..ParsingError import ParsingError
from ..expr.BaseExpr import BaseExpr
from ..expr.get_expr import get_expr
from ..stmnt.get_stmnt import get_stmnt
from ..type.CompileContext import CompileContext
from ..type.LocalScope import LocalScope
from ...lexer.lexer import Token, TokenType
from .StaticAssertStmnt import _try_eval_const
