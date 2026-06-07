"""
_Static_assert(const_expr [, string_literal]) statement.

Evaluates `const_expr` as a compile-time integer constant.  If the result
is zero the compilation is aborted with the optional message; otherwise the
statement is a no-op.

Supported constant expressions:
  - Integer literals (decimal / hex / octal / binary)
  - sizeof(type)
  - Binary: + - * / % == != < > <= >= << >> & ^ | && ||
  - Unary:  ! ~ - +
  - Parentheses
"""

from typing import List, Optional
from .BaseStmnt import BaseStmnt, StmntType


class StaticAssertStmnt(BaseStmnt):
    stmnt_type = StmntType.STATIC_ASSERT

    def __init__(self):
        self.cond_value: Optional[int] = None  # None = could not evaluate
        self.message: Optional[str] = None

    def pretty_repr(self, pretty_repr_ctx=None):
        return [
            "StaticAssertStmnt(",
            str(self.cond_value),
            ", ",
            repr(self.message),
            ")",
        ]

    def build(
        self,
        tokens: List["Token"],
        c: int,
        end: int,
        context: "CompileContext",
    ) -> int:
        # tokens[c].str == '_Static_assert'
        c += 1
        if tokens[c].str != "(":
            raise ParsingError(tokens, c, "expected '(' after '_Static_assert'")
        c += 1  # skip '('

        # Collect argument tokens up to the matching ')'.
        depth = 1
        arg_start = c
        while c < end and depth > 0:
            s = tokens[c].str
            if s in ("(", "{", "["):
                depth += 1
            elif s in (")", "}", "]"):
                depth -= 1
            if depth > 0:
                c += 1
            else:
                break  # c is now pointing at the closing ')'

        # tokens[arg_start : c] are all argument tokens (everything inside the outer parens).
        # Split on ',' at depth 0 to separate condition from message.
        cond_end = c  # default: no comma found
        msg_start: Optional[int] = None
        d2 = 0
        for k in range(arg_start, c):
            s = tokens[k].str
            if s in ("(", "{", "["):
                d2 += 1
            elif s in (")", "}", "]"):
                d2 -= 1
            elif s == "," and d2 == 0:
                cond_end = k
                msg_start = k + 1
                break

        # Evaluate the condition.
        self.cond_value = _try_eval_const(tokens, arg_start, cond_end, context)

        # Extract the message string (optional).
        if msg_start is not None:
            # Find a string literal token in the message range.
            for k in range(msg_start, c):
                if tokens[k].type_id == TokenType.DBL_QUOTE:
                    raw = tokens[k].str
                    # Strip surrounding "..." quotes.
                    if raw.startswith('"') and raw.endswith('"'):
                        self.message = raw[1:-1]
                    break

        if tokens[c].str != ")":
            raise ParsingError(tokens, c, "expected ')' to close '_Static_assert'")
        c += 1  # skip ')'

        if tokens[c].str != ";":
            raise ParsingError(tokens, c, "expected ';' after '_Static_assert'")
        c += 1  # skip ';'

        # Assert at parse time.
        if self.cond_value is not None and self.cond_value == 0:
            msg = self.message if self.message else "_Static_assert failed"
            raise ParsingError(tokens, arg_start, f"static assertion failed: {msg}")

        if self.cond_value is None:
            import sys

            print(
                "warning: _Static_assert: could not evaluate constant expression "
                "— assertion skipped",
                file=sys.stderr,
            )

        return c


# ---------------------------------------------------------------------------
# Compile-time constant expression evaluator (token-level)
# ---------------------------------------------------------------------------

# Operator precedence levels, lowest first.  Each tuple contains operators of
# the same precedence.  Longer operators must come before shorter ones that
# are prefixes of them (e.g. '<=' before '<').
_BINOP_LEVELS = [
    ("||",),
    ("&&",),
    ("|",),
    ("^",),
    ("&",),
    ("==", "!="),
    ("<=", ">=", "<", ">"),
    ("<<", ">>"),
    ("+", "-"),
    ("*", "/", "%"),
]


def _try_eval_const(
    tokens: List["Token"],
    start: int,
    end: int,
    context: "CompileContext",
) -> Optional[int]:
    """Return the integer value of tokens[start:end] or None."""
    try:
        return _eval_tokens(tokens, start, end, context)
    except Exception:
        return None


def _find_call_paren_end(tokens: List["Token"], c: int, end: int) -> int:
    lvl = 1
    while c < end:
        if tokens[c].str in ("(", "[", "{"):
            lvl += 1
        elif tokens[c].str in (")", "]", "}"):
            lvl -= 1
            if lvl == 0:
                return c
        c += 1
    raise ValueError("expected ')' to terminate builtin call")


def _find_top_level_call_comma(
    tokens: List["Token"], c: int, end: int
) -> Optional[int]:
    lvl = 1
    while c < end:
        if tokens[c].str in ("(", "[", "{"):
            lvl += 1
        elif tokens[c].str in (")", "]", "}"):
            lvl -= 1
        elif tokens[c].str == "," and lvl == 1:
            return c
        c += 1
    return None


def _top_level_call_commas(tokens: List["Token"], c: int, end: int) -> List[int]:
    commas = []
    lvl = 1
    ternary_lvl = 0
    while c < end:
        if tokens[c].str in ("(", "[", "{"):
            lvl += 1
        elif tokens[c].str in (")", "]", "}"):
            lvl -= 1
        elif tokens[c].str == "?" and lvl == 1:
            ternary_lvl += 1
        elif tokens[c].str == ":" and lvl == 1 and ternary_lvl > 0:
            ternary_lvl -= 1
        elif tokens[c].str == "," and lvl == 1 and ternary_lvl == 0:
            commas.append(c)
        c += 1
    return commas


def _find_top_level_colon(tokens: List["Token"], c: int, end: int) -> Optional[int]:
    lvl = 0
    while c < end:
        s = tokens[c].str
        if s in ("(", "[", "{"):
            lvl += 1
        elif s in (")", "]", "}"):
            lvl -= 1
        elif s == ":" and lvl == 0:
            return c
        c += 1
    return None


def _find_top_level_ternary(tokens: List["Token"], start: int, end: int):
    lvl = 0
    q_pos = None
    nested = 0
    for k in range(start, end):
        s = tokens[k].str
        if s in ("(", "[", "{"):
            lvl += 1
        elif s in (")", "]", "}"):
            lvl -= 1
        elif lvl == 0 and s == "?":
            if q_pos is None:
                q_pos = k
            else:
                nested += 1
        elif lvl == 0 and s == ":" and q_pos is not None:
            if nested == 0:
                return q_pos, k
            nested -= 1
    return None


def _find_next_generic_assoc_comma(tokens: List["Token"], c: int, end: int) -> int:
    lvl = 0
    ternary_lvl = 0
    while c < end:
        s = tokens[c].str
        if s in ("(", "[", "{"):
            lvl += 1
        elif s in (")", "]", "}"):
            lvl -= 1
        elif s == "?" and lvl == 0:
            ternary_lvl += 1
        elif s == ":" and lvl == 0 and ternary_lvl > 0:
            ternary_lvl -= 1
        elif s == "," and lvl == 0 and ternary_lvl == 0:
            return c
        c += 1
    return end


