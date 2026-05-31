from typing import List, Optional, Tuple
from ..util import try_catch_wrapper0

"""def GetTypeName(tokens, c, end, context, Strict=False):
    type_name = TypeNameInf()
    try:
        c = type_name.build(tokens, c, end, context)
    except Exception as Exc:
        if Strict:
            raise
        else: return None, c
    return type_name, c"""

# TODO: find out why MyGetExprPart(..from LangTest.py, 107, 391, ..context) returns ?, 2


@try_catch_wrapper0
def my_get_expr_part(
    tokens: List["Token"],
    c: int,
    end: int,
    context: "CompileContext",
) -> Tuple["BaseOpPart", int]:
    s = tokens[c].str
    if LiteralExpr.is_literal_token(tokens[c]):
        rtn = LiteralExpr()
        c = rtn.build(tokens, c, end, context)
        return ExprOpPart(rtn), c
    elif s == ".":
        line, col = tokens[c].line, tokens[c].col
        c += 1
        if tokens[c].type_id != TokenType.NAME:
            raise ParsingError(tokens, c, "expected name after '.'")
        s += tokens[c].str
        c += 1
        return SimpleOpPart(BreakSymClass(s, line, col)), c
    elif s == "->":
        line, col = tokens[c].line, tokens[c].col
        c += 1
        if tokens[c].type_id != TokenType.NAME:
            raise ParsingError(tokens, c, "expected name after '.'")
        s += tokens[c].str
        c += 1
        return SimpleOpPart(OperatorClass(s, line, col)), c
    elif s in DCT_FIXES:
        rtn = SimpleOpPart(tokens[c])
        c += 1
        return rtn, c
    elif s == "(":
        lvl = 1
        start = c
        c += 1
        comma_count = 0
        while lvl > 0:
            s = tokens[c].str
            if s in OPEN_GROUPS:
                lvl += 1
            elif s in CLOSE_GROUPS:
                lvl -= 1
            elif s == "," and lvl == 1:
                comma_count += 1
            c += 1
        end_t = c
        end_p = end_t - 1
        c = start + 1
        if c == end_p:
            c = end_t
            return ParenthOpPart([]), c
        # GNU statement expression: ({ ... })
        if tokens[c].str == "{":
            stmnt_expr = StmntExpr()
            c = stmnt_expr.build(tokens, c, end_p, context)
            # c is now at ')'; advance past it
            c = end_t
            return ExprOpPart(stmnt_expr), c
        if comma_count == 0:
            type_name, c = proc_typed_decl(tokens, c, end_p, context)
            if c > start + 1 and type_name is not None:
                assert isinstance(type_name, IdentifiedQualType)
                if type_name.name is not None:
                    print(
                        "WARN: (c = %u) Unexpected name in C-Style Cast Operator: '%s'"
                        % (c, type_name.name)
                    )
                c = end_t
                return CastOpPart(type_name.typ), c
        lst_expr = [None] * (comma_count + 1)
        n_expr = 0
        while c < end_p:
            lst_expr[n_expr], c = get_expr(tokens, c, ",", end_p, context)
            c += 1
            n_expr += 1
        return ParenthOpPart(lst_expr), c
    elif s == "[":
        c += 1
        expr, c = get_expr(tokens, c, "]", end, context)
        if tokens[c].str != "]":
            raise ParsingError(
                tokens, c, "Only single expression inside '[' and ']' is allowed"
            )
        c += 1
        return SParenthOpPart(expr), c
    elif s == "{":
        expr = CurlyExpr()
        # TODO: fix the incorrect usage (will throw error if '}' is encountered)
        c = expr.build(tokens, c, end, context)
        c += 1  # TODO: verify this is correct usage of return value
        return ExprOpPart(expr), c
    elif s == "?":
        c += 1
        expr, c = get_expr(tokens, c, ":", end, context)
        c += 1
        return InlineIfOpPart(expr), c
    elif (
        s in {"va_start", "va_arg", "va_end", "va_copy"}
        and c + 1 < end
        and tokens[c + 1].str == "("
    ):
        intrinsic_name = s
        c += 2  # consume name + '('
        lvl = 1
        paren_end = c
        while paren_end < end and lvl > 0:
            if tokens[paren_end].str in OPEN_GROUPS:
                lvl += 1
            elif tokens[paren_end].str in CLOSE_GROUPS:
                lvl -= 1
            if lvl > 0:
                paren_end += 1
        # paren_end is at ')'
        rtn_expr = _build_va_intrinsic(intrinsic_name, tokens, c, paren_end, context)
        c = paren_end + 1
        return ExprOpPart(rtn_expr), c
    elif tokens[c].type_id == TokenType.NAME:
        rtn = NameRefExpr()
        c = rtn.build(tokens, c, end, context)
        return ExprOpPart(rtn), c
    else:
        raise ParsingError(tokens, c, "Unrecognized Token Type")


