def get_strict_stmnt(tokens, c, end, context):
    assert isinstance(context, (ClassType, StructType, UnionType))
    # TODO: place all members in host_scopeable (allows for scoped 'using' [namespace])
    start = c
    if (
        tokens[c].type_id == TokenType.NAME
        and tokens[c].str == context.name
        and tokens[c + 1].str == "("
    ):
        pos = StmntType.DECL
    elif tokens[c].type_id == TokenType.NAME and is_type_name_part(
        tokens[c].str, context
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


from .BaseStmnt import STMNT_KEY_TO_ID, StmntType
from .DeclStmnt import DeclStmnt
from .TypeDefStmnt import TypeDefStmnt
from ..ParsingError import ParsingError
from ..type.ClassType import ClassType
from ..type.StructType import StructType
from ..type.UnionType import UnionType
from ..type.is_type_name_part import is_type_name_part
from ...lexer.lexer import TokenType
from .CurlyStmnt import CurlyStmnt
