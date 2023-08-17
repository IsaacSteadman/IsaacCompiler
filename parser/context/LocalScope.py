from typing import Optional
from .CompileContext import CompileContext


class LocalScope(CompileContext):
    def __init__(self, name=""):
        super(LocalScope, self).__init__(name, None)
        self.host_scopeable: Optional[CompileContext] = None
        self.lvl: int = 0
        self.scope_index: Optional[int] = None
        # self.parent_decl: Optional[Tuple[DeclStmnt, int]] = None
        # self.parent_loop: Optional[Union[ForLoop, WhileLoop]] = None

    def set_parent(self, parent: "CompileContext", index: Optional[int] = None):
        if self.parent is not parent:
            self.parent = parent
            lvl = 0
            self.host_scopeable = parent
            if parent.is_local_scope():
                assert isinstance(parent, LocalScope)
                self.host_scopeable = parent.host_scopeable
                lvl = parent.lvl + 1
            if lvl == 0 and len(self.name) == 0:
                raise SyntaxError("cannot create anonymous function scopes yes")
            for c, scope in enumerate(self.scopes):
                assert isinstance(scope, LocalScope)
                scope.set_parent(self, c)
        self.scope_index = index

    def is_local_scope(self):
        return True

    def new_var(self, v: str, inst: "ContextVariable") -> "ContextVariable":
        vt = get_value_type(inst.typ)
        if vt.type_class_id == TypeClass.QUAL:
            assert isinstance(vt, QualType)
            if vt.qual_id == QualType.QUAL_FN:
                raise ValueError("Cannot define functions in LocalScope (attempt to define '%s')" % v)
        var = self.vars.get(v, None)
        if var is not None:
            raise NameError("Redefinition of Variable '%s' not allowed in LocalScope" % v)
        self.vars[v] = inst
        inst.parent = self
        return inst

    def has_ns(self, ns: str) -> bool:
        return self.host_scopeable.has_ns(ns)

    def has_ns_strict(self, ns: str) -> bool:
        return False

    def new_ns(self, ns: str, inst: CompileContext) -> CompileContext:
        raise ValueError("cannot create NameSpace in LocalScope")

    def namespace(self, ns: str) -> Optional[CompileContext]:
        return self.host_scopeable.namespace(ns)

    def namespace_strict(self, ns):
        return None


from .ContextVariable import ContextVariable
from ..type.BaseType import TypeClass
from ..type.QualType import QualType
from ..type.get_value_type import get_value_type