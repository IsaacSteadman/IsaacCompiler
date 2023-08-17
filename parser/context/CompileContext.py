from typing import Dict, List, Optional, TYPE_CHECKING
from .ContextMember import ContextMember


OPT_USER_INSPECT = 0
OPT_CODE_GEN = 1


class CompileContext(ContextMember):
    # Optimize tells the rest of the code to optimize (very slightly and not runtime performance-wise)
    #   the representation for the code generator
    Optimize = OPT_CODE_GEN

    def __init__(self, name: str, parent: Optional["CompileContext"] = None):
        super(CompileContext, self).__init__(name, parent)
        self.scopes: List["LocalScope"] = []
        self.types: Dict[str, "BaseType"] = {}
        self.namespaces: Dict[str, "CompileContext"] = {}
        self.vars: Dict[str, "ContextVariable"] = {}

    def is_namespace(self):
        return True

    def merge_to(self, other: "CompileContext"):
        keys = list(self.types)
        other.types.update(self.types)
        for k in keys:
            typ = other.types[k]
            assert isinstance(typ, ContextMember)
            typ.parent = other
        keys = list(self.namespaces)
        other.namespaces.update(self.namespaces)
        for k in keys:
            namespace = other.namespaces[k]
            assert isinstance(namespace, ContextMember)
            namespace.parent = other
        keys = list(self.vars)
        other.vars.update(self.vars)
        for k in keys:
            var = other.vars[k]
            var.parent = other
        pre_len = len(other.scopes)
        other.scopes.extend(self.scopes)
        for c in range(pre_len, len(other.scopes)):
            scope = other.scopes[c]
            scope.set_parent(other, c)

    def has_type(self, t: str) -> bool:
        return t in self.types or (self.parent is not None and self.parent.has_type(t))

    def has_var(self, v: str) -> bool:
        return v in self.vars or (self.parent is not None and self.parent.has_var(v))

    def has_ns(self, ns: str) -> bool:
        return ns in self.namespaces or (
            self.parent is not None and self.parent.has_ns(ns)
        )

    def has_type_strict(self, t: str) -> bool:
        return t in self.types

    def has_var_strict(self, v: str) -> bool:
        return v in self.vars

    def has_ns_strict(self, ns: str) -> bool:
        return ns in self.namespaces

    def new_type(self, t: str, inst: ContextMember) -> ContextMember:
        self.types[t] = inst
        inst.parent = self
        return inst

    def new_var(self, v: str, inst: "ContextVariable") -> "ContextVariable":
        inst.parent = self
        var = self.vars.get(v, None)
        if var is None:
            self.vars[v] = inst
            # print "AbsScopeGet(%r).NewVar(%r, %r)" % (self.GetFullName(), V, inst)
        else:
            if not is_fn_type(inst.typ):
                # raise NameError("Cannot have a function share the same name as a variable")
                return var
            if var.typ.type_class_id == TypeClass.MULTI:
                assert isinstance(var, OverloadedCtxVar)
                var.add_ctx_var(inst)
                # print "AbsScopeGet(%r).NewVar(%r, %r) # OVERLOAD" % (self.GetFullName(), V, inst)
            else:
                if not is_fn_type(var.typ):
                    raise NameError(
                        "Cannot have a variable share the same name as a function"
                    )
                var = OverloadedCtxVar(v, [var, inst])
                var.parent = self
                self.vars[v] = var
                # print "AbsScopeGet(%r).NewVar(%r, %r) # OVERLOAD" % (self.GetFullName(), V, inst)
        inst.parent = self
        return inst

    def new_ns(self, ns: str, inst: "CompileContext") -> "CompileContext":
        self.namespaces[ns] = inst
        # TODO: change to using set_parent like `new_scope` defined below
        inst.parent = self
        return inst

    def new_scope(self, inst: "LocalScope") -> "LocalScope":
        self.scopes.append(inst)
        inst.set_parent(self, len(self.scopes) - 1)
        return inst

    def type_name(self, t: str) -> Optional["ContextMember"]:
        rtn = self.type_name_strict(t)
        if rtn is None and self.parent is not None:
            return self.parent.type_name(t)
        return rtn

    def var_name(self, v: str) -> Optional["ContextVariable"]:
        rtn = self.var_name_strict(v)
        if rtn is None and self.parent is not None:
            return self.parent.var_name(v)
        return rtn

    def namespace(self, ns: str) -> Optional["CompileContext"]:
        rtn = self.namespace_strict(ns)
        if rtn is None and self.parent is not None:
            return self.parent.namespace(ns)
        return rtn

    def type_name_strict(self, t: str) -> Optional["ContextMember"]:
        return self.types.get(t, None)

    def var_name_strict(self, v: str) -> Optional["ContextVariable"]:
        return self.vars.get(v, None)

    def namespace_strict(self, ns: str) -> Optional["CompileContext"]:
        return self.namespaces.get(ns, None)

    def get_strict(self, k: str) -> Optional["ContextMember"]:
        rtn = self.vars.get(k, None)
        if rtn is not None:
            return rtn
        rtn = self.types.get(k, None)
        if rtn is not None:
            return rtn
        rtn = self.namespaces.get(k, None)
        return rtn

    def __getitem__(self, k: str) -> Optional["ContextMember"]:
        rtn = self.get(k)
        if rtn is None:
            raise KeyError("name '%s' was not found" % k)
        return rtn

    def get(self, k: str) -> Optional["ContextMember"]:
        rtn = self.get_strict(k)
        if rtn is None and self.parent is not None:
            rtn = self.parent.get(k)
        return rtn

    def scoped_get(self, k0: str) -> Optional["ContextMember"]:
        return self.scoped_get_lst(k0.split("::"))

    def scoped_get_strict(self, k0: str) -> Optional["ContextMember"]:
        return self.scoped_get_lst_strict(k0.split("::"))

    def scoped_get_lst(self, lst_scope: List[str]) -> Optional["ContextMember"]:
        # TODO: make the resolver resolve only absolute (no parent-inheritance), deferred to ScopedGetLst_Strict
        cur = self
        c = 0
        assert len(lst_scope) > 0
        if lst_scope[c] == "":
            while cur.parent is not None:
                cur = cur.parent
            c += 1
            if c >= len(lst_scope):
                return None
                # raise SyntaxError("bad global scope reference: '%s'" % "::".join(LstScope))
        end = len(lst_scope) - 1
        while c < end:
            cur = cur.namespace(lst_scope[c])
            if cur is None:
                return None
                # raise NameError("Bad name Resolution: '%s' is not in '%s'" % (LstScope[c], "::".join(LstScope[:c])))
            c += 1
        cur = cur[lst_scope[c]]
        if cur is None:
            return None
            # raise NameError("Bad name Resolution: '%s' is not in '%s'" % (LstScope[c], "::".join(LstScope[:c])))
        return cur

    def scoped_get_lst_strict(self, lst_scope: List[str]) -> Optional["ContextMember"]:
        cur = self
        c = 0
        if lst_scope[c] == "":
            while cur.parent is not None:
                cur = cur.parent
            c += 1
            if c >= len(lst_scope):
                return None
                # raise SyntaxError("bad global scope reference: '%s'" % "::".join(LstScope))
        end = len(lst_scope) - 1
        while c < end:
            cur = cur.namespace_strict(lst_scope[c])
            if cur is None:
                return None
                # raise NameError("Bad name Resolution: '%s' is not in '%s'" % (LstScope[c], "::".join(LstScope[:c])))
            c += 1
        cur = cur.get_strict(lst_scope[c])
        if cur is None:
            return None
            # raise NameError("Bad name Resolution: '%s' is not in '%s'" % (LstScope[c], "::".join(LstScope[:c])))
        return cur

    def __contains__(self, k: str) -> bool:
        return self.has_var(k) or self.has_type(k) or self.has_ns(k)

    def has_strict(self, k: str) -> bool:
        return self.get_strict(k) is not None

    def which(self, k: str) -> Optional["ContextMember"]:
        member = self.get(k)
        if member is None:
            return ""
        return member.get_full_name()

    # def __setitem__(self, k, v): raise NotImplementedError("NOT IMPLEMENTED")


if TYPE_CHECKING:
    from .ContextVariable import ContextVariable
    from .LocalScope import LocalScope

from .OverloadedCtxVar import OverloadedCtxVar
from ..type.BaseType import BaseType, TypeClass
from ..type.is_fn_type import is_fn_type
