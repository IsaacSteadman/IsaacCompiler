from typing import Tuple, List, TYPE_CHECKING
from ..util import try_catch_wrapper0


@try_catch_wrapper0
def get_stmnt(
    tokens: List["Token"], c: int, end: int, context: "CompileContext"
) -> Tuple["BaseStmnt", int]:
    start = c
    position = tokens[c].line, tokens[c].col
    if tokens[c].type_id == TokenType.NAME and is_type_name_part(
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
            pos = StmntType.SEMI_COLON
            rtn = SemiColonStmnt()
            c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.IF:
        rtn = IfElse()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.WHILE:
        rtn = WhileLoop()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.FOR:
        rtn = ForLoop()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.RTN:
        rtn = ReturnStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.BRK:
        rtn = BreakStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.CONTINUE:
        rtn = ContinueStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.NAMESPACE:
        rtn = NamespaceStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.TYPEDEF:
        rtn = TypeDefStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.DECL:
        rtn = DeclStmnt()
        # print "Before c = %u, end = %u, StmntType.DECL" % (c, end)
        c = rtn.build(tokens, c, end, context)
        # print "After c = %u, end = %u, StmntType.DECL" % (c, end)
    elif pos == StmntType.ASM:
        rtn = AsmStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.SEMI_COLON:
        # NOTE: Make sure that DeclStmnt would not work here
        rtn = SemiColonStmnt()
        # print "Before c = %u, end = %u, StmntType.SEMI_COLON" % (c, end)
        c = rtn.build(tokens, c, end, context)
        # print "After c = %u, end = %u, StmntType.SEMI_COLON" % (c, end)
    if rtn is None:
        raise LookupError("statement id: %u unaccounted for" % pos)
    rtn.position = position
    return rtn, c


from ...lexer.lexer import Token, TokenType
from ..type.is_type_name_part import is_type_name_part
from .BaseStmnt import BaseStmnt, StmntType, STMNT_KEY_TO_ID
from .AsmStmnt import AsmStmnt
from .BreakStmnt import BreakStmnt
from .ContinueStmnt import ContinueStmnt
from .CurlyStmnt import CurlyStmnt
from .NamespaceStmnt import NamespaceStmnt
from .ReturnStmnt import ReturnStmnt
from .SemiColonStmnt import SemiColonStmnt
from .TypeDefStmnt import TypeDefStmnt
from .WhileLoop import WhileLoop
from .DeclStmnt import DeclStmnt
from .ForLoop import ForLoop
from .IfElse import IfElse

if TYPE_CHECKING:
    from ..context.CompileContext import CompileContext
