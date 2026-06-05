from .BaseStmnt import BaseStmnt, StmntType
from typing import List, Optional


class CurlyStmnt(BaseStmnt):
    stmnt_type = StmntType.CURLY_STMNT
    # init-args added for __repr__

    def __init__(self, stmnts: Optional[List[BaseStmnt]] = None, name: str = ""):
        self.stmnts = stmnts
        self.name = name
        self.context = None
        self.implicit_ctx_vars = []

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
        self._inject_function_name_builtins(context)
        c += 1
        while c < end and tokens[c].str != "}":
            stmnt, c = get_stmnt(tokens, c, end, self.context)
            self.stmnts.append(stmnt)
        c += 1
        return c

    def _inject_function_name_builtins(self, parent_context: "CompileContext") -> None:
        if (
            not isinstance(parent_context, LocalScope)
            or parent_context.lvl != 0
            or len(parent_context.name) == 0
        ):
            return
        if self.context.has_var_strict("__func__"):
            return

        fn_name = parent_context.name
        char_type = PrimitiveType.from_type_code(PrimitiveTypeId.INT_C)
        elem_type = QualType(QualType.QUAL_CONST, char_type)
        arr_type = QualType(QualType.QUAL_ARR, elem_type, len(fn_name) + 1)
        literal = LiteralExpr(LiteralExpr.LIT_STR, '"%s"' % fn_name)
        literal.l_val = list(map(ord, fn_name))
        literal.t_anot = QualType(QualType.QUAL_REF, arr_type)

        ctx_var = ContextVariable("__func__", arr_type, literal, VarDeclMods.STATIC)
        self.context.new_var("__func__", ctx_var)
        self.context.new_var("__FUNCTION__", ctx_var)
        self.implicit_ctx_vars.append(ctx_var)


from .get_stmnt import get_stmnt
from ...PrettyRepr import get_pretty_repr
from ..type.CompileContext import CompileContext
from ..type.LocalScope import LocalScope
from ...lexer.lexer import Token
from ..expr.LiteralExpr import LiteralExpr
from ..type.ContextVariable import ContextVariable
from ..type.PrimitiveType import PrimitiveType, PrimitiveTypeId
from ..type.QualType import QualType
from ..type.VarDeclMods import VarDeclMods
