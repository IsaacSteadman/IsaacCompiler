from enum import Enum
from typing import Optional, TYPE_CHECKING
from .ContextMember import ContextMember
from ...PrettyRepr import PrettyRepr, get_pretty_repr


class VarDeclMods(Enum):
    DEFAULT = 0
    STATIC = 1
    EXTERN = 2
    IS_ARG = 3


class ContextVariable(ContextMember, PrettyRepr):
    def __init__(
        self,
        name: str,
        typ: "BaseType",
        init_expr: Optional["BaseExpr"] = None,
        mods: VarDeclMods = VarDeclMods.DEFAULT,
    ):
        super(ContextVariable, self).__init__(name, None)
        # self.Size = SizeOf(typ, Mods == VarDeclMods.IS_ARG)
        self.init_expr = init_expr
        self.is_op_fn = False
        self.typ: "BaseType" = typ
        self.mods = mods

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (self.name, self.typ, self.init_expr, self.mods)
        )

    def get_link_name(self):
        if self.parent.is_local_scope():
            scope: "LocalScope" = self.parent
            lst_rtn = [0] * scope.lvl
            c = 0
            test = scope
            while test.is_local_scope():
                scope: "LocalScope" = test
                if c >= len(lst_rtn):
                    lst_rtn.append(0)
                lst_rtn[c] = scope.scope_index
                test = scope.parent
            return (
                "$"
                + "?".join(map(str, lst_rtn))
                + "?"
                + self.typ.to_mangle_str(False)
                + self.name
            )
        else:
            ns = self.parent
            lst_rtn = [""]
            while ns.parent is not None:
                lst_rtn.append(ns.name)
                ns = ns.parent
            if self.is_op_fn:
                raise NotImplementedError("Not Implemented")
                # TODO replace `OP_MANGLE` with a mapping from operator name and type to its mangled name
                # return "@".join(lst_rtn) + "$" + self.typ.ToMangleStr(True) + `OP_MANGLE` + "_g"
            else:
                return (
                    "@".join(lst_rtn) + "?" + self.typ.to_mangle_str(True) + self.name
                )

    def const_init(self, expr):
        self.init_expr = expr
        if (
            not isinstance(self.typ, QualType)
            or self.typ.qual_id != QualType.QUAL_CONST
        ):
            self.typ = QualType(QualType.QUAL_CONST, self.typ)
        return self


if TYPE_CHECKING:
    from .LocalScope import LocalScope
    from ..expr.BaseExpr import BaseExpr
    from ..type.BaseType import BaseType
from ..type.QualType import QualType
