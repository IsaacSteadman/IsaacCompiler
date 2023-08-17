from .BaseStmnt import BaseStmnt, StmntType
from typing import List, Optional, TYPE_CHECKING


class CurlyStmnt(BaseStmnt):
    stmnt_type = StmntType.CURLY_STMNT
    # init-args added for __repr__

    def __init__(self, stmnts: Optional[List[BaseStmnt]] = None, name: str = ""):
        self.stmnts = stmnts
        self.name = name
        self.context = None

    def pretty_repr(self):
        rtn = [self.__class__.__name__, "("] + get_pretty_repr(self.stmnts) + [")"]
        if self.name != "":
            rtn[-1:-1] = get_pretty_repr(self.name)
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


from ...PrettyRepr import get_pretty_repr
from ..context.LocalScope import LocalScope
from ...lexer.lexer import Token

if TYPE_CHECKING:
    from ..context.CompileContext import CompileContext

from .get_stmnt import get_stmnt