def _consume_abstract_decl_suffixes(
    tokens: List["Token"],
    c: int,
    end: int,
    context: "CompileContext",
    typ,
):
    while c < end and tokens[c].str == "[":
        c += 1
        ext_inf = None
        if c >= end:
            raise ValueError("expected closing ']' in abstract declarator")
        if tokens[c].str != "]":
            depth = 1
            bound_start = c
            while c < end:
                if tokens[c].str in ("(", "[", "{"):
                    depth += 1
                elif tokens[c].str in (")", "]", "}"):
                    depth -= 1
                    if depth == 0:
                        break
                c += 1
            if c >= end or tokens[c].str != "]":
                raise ValueError("expected closing ']' in abstract declarator")
            ext_inf = int(_eval_tokens(tokens, bound_start, c, context))
        if tokens[c].str != "]":
            raise ValueError("expected closing ']' in abstract declarator")
        c += 1
        typ = QualType(QualType.QUAL_ARR, typ, ext_inf)
    return typ, c


def _parse_types_compatible_arg(
    tokens: List["Token"], start: int, end: int, context: "CompileContext"
):
    type_decl, type_c = proc_typed_decl(tokens, start, end, context)
    if type_decl is not None and type_c > start:
        type_decl.typ, type_c = _consume_abstract_decl_suffixes(
            tokens, type_c, end, context, type_decl.typ
        )
    if (
        type_decl is None
        or type_c != end
        or getattr(type_decl, "name", None) is not None
    ):
        raise ValueError("argument must be a type")
    return type_decl.typ


def _get_generic_control_type(tokens, start: int, end: int, context: "CompileContext"):
    from ..expr.get_expr import get_expr

    expr, expr_c = get_expr(tokens, start, None, end, context)
    if expr is None or expr_c != end or expr.t_anot is None:
        raise ValueError("_Generic controlling expression has no type")
    control_type = get_value_type(expr.t_anot)
    if isinstance(control_type, QualType):
        if control_type.qual_id == QualType.QUAL_ARR:
            return QualType(QualType.QUAL_PTR, control_type.tgt_type)
        if control_type.qual_id == QualType.QUAL_FN:
            return QualType(QualType.QUAL_PTR, control_type)
    return control_type


def _eval_generic_tokens(
    tokens: List["Token"],
    start: int,
    end: int,
    context: "CompileContext",
) -> int:
    paren_end = _find_call_paren_end(tokens, start + 2, end)
    if paren_end != end - 1:
        raise ValueError("_Generic must occupy the whole expression")
    comma_pos = _find_top_level_call_comma(tokens, start + 2, paren_end)
    if comma_pos is None:
        raise ValueError("_Generic expects a controlling expression")
    control_type = _get_generic_control_type(tokens, start + 2, comma_pos, context)

    c = comma_pos + 1
    default_range = None
    selected_range = None
    while c < paren_end:
        assoc_end = _find_next_generic_assoc_comma(tokens, c, paren_end)
        if c == assoc_end:
            raise ValueError("expected _Generic association")
        colon_pos = _find_top_level_colon(tokens, c, assoc_end)
        if colon_pos is None:
            raise ValueError("expected ':' in _Generic association")
        expr_start = colon_pos + 1
        if expr_start >= assoc_end:
            raise ValueError("expected _Generic result expression")

        if tokens[c].str == "default" and c + 1 == colon_pos:
            if default_range is not None:
                raise ValueError("_Generic has more than one default")
            default_range = (expr_start, assoc_end)
        else:
            assoc_type = _parse_types_compatible_arg(tokens, c, colon_pos, context)
            if compare_no_cvr(control_type, assoc_type):
                if selected_range is not None:
                    raise ValueError(
                        "_Generic has multiple associations compatible with "
                        "the controlling expression"
                    )
                selected_range = (expr_start, assoc_end)

        c = assoc_end + 1

    branch_range = selected_range if selected_range is not None else default_range
    if branch_range is None:
        raise ValueError("no _Generic association matches the controlling type")
    return _eval_tokens(tokens, branch_range[0], branch_range[1], context)


