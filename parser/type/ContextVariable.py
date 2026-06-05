from typing import List, Optional, TYPE_CHECKING

from .VarDeclMods import VarDeclMods
from .ContextMember import ContextMember
from ...PrettyRepr import PrettyRepr, get_pretty_repr


class ContextVariable(ContextMember, PrettyRepr):
    def __init__(
        self,
        name: str,
        typ: "BaseType",
        init_expr: Optional["BaseExpr"] = None,
        mods: VarDeclMods = VarDeclMods.DEFAULT,
    ):
        super(ContextVariable, self).__init__(name, None)
        # self.size = size_of(typ, mods == VarDeclMods.IS_ARG)
        self.init_expr = init_expr
        self.is_op_fn = False
        self.typ: BaseType = typ
        self.mods = mods if isinstance(mods, VarDeclMods) else VarDeclMods(mods)
        self.bit_field_width: Optional[int] = None
        self.align_override: Optional[int] = None
        self.section_name: Optional[str] = None
        self.attributes: List[Attribute] = []

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.name,
                self.typ,
                self.init_expr,
                self.mods,
                self.align_override,
            ),
            pretty_repr_ctx,
        )

    def has_external_linkage(self) -> bool:
        if self.parent is None:
            return False
        if self.parent.is_local_scope():
            return self.mods == VarDeclMods.EXTERN
        if self.mods == VarDeclMods.STATIC:
            return False
        return self.parent.is_namespace() or is_fn_type(self.typ)

    def _get_linkage_scope(self) -> "CompileContext":
        assert self.parent is not None
        if self.parent.is_local_scope() and self.mods == VarDeclMods.EXTERN:
            scope = self.parent
            assert isinstance(scope, LocalScope)
            assert scope.host_scopeable is not None
            return scope.host_scopeable
        return self.parent

    def _get_isaac_link_name(self) -> str:
        assert self.parent is not None
        if self.parent.is_local_scope() and self.mods != VarDeclMods.EXTERN:
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
            ns = self._get_linkage_scope()
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

    def get_link_name(self):
        isaac_name = self._get_isaac_link_name()
        if not self.has_external_linkage():
            return isaac_name
        scope = self._get_linkage_scope()
        mode = scope.name_mangling_mode
        if mode == NameManglingMode.NONE and (scope.parent is not None or scope.name):
            raise NameError(
                "External namespace or member symbol '%s' requires name mangling; "
                "compile with --mangle" % self.get_full_name()
            )
        return select_external_link_name(self.name, isaac_name, mode)

    def uses_stack_storage(self) -> bool:
        return (
            self.parent is not None
            and self.parent.is_local_scope()
            and self.mods not in {VarDeclMods.STATIC, VarDeclMods.EXTERN}
        )

    def has_static_storage(self) -> bool:
        return not self.uses_stack_storage()

    def is_static_local(self) -> bool:
        return (
            self.parent is not None
            and self.parent.is_local_scope()
            and self.mods == VarDeclMods.STATIC
        )

    def const_init(self, expr):
        self.init_expr = expr
        if (
            not isinstance(self.typ, QualType)
            or self.typ.qual_id != QualType.QUAL_CONST
        ):
            self.typ = QualType(QualType.QUAL_CONST, self.typ)
        return self

    def effective_alignment(self) -> int:
        align = align_of(self.typ, owner=self.parent)
        if self.align_override is not None:
            align = max(align, self.align_override)
        return align


from .BaseType import BaseType
from .align_size_of import align_of
from .QualType import QualType
from .is_fn_type import is_fn_type
from ..expr.BaseExpr import BaseExpr
from ...code_gen.NameMangling import NameManglingMode, select_external_link_name
from .LocalScope import LocalScope
from .Attribute import Attribute
from .CompileContext import CompileContext
