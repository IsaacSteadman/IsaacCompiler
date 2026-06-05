from typing import List


def get_strict_stmnt(
    tokens: List["Token"], c: int, end: int, context: "CompileContext"
):
    assert isinstance(context, (ClassType, StructType, UnionType))
    # TODO: place all members in host_scopeable (allows for scoped 'using' [namespace])
    start = c
    decl_c = skip_gnu_attrs(tokens, c, end)
    if (
        decl_c < end
        and tokens[decl_c].type_id == TokenType.NAME
        and tokens[decl_c].str == context.name
        and decl_c + 1 < end
        and tokens[decl_c + 1].str == "("
    ):
        pos = StmntType.DECL
    elif (
        decl_c < end
        and tokens[decl_c].type_id == TokenType.NAME
        and is_type_name_part(tokens[decl_c].str, context)
    ):
        pos = StmntType.DECL
    else:
        pos = STMNT_KEY_TO_ID.get(tokens[c].str, StmntType.SEMI_COLON)
    rtn = None
    if pos == StmntType.CURLY_STMNT:
        rtn = CurlyStmnt()
        c = rtn.build(tokens, c, end, context)
        if start == c:
            raise ParsingError(
                tokens, c, "Expected only '{' statement (not expression)"
            )
    elif pos == StmntType.DECL:
        rtn = DeclStmnt()
        # print "Before c = %u, end = %u, StmntType.DECL" % (c, end)
        c = rtn.build(tokens, c, end, context)
        # print "After c = %u, end = %u, StmntType.DECL" % (c, end)
    elif pos == StmntType.TYPEDEF:
        rtn = TypeDefStmnt()
        c = rtn.build(tokens, c, end, context)
    if rtn is None:
        raise ParsingError(
            tokens,
            c,
            "Expected only '{' statement or decl/typedef statement for strict statement",
        )
    return rtn, c


from .CompileContext import CompileContext
from .ClassType import ClassType
from .StructType import StructType
from .UnionType import UnionType
from ..ParsingError import ParsingError
from ..stmnt.CurlyStmnt import CurlyStmnt
from ..stmnt.DeclStmnt import DeclStmnt
from ..stmnt.TypeDefStmnt import TypeDefStmnt
from .gnu_attrs import skip_gnu_attrs
from ...lexer.lexer import Token, TokenType
from ..stmnt.BaseStmnt import StmntType, STMNT_KEY_TO_ID
from .is_type_name_part import is_type_name_part