def _eval_tokens(
    tokens: List["Token"],
    start: int,
    end: int,
    context: "CompileContext",
) -> int:
    """Recursively evaluate tokens[start:end] as a compile-time integer."""
    # Skip trailing/leading whitespace (no-op: tokens have no whitespace).
    while start < end and tokens[start].str in ("", " "):
        start += 1
    while end > start and tokens[end - 1].str in ("", " "):
        end -= 1

    if start >= end:
        raise ValueError("empty expression")

    ternary = _find_top_level_ternary(tokens, start, end)
    if ternary is not None:
        q_pos, colon_pos = ternary
        cond = _eval_tokens(tokens, start, q_pos, context)
        if cond:
            return _eval_tokens(tokens, q_pos + 1, colon_pos, context)
        return _eval_tokens(tokens, colon_pos + 1, end, context)

    n = end - start

    # --- Single token ---
    if n == 1:
        tok = tokens[start]
        if tok.type_id in (
            TokenType.DEC_INT,
            TokenType.HEX_INT,
            TokenType.OCT_INT,
            TokenType.BIN_INT,
        ):
            return LiteralExpr.literal_to_value(tok)
        if tok.type_id == TokenType.NAME and tok.str in ("true", "1"):
            return 1
        if tok.type_id == TokenType.NAME and tok.str in ("false", "0"):
            return 0
        raise ValueError(f"cannot evaluate: {tok.str!r}")

    # --- sizeof(type) ---
    if tokens[start].str == "sizeof" and tokens[start + 1].str == "(":
        depth = 0
        j = start + 1
        while j < end:
            if tokens[j].str in ("(", "[", "{"):
                depth += 1
            elif tokens[j].str in (")", "]", "}"):
                depth -= 1
                if depth == 0:
                    break
            j += 1
        inner_start = start + 2
        inner_end = j  # tokens[inner_start:inner_end] are inside sizeof(...)
        try:
            type_decl, _ = proc_typed_decl(tokens, inner_start, inner_end, context)
            if type_decl is not None and hasattr(type_decl, "typ"):
                return size_of(type_decl.typ)
        except Exception:
            pass
        raise ValueError("sizeof argument is not a type")

    # --- __builtin_expect(expr, expected) / __builtin_expect_with_probability(...) ---
    if (
        tokens[start].str in {
            "__builtin_expect",
            "__builtin_expect_with_probability",
        }
        and start + 1 < end
        and tokens[start + 1].str == "("
    ):
        paren_end = _find_call_paren_end(tokens, start + 2, end)
        if paren_end != end - 1:
            raise ValueError("%s must occupy the whole expression" % tokens[start].str)
        comma_pos = _find_top_level_call_comma(tokens, start + 2, paren_end)
        if comma_pos is None:
            raise ValueError("%s expects arguments" % tokens[start].str)
        return _eval_tokens(tokens, start + 2, comma_pos, context)

    # --- __builtin_constant_p(expr) ---
    if (
        tokens[start].str == "__builtin_constant_p"
        and start + 1 < end
        and tokens[start + 1].str == "("
    ):
        paren_end = _find_call_paren_end(tokens, start + 2, end)
        if paren_end != end - 1:
            raise ValueError("__builtin_constant_p must occupy the whole expression")
        try:
            _eval_tokens(tokens, start + 2, paren_end, context)
        except Exception:
            return 0
        return 1

    # --- __builtin_choose_expr(const_expr, true_expr, false_expr) ---
    if (
        tokens[start].str == "__builtin_choose_expr"
        and start + 1 < end
        and tokens[start + 1].str == "("
    ):
        paren_end = _find_call_paren_end(tokens, start + 2, end)
        if paren_end != end - 1:
            raise ValueError("__builtin_choose_expr must occupy the whole expression")
        commas = _top_level_call_commas(tokens, start + 2, paren_end)
        if len(commas) != 2:
            raise ValueError("__builtin_choose_expr expects three arguments")
        cond = _eval_tokens(tokens, start + 2, commas[0], context)
        if cond:
            return _eval_tokens(tokens, commas[0] + 1, commas[1], context)
        return _eval_tokens(tokens, commas[1] + 1, paren_end, context)

    # --- __builtin_object_size / __builtin_dynamic_object_size ---
    if (
        tokens[start].str in {
            "__builtin_object_size",
            "__builtin_dynamic_object_size",
        }
        and start + 1 < end
        and tokens[start + 1].str == "("
    ):
        paren_end = _find_call_paren_end(tokens, start + 2, end)
        if paren_end != end - 1:
            raise ValueError("%s must occupy the whole expression" % tokens[start].str)
        return (1 << 64) - 1

    # --- __builtin_offsetof(type, member) ---
    if (
        tokens[start].str == "__builtin_offsetof"
        and start + 1 < end
        and tokens[start + 1].str == "("
    ):
        depth = 0
        j = start + 1
        while j < end:
            if tokens[j].str in ("(", "[", "{"):
                depth += 1
            elif tokens[j].str in (")", "]", "}"):
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j == end - 1:
            comma_pos = None
            depth = 0
            for k in range(start + 2, j):
                if tokens[k].str in ("(", "[", "{"):
                    depth += 1
                elif tokens[k].str in (")", "]", "}"):
                    depth -= 1
                elif tokens[k].str == "," and depth == 0:
                    comma_pos = k
                    break
            if comma_pos is None:
                raise ValueError("__builtin_offsetof expects two arguments")
            type_decl, type_c = proc_typed_decl(tokens, start + 2, comma_pos, context)
            if type_decl is None or type_c != comma_pos:
                raise ValueError("__builtin_offsetof first argument must be a type")
            if comma_pos + 1 >= j or tokens[comma_pos + 1].type_id != TokenType.NAME:
                raise ValueError(
                    "__builtin_offsetof second argument must be a member name"
                )
            if comma_pos + 2 != j:
                raise ValueError(
                    "__builtin_offsetof currently expects a single member name"
                )
            agg_type = get_value_type(type_decl.typ)
            if not isinstance(agg_type, (ClassType, StructType, UnionType)):
                raise ValueError(
                    "__builtin_offsetof first argument must name a struct, union, or class type"
                )
            return agg_type.offset_of(tokens[comma_pos + 1].str)

    # --- __builtin_types_compatible_p(type1, type2) ---
    if (
        tokens[start].str == "__builtin_types_compatible_p"
        and start + 1 < end
        and tokens[start + 1].str == "("
    ):
        paren_end = _find_call_paren_end(tokens, start + 2, end)
        if paren_end == end - 1:
            comma_pos = _find_top_level_call_comma(tokens, start + 2, paren_end)
            if comma_pos is None:
                raise ValueError("__builtin_types_compatible_p expects two arguments")
            lhs_type = _parse_types_compatible_arg(
                tokens, start + 2, comma_pos, context
            )
            rhs_type = _parse_types_compatible_arg(
                tokens, comma_pos + 1, paren_end, context
            )
            return 1 if compare_no_cvr(lhs_type, rhs_type) else 0

    # --- _Generic(controlling_expr, type: expr, ..., default: expr) ---
    if (
        tokens[start].str == "_Generic"
        and start + 1 < end
        and tokens[start + 1].str == "("
    ):
        return _eval_generic_tokens(tokens, start, end, context)

    # --- Outer parentheses: ( expr ) ---
    if tokens[start].str == "(":
        # Check if the entire range is wrapped in matching parens.
        depth = 0
        for k in range(start, end):
            s = tokens[k].str
            if s in ("(", "[", "{"):
                depth += 1
            elif s in (")", "]", "}"):
                depth -= 1
            if depth == 0 and k < end - 1:
                # Opening paren closed before the last token — not fully wrapped.
                break
        else:
            # Loop completed without hitting depth==0 early → fully wrapped.
            if tokens[end - 1].str == ")":
                return _eval_tokens(tokens, start + 1, end - 1, context)

    # --- Binary operators (scan right-to-left for left-associativity) ---
    for level in _BINOP_LEVELS:
        depth = 0
        k = end - 1
        while k >= start:
            s = tokens[k].str
            if s in (")", "]", "}"):
                depth += 1
            elif s in ("(", "[", "{"):
                depth -= 1
            elif depth == 0:
                for op in level:
                    op_len = len(op)
                    # Check whether tokens[k : k + op_len] match the operator.
                    # For single-char operators check the single token string;
                    # for two-char operators check two adjacent tokens' concat.
                    matched = False
                    op_end_idx = k  # first token after the operator
                    if op_len == 1 and tokens[k].str == op:
                        matched = True
                        op_end_idx = k + 1
                    elif op_len == 2:
                        # Multi-char operators are stored as a single token.
                        if tokens[k].str == op:
                            matched = True
                            op_end_idx = k + 1
                    if not matched:
                        continue
                    # Guard: don't match unary - or + at the leftmost position.
                    if op in ("+", "-") and k == start:
                        continue
                    lhs_str_start = start
                    lhs_str_end = k
                    rhs_str_start = op_end_idx
                    rhs_str_end = end
                    if lhs_str_start >= lhs_str_end or rhs_str_start >= rhs_str_end:
                        continue
                    lhs = _eval_tokens(tokens, lhs_str_start, lhs_str_end, context)
                    rhs = _eval_tokens(tokens, rhs_str_start, rhs_str_end, context)
                    if op == "||":
                        return int(bool(lhs) or bool(rhs))
                    if op == "&&":
                        return int(bool(lhs) and bool(rhs))
                    if op == "|":
                        return lhs | rhs
                    if op == "^":
                        return lhs ^ rhs
                    if op == "&":
                        return lhs & rhs
                    if op == "==":
                        return int(lhs == rhs)
                    if op == "!=":
                        return int(lhs != rhs)
                    if op == "<=":
                        return int(lhs <= rhs)
                    if op == ">=":
                        return int(lhs >= rhs)
                    if op == "<":
                        return int(lhs < rhs)
                    if op == ">":
                        return int(lhs > rhs)
                    if op == "<<":
                        return lhs << rhs
                    if op == ">>":
                        return lhs >> rhs
                    if op == "+":
                        return lhs + rhs
                    if op == "-":
                        return lhs - rhs
                    if op == "*":
                        return lhs * rhs
                    if op == "/":
                        if rhs == 0:
                            raise ValueError("division by zero")
                        return int(lhs / rhs)
                    if op == "%":
                        if rhs == 0:
                            raise ValueError("modulo by zero")
                        return lhs % rhs
            k -= 1

    # --- Unary operators ---
    if tokens[start].str == "!":
        return int(not _eval_tokens(tokens, start + 1, end, context))
    if tokens[start].str == "~":
        return ~_eval_tokens(tokens, start + 1, end, context)
    if tokens[start].str == "-":
        return -_eval_tokens(tokens, start + 1, end, context)
    if tokens[start].str == "+":
        return _eval_tokens(tokens, start + 1, end, context)

    raise ValueError(f"cannot evaluate: {' '.join(t.str for t in tokens[start:end])!r}")


# ---------------------------------------------------------------------------
# Deferred imports
# ---------------------------------------------------------------------------

from ..ParsingError import ParsingError
from ..type.ClassType import ClassType
from ..type.UnionType import UnionType
from ..type.StructType import StructType
from ..type.QualType import QualType
from ..type.qual_atomic_type_util import compare_no_cvr, get_value_type
from ..type.proc_typed_decl import proc_typed_decl
from ..type.align_size_of import size_of
from ...lexer.lexer import Token, TokenType
from ..expr.LiteralExpr import LiteralExpr
from ...lexer.lexer import Token
from ..type.CompileContext import CompileContext
