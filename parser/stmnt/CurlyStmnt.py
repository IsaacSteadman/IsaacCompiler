from .BaseStmnt import BaseStmnt, StmntType
from typing import List, Optional


class CurlyStmnt(BaseStmnt):
    stmnt_type = StmntType.CURLY_STMNT
    # init-args added for __repr__

    def __init__(self, stmnts: Optional[List[BaseStmnt]] = None, name: str = ""):
        self.stmnts = stmnts
        self.name = name
        self.context = None

    def pretty_repr(self, pretty_repr_ctx=None):
        rtn = (
            [self.__class__.__name__, "("]
            + get_pretty_repr(self.stmnts, pretty_repr_ctx)
            + [")"]
        )
        if self.name != "":
            rtn[-1:-1] = get_pretty_repr(self.name, pretty_repr_ctx)
        return rtn

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        self.stmnts = []
        self.context = context.new_scope(LocalScope(self.name))
        c += 1
        while c < end and tokens[c].str != "}":
            stmnt, c = get_stmnt(tokens, c, end, self.context)
            self.stmnts.append(stmnt)
        c += 1
        return c


from .get_stmnt import get_stmnt
from ...PrettyRepr import get_pretty_repr
from ..type.types import CompileContext, LocalScope
from ...lexer.lexer import Token
