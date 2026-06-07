from typing import Dict, List, Optional
from .ContextMember import ContextMember
from ...PrettyRepr import PrettyRepr, get_pretty_repr
from ...code_gen.NameMangling import (
    NameManglingMode,
    normalize_name_mangling_mode,
)

OPT_USER_INSPECT = 0
OPT_CODE_GEN = 1


class CompileContext(ContextMember, PrettyRepr):
    # Optimize tells the rest of the code to optimize (very slightly and not runtime performance-wise)
    #   the representation for the code generator
    Optimize = OPT_CODE_GEN

    def __init__(
        self,
        name: str,
        parent: Optional["CompileContext"] = None,
        default_alignment: Optional[int] = None,
        scopes: Optional[List["LocalScope"]] = None,
        types: Optional[Dict[str, "BaseType"]] = None,
        namespaces: Optional[Dict[str, "CompileContext"]] = None,
        vars: Optional[Dict[str, "ContextVariable"]] = None,
        name_mangling_mode: NameManglingMode = NameManglingMode.NONE,
    ):
        super(CompileContext, self).__init__(name, parent)
        if default_alignment is None and parent is not None:
            default_alignment = parent.default_alignment
        if parent is not None:
            name_mangling_mode = parent.name_mangling_mode
        self.default_alignment: Optional[int] = default_alignment
        self.name_mangling_mode = normalize_name_mangling_mode(name_mangling_mode)
        self.scopes: List["LocalScope"] = [] if scopes is None else scopes
        self.types: Dict[str, "BaseType"] = {} if types is None else types
        self.namespaces: Dict[str, "CompileContext"] = (
            {} if namespaces is None else namespaces
        )
        self.vars: Dict[str, "ContextVariable"] = {} if vars is None else vars

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
        other.default_alignment = self.default_alignment
        other.name_mangling_mode = self.name_mangling_mode

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
                if is_fn_type(var.typ):
                    raise NameError(
                        "Cannot have a variable share the same name as a function"
                    )
                return self._merge_compatible_decl(var, inst)
            if var.typ.type_class_id == TypeClass.MULTI:
                assert isinstance(var, OverloadedCtxVar)
                for specific in var.specific_ctx_vars:
                    if compare_no_cvr(specific.typ, inst.typ):
                        return self._merge_compatible_decl(specific, inst)
                self._check_external_overload(v, var.specific_ctx_vars[0], inst)
                var.add_ctx_var(inst)
                # print "AbsScopeGet(%r).NewVar(%r, %r) # OVERLOAD" % (self.GetFullName(), V, inst)
            else:
                if not is_fn_type(var.typ):
                    raise NameError(
                        "Cannot have a variable share the same name as a function"
                    )
                if compare_no_cvr(var.typ, inst.typ):
                    return self._merge_compatible_decl(var, inst)
                self._check_external_overload(v, var, inst)
                var = OverloadedCtxVar(v, [var, inst])
                var.parent = self
                self.vars[v] = var
                # print "AbsScopeGet(%r).NewVar(%r, %r) # OVERLOAD" % (self.GetFullName(), V, inst)
        inst.parent = self
        return inst

    def _check_external_overload(
        self,
        name: str,
        previous: "ContextVariable",
        current: "ContextVariable",
    ) -> None:
        if (
            self.name_mangling_mode == NameManglingMode.NONE
            and previous.has_external_linkage()
            and current.has_external_linkage()
        ):
            raise NameError(
                "External overload '%s' requires name mangling; compile with --mangle"
                % name
            )

    @staticmethod
    def _merge_compatible_decl(
        previous: "ContextVariable", current: "ContextVariable"
    ) -> "ContextVariable":
        if not compare_no_cvr(previous.typ, current.typ):
            raise TypeError("Conflicting declarations for '%s'" % previous.name)
        if (
            previous.mods == VarDeclMods.STATIC and current.mods != VarDeclMods.STATIC
        ) or (
            previous.mods != VarDeclMods.STATIC and current.mods == VarDeclMods.STATIC
        ):
            raise TypeError("Conflicting linkage for '%s'" % previous.name)
        if previous.mods == VarDeclMods.EXTERN and current.mods != VarDeclMods.EXTERN:
            previous.mods = current.mods
        if current.align_override is not None:
            previous.align_override = max(
                previous.align_override or 1, current.align_override
            )
        if current.section_name is not None:
            if (
                previous.section_name is not None
                and previous.section_name != current.section_name
            ):
                raise TypeError("Conflicting section for '%s'" % previous.name)
            previous.section_name = current.section_name
        if current.alias_name is not None:
            if (
                previous.alias_name is not None
                and previous.alias_name != current.alias_name
            ):
                raise TypeError("Conflicting alias for '%s'" % previous.name)
            previous.alias_name = current.alias_name
        if current.cleanup_name is not None:
            if (
                previous.cleanup_name is not None
                and previous.cleanup_name != current.cleanup_name
            ):
                raise TypeError("Conflicting cleanup for '%s'" % previous.name)
            previous.cleanup_name = current.cleanup_name
        previous.noreturn = previous.noreturn or current.noreturn
        previous.used = previous.used or current.used
        previous.unused = previous.unused or current.unused
        previous.always_inline = previous.always_inline or current.always_inline
        previous.noinline = previous.noinline or current.noinline
        if previous.always_inline and previous.noinline:
            raise TypeError(
                "always_inline and noinline attributes conflict for '%s'"
                % previous.name
            )
        previous.deprecated = previous.deprecated or current.deprecated
        if current.error_message is not None:
            previous.error_message = current.error_message
        if current.warning_message is not None:
            previous.warning_message = current.warning_message
        previous.attributes.extend(current.attributes)
        return previous

    def new_ns(self, ns: str, inst: "CompileContext") -> "CompileContext":
        self.namespaces[ns] = inst
        # TODO: change to using set_parent like `new_scope` defined below
        inst.parent = self
        inst.default_alignment = self.default_alignment
        inst.name_mangling_mode = self.name_mangling_mode
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

    def pretty_repr(self, pretty_repr_ctx=None):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.name,
                self.parent,
                self.default_alignment,
                self.name_mangling_mode,
                self.scopes,
                self.types,
                self.namespaces,
                self.vars,
            ),
            pretty_repr_ctx,
        )


from .VarDeclMods import VarDeclMods
from .is_fn_type import is_fn_type
from .ContextVariable import ContextVariable
from .qual_atomic_type_util import compare_no_cvr
from .OverloadedCtxVar import OverloadedCtxVar
from .LocalScope import LocalScope
from .BaseType import BaseType, TypeClass