from .CurlyExpr import CurlyExpr
from .LiteralExpr import LiteralExpr
from .NameRefExpr import NameRefExpr
from .StmntExpr import StmntExpr
from .VaIntrinsicExpr import VaIntrinsicExpr
from .get_expr import get_expr
from ..ParsingError import ParsingError
from ..constants import DCT_FIXES
from .expr_part.BaseOpPart import BaseOpPart
from .expr_part.CastOpPart import CastOpPart
from .expr_part.ExprOpPart import ExprOpPart
from .expr_part.InlineIfOpPart import InlineIfOpPart
from .expr_part.ParentOpPart import ParenthOpPart
from .expr_part.SParenthOpPart import SParenthOpPart
from .expr_part.SimpleOpPart import SimpleOpPart
from ...ParseConstants import CLOSE_GROUPS, OPEN_GROUPS
from ..type.types import IdentifiedQualType, proc_typed_decl, CompileContext, void_t
from ...lexer.lexer import BreakSymClass, OperatorClass, Token, TokenType


def _build_va_intrinsic(name, tokens, c, end, context):
    if name == "va_start":
        ap_expr, c = get_expr(tokens, c, ",", end, context)
        assert tokens[c].str == ",", "va_start expects two arguments"
        c += 1  # skip ','
        last_expr, _c = get_expr(tokens, c, None, end, context)
        from .BaseExpr import ExprType

        rtn = VaIntrinsicExpr(VaIntrinsicExpr.INTRINSIC_VA_START, [ap_expr, last_expr])
        rtn.t_anot = void_t
        return rtn
    elif name == "va_arg":
        ap_expr, c = get_expr(tokens, c, ",", end, context)
        assert tokens[c].str == ",", "va_arg expects two arguments"
        c += 1  # skip ','
        type_decl, _c = proc_typed_decl(tokens, c, end, context)
        assert type_decl is not None, "va_arg: second argument must be a type"
        rtn = VaIntrinsicExpr(
            VaIntrinsicExpr.INTRINSIC_VA_ARG, [ap_expr], arg_type=type_decl.typ
        )
        rtn.t_anot = type_decl.typ
        return rtn
    elif name == "va_end":
        ap_expr, _c = get_expr(tokens, c, None, end, context)
        rtn = VaIntrinsicExpr(VaIntrinsicExpr.INTRINSIC_VA_END, [ap_expr])
        rtn.t_anot = void_t
        return rtn
    elif name == "va_copy":
        dst_expr, c = get_expr(tokens, c, ",", end, context)
        assert tokens[c].str == ",", "va_copy expects two arguments"
        c += 1  # skip ','
        src_expr, _c = get_expr(tokens, c, None, end, context)
        rtn = VaIntrinsicExpr(VaIntrinsicExpr.INTRINSIC_VA_COPY, [dst_expr, src_expr])
        rtn.t_anot = void_t
        return rtn
    else:
        raise ValueError("Unknown va intrinsic: %s" % name)
