from typing import List, Optional
from .BaseStmnt import BaseStmnt, StmntType


class NamespaceStmnt(BaseStmnt):
    stmnt_type = StmntType.NAMESPACE

    def __init__(self, lst_stmnts: Optional[List[BaseStmnt]] = None):
        self.lst_stmnts: List[BaseStmnt] = [] if lst_stmnts is None else lst_stmnts
        self.ns = None

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        c += 1
        if tokens[c].type_id != TokenType.NAME:
            raise ParsingError(tokens, c, "Expected name for namespace")
        name = tokens[c].str
        ns = context.namespace_strict(name)
        if ns is None:
            ns = CompileContext(name, context)
            context.namespaces[name] = ns
        self.ns = ns
        c += 1
        if tokens[c].str == ";":
            c += 1
        elif tokens[c].str == "{":
            c += 1
            lst_stmnts = self.lst_stmnts
            while tokens[c].str != "}" and c < end:
                stmnt, c = get_stmnt(tokens, c, end, ns)
                lst_stmnts.append(stmnt)
            if c >= end:
                raise ParsingError(
                    tokens, c, "[Namespace] Unexpected end reached before closing '}'"
                )
            c += 1
        return c

    # default pretty_repr
    # default __init__


from ..ParsingError import ParsingError
from .get_stmnt import get_stmnt
from ..context.CompileContext import CompileContext
from ...lexer.lexer import Token, TokenType
