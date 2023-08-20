from typing import List, Optional, Tuple
from ..util import try_catch_wrapper1


@try_catch_wrapper1
def get_expr(
    tokens: List["Token"],
    c: int,
    delim: Optional[str],
    end: int,
    context: "CompileContext",
) -> Tuple[Optional["BaseExpr"], int]:
    # TODO: complete
    start = c
    rtn, c = mk_postfix(tokens, c, end, context, my_get_expr_part, delim)
    # print("All the Postfix:\n  ", "\n  ".join(map(repr, rtn)))
    stack = list()
    for Part in rtn:
        if len(stack) < Part[0]:
            print(stack, Part)
            raise ParsingError(
                tokens, c, "Insufficient number of operands for operator: %r" % Part[1]
            )
        if Part[0] == 0:
            try:
                stack.append(Part[1].build([], 0))  # nofix
            except Exception as exc:
                del exc
                print("c = %u" % c)
                raise
        elif Part[0] == 1:
            op_part = Part[1]
            assert isinstance(op_part, BaseOpPart)
            if len(stack) < 1:
                raise ParsingError(
                    tokens,
                    c,
                    "expected operands for prefix/postfix operator: %s" % op_part.txt,
                )
            a = stack.pop()
            try:
                stack.append(op_part.build([a], Part[3]))  # prefix/postfix
            except Exception as exc:
                del exc
                print("c = %u" % c)
                raise
        elif Part[0] == 2:
            op_part = Part[1]
            assert isinstance(op_part, BaseOpPart)
            b = stack.pop()
            a = stack.pop()
            try:
                stack.append(op_part.build([a, b], Part[3]))  # infix
            except Exception as exc:
                del exc
                print(get_user_str_parse_pos(tokens, c))
                raise
        else:
            raise ParsingError(tokens, c, "Unexpected number of required operands")
    if len(stack) == 0 and start == c:
        return None, c
    if len(stack) != 1:
        raise ParsingError(tokens, c, "Expected single expression got %s" % repr(stack))
    return stack[0], c


from .BaseExpr import BaseExpr
from .mk_postfix import mk_postfix
from ..ParsingError import ParsingError
from ..get_user_str_parse_pos import get_user_str_parse_pos
from .expr_part.BaseOpPart import BaseOpPart
from ..type.types import CompileContext
from ...lexer.lexer import Token
from .my_get_expr_part import my_get_expr_part
