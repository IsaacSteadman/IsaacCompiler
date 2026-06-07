from typing import Tuple, List
from ..util import try_catch_wrapper0


@try_catch_wrapper0
def get_stmnt(
    tokens: List["Token"], c: int, end: int, context: "CompileContext"
) -> Tuple["BaseStmnt", int]:
    start = c
    position = tokens[c].line, tokens[c].col
    _DECL_SPECIFIERS = {"extern", "static", "inline", "_Noreturn"}
    decl_c = c
    leading_attr_specs = []
    while (
        decl_c < end
        and tokens[decl_c].type_id == TokenType.NAME
        and tokens[decl_c].str == "__attribute__"
    ):
        if decl_c + 1 >= end or tokens[decl_c + 1].str != "(":
            break
        decl_c, specs = parse_single_gnu_attr_specs(tokens, decl_c, end)
        leading_attr_specs.extend(specs)
    if (
        decl_c < end
        and tokens[decl_c].str == ";"
        and any(spec.attribute.name == "fallthrough" for spec in leading_attr_specs)
    ):
        rtn = SemiColonStmnt()
        rtn.position = position
        return rtn, decl_c + 1
    if tokens[decl_c].type_id == TokenType.NAME and (
        is_type_name_part(tokens[decl_c].str, context)
        or tokens[decl_c].str in _DECL_SPECIFIERS
    ):
        pos = StmntType.DECL
    else:
        pos = STMNT_KEY_TO_ID.get(tokens[c].str, StmntType.SEMI_COLON)
    # Two-token lookahead: NAME ':' → label statement (must not be '::', which is a single token)
    if (
        pos == StmntType.SEMI_COLON
        and tokens[c].type_id == TokenType.NAME
        and c + 1 < end
        and tokens[c + 1].str == ":"
    ):
        pos = StmntType.LABEL
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
    elif pos == StmntType.STATIC_ASSERT:
        rtn = StaticAssertStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.SWITCH:
        rtn = SwitchStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.GOTO:
        rtn = GotoStmnt()
        c = rtn.build(tokens, c, end, context)
    elif pos == StmntType.LABEL:
        rtn = LabelStmnt()
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


from .AsmStmnt import AsmStmnt
from .BaseStmnt import BaseStmnt, STMNT_KEY_TO_ID, StmntType
from .BreakStmnt import BreakStmnt
from .ContinueStmnt import ContinueStmnt
from .CurlyStmnt import CurlyStmnt
from .ForLoop import ForLoop
from .GotoStmnt import GotoStmnt
from .IfElse import IfElse
from .LabelStmnt import LabelStmnt
from .NamespaceStmnt import NamespaceStmnt
from .ReturnStmnt import ReturnStmnt
from .SemiColonStmnt import SemiColonStmnt
from .StaticAssertStmnt import StaticAssertStmnt
from .SwitchStmnt import SwitchStmnt
from .DeclStmnt import DeclStmnt
from .TypeDefStmnt import TypeDefStmnt
from .WhileLoop import WhileLoop
from ..type.is_type_name_part import is_type_name_part
from ..type.gnu_attrs import parse_single_gnu_attr_specs
from ..type.CompileContext import CompileContext
from ...lexer.lexer import Token, TokenType
