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
    elif tokens[c].type_id == TokenType.NAME:
        rtn = NameRefExpr()
        c = rtn.build(tokens, c, end, context)
        return ExprOpPart(rtn), c
    else:
        raise ParsingError(tokens, c, "Unrecognized Token Type")


from ..ParsingError import ParsingError
from .LiteralExpr import LiteralExpr
from .expr_part.SimpleOpPart import SimpleOpPart
from .expr_part.SParenthOpPart import SParenthOpPart
from .expr_part.ExprOpPart import ExprOpPart
from .expr_part.InlineIfOpPart import InlineIfOpPart
from .expr_part.BaseOpPart import BaseOpPart
from .CurlyExpr import CurlyExpr
from ...lexer.lexer import BreakSymClass, TokenType, OperatorClass, Token
from .get_expr import get_expr
from .NameRefExpr import NameRefExpr
from ..type.IdentifiedQualType import IdentifiedQualType
from ..type.proc_typed_decl import proc_typed_decl
from ...ParseConstants import OPEN_GROUPS, CLOSE_GROUPS
from ..constants import DCT_FIXES
from ..context.CompileContext import CompileContext
from .expr_part.ParentOpPart import ParenthOpPart
from .expr_part.CastOpPart import CastOpPart
