from enum import Enum
from typing import Dict, List, Optional, Tuple, TypeVar, Union
from .BaseType import BaseType, TypeClass
from ..constants import BASE_TYPE_MODS
from ...PrettyRepr import PrettyRepr, format_pretty, get_pretty_repr
from ..stmnt.BaseStmnt import BaseStmnt, STMNT_KEY_TO_ID, StmntType


class ContextMember(object):
    def __init__(self, name: str, parent: Optional["CompileContext"]):
        self.name = name
        self.parent = parent

    def get_full_name(self):
        if self.parent is None:
            return self.name
        return "%s::%s" % (self.parent.get_full_name(), self.name)

    def get_scope_name(self):
        if self.parent is None or not self.parent.is_local_scope():
            return self.name
        return "%s::%s" % (self.parent.get_scope_name(), self.name)

    def is_var(self):
        return not (self.is_type() or self.is_scopeable() or self.is_local_scope())

    def is_scopeable(self):
        return self.is_namespace() or self.is_class()

    def is_type(self):
        return False

    def is_class(self):
        return False

    def is_namespace(self):
        return False

    def is_local_scope(self):
        return False

    def get_underlying_type(self):
        # TODO: fix this so that structs/unions/classes will directly handle this (important)
        if isinstance(self, BaseType):
            return self
        return None


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


class PrimitiveTypeId(Enum):
    INT_I = 0
    INT_L = 1
    INT_LL = 2
    INT_S = 3
    INT_C = 4
    INT_C16 = 5
    INT_C32 = 6
    INT_WC = 7
    FLT_F = 8
    FLT_D = 9
    FLT_LD = 10
    TYP_BOOL = 11
    TYP_VOID = 12
    TYP_AUTO = 13


LST_TYPE_CODES = [
    "INT_I",
    "INT_L",
    "INT_LL",
    "INT_S",
    "INT_C",
    "INT_C16",
    "INT_C32",
    "INT_WC",
    "FLT_F",
    "FLT_D",
    "FLT_LD",
    "TYP_BOOL",
    "TYP_VOID",
    "TYP_AUTO",
]
INT_TYPE_CODES = [
    PrimitiveTypeId.INT_I,
    PrimitiveTypeId.INT_L,
    PrimitiveTypeId.INT_LL,
    PrimitiveTypeId.INT_S,
    PrimitiveTypeId.INT_C,
    PrimitiveTypeId.INT_C16,
    PrimitiveTypeId.INT_C32,
    PrimitiveTypeId.INT_WC,
    PrimitiveTypeId.TYP_BOOL,
]
FLT_TYPE_CODES = [PrimitiveTypeId.FLT_F, PrimitiveTypeId.FLT_D, PrimitiveTypeId.FLT_LD]
# TODO: TYP_FN = ?
SIZE_SIGN_MAP = {
    # k: (Size, Sign)
    PrimitiveTypeId.INT_I: (4, True),
    PrimitiveTypeId.INT_L: (4, True),
    PrimitiveTypeId.INT_LL: (8, True),
    PrimitiveTypeId.INT_S: (2, True),
    PrimitiveTypeId.INT_C: (1, False),
    PrimitiveTypeId.INT_C16: (2, False),
    PrimitiveTypeId.INT_C32: (4, False),
    PrimitiveTypeId.INT_WC: (2, False),
    PrimitiveTypeId.FLT_F: (4, True),
    PrimitiveTypeId.FLT_D: (8, True),
    PrimitiveTypeId.FLT_LD: (16, True),
    PrimitiveTypeId.TYP_BOOL: (1, False),
    PrimitiveTypeId.TYP_VOID: (0, False),
    PrimitiveTypeId.TYP_AUTO: (0, False),
}


set_pt_int_mods = {"short", "long"}
dct_pt_s_type_codes = {
    "int": PrimitiveTypeId.INT_I,
    "float": PrimitiveTypeId.FLT_F,
    "double": PrimitiveTypeId.FLT_D,
    "void": PrimitiveTypeId.TYP_VOID,
    "auto": PrimitiveTypeId.TYP_AUTO,
    "char": PrimitiveTypeId.INT_C,
    "char16_t": PrimitiveTypeId.INT_C16,
    "char32_t": PrimitiveTypeId.INT_C32,
    "wchar_t": PrimitiveTypeId.INT_WC,
    "bool": PrimitiveTypeId.TYP_BOOL,
}


class PrimitiveType(BaseType):
    def get_expr_arg_type(self, expr):
        """
        :param BaseExpr expr:
        :rtype: BaseExpr
        """
        raise NotImplementedError("Not Implemented")

    type_class_id = TypeClass.PRIM
    # Takes lists like (does not take access specifiers
    # for LL, L, C, WC, C16, C32, S: int is optional
    #   ["unsigned", "long", "long", "int"] -> Sign=False, Size=LL_Sz
    #   ["unsigned", "long", "long"] --------> Sign=False, Size=LL_Sz
    #   ["unsigned", "long", "int"] ---------> Sign=False, Size=L_Sz
    #   ["unsigned", "char", "int"] ---------> Sign=False, Size=C_Sz
    #   ["unsigned", "char"] ----------------> Sign=False, Size=C_Sz
    #   ["unsigned", "long"] ----------------> Sign=False, Size=L_Sz
    #   ["unsigned", "int"] -----------------> Sign=False, Size=I_Sz
    #   ["signed", "long", "long", "int"] ---> Sign=True,  Size=LL_Sz
    #   ["signed", "long", "long"] ----------> Sign=True,  Size=LL_Sz
    #   ["signed", "long", "int"] -----------> Sign=True,  Size=L_Sz
    #   ["signed", "char", "int"] -----------> Sign=True,  Size=C_Sz
    #   ["signed", "char"] ------------------> Sign=True,  Size=C_Sz
    #   ["signed", "long"] ------------------> Sign=True,  Size=L_Sz
    #   ["signed", "int"] -------------------> Sign=True,  Size=I_Sz
    #   ["long", "long", "int"] -------------> Sign=True,  Size=LL_Sz
    #   ["long", "long"] --------------------> Sign=True,  Size=LL_Sz
    #   ["char", "int"] ---------------------> Sign=CSIGN, Size=C_Sz
    #   ["long", "int"] ---------------------> Sign=True,  Size=L_Sz
    #   ["char"] ----------------------------> Sign=CSIGN, Size=C_Sz
    #   ["long"] ----------------------------> Sign=True,  Size=L_Sz
    #   ["int"] -----------------------------> Sign=True,  Size=I_Sz

    @classmethod
    def get_size_l_type(cls, is_sign=False):
        return PrimitiveType.from_type_code(
            PrimitiveTypeId.INT_LL, -1 if is_sign else 1
        )

    lst_user_str_map = {
        PrimitiveTypeId.INT_I: ["int"],
        PrimitiveTypeId.INT_L: ["long"],
        PrimitiveTypeId.INT_LL: ["long", "long"],
        PrimitiveTypeId.INT_S: ["short"],
        PrimitiveTypeId.INT_C: ["char"],
        PrimitiveTypeId.INT_C16: ["char16_t"],
        PrimitiveTypeId.INT_C32: ["char32_t"],
        PrimitiveTypeId.INT_WC: ["wchar_t"],
        PrimitiveTypeId.FLT_F: ["float"],
        PrimitiveTypeId.FLT_D: ["double"],
        PrimitiveTypeId.FLT_LD: ["long", "double"],
        PrimitiveTypeId.TYP_BOOL: ["bool"],
        PrimitiveTypeId.TYP_VOID: ["void"],
        PrimitiveTypeId.TYP_AUTO: ["auto"],
    }
    mangle_captures = {
        "v": (PrimitiveTypeId.TYP_VOID, 0),
        "b": (PrimitiveTypeId.TYP_BOOL, 0),
        "w": (PrimitiveTypeId.INT_WC, 1),  # gcc calls it plain old wchar_t
        "h": (PrimitiveTypeId.INT_WC, -1),  # gcc calls it unsigned char
        "a": (PrimitiveTypeId.INT_C, -1),
        "c": (PrimitiveTypeId.INT_C, 1),  # gcc calls it plain old char
        "s": (PrimitiveTypeId.INT_S, -1),
        "t": (PrimitiveTypeId.INT_S, 1),
        "i": (PrimitiveTypeId.INT_I, -1),
        "j": (PrimitiveTypeId.INT_I, 1),
        "l": (PrimitiveTypeId.INT_L, -1),
        "m": (PrimitiveTypeId.INT_L, 1),
        "x": (PrimitiveTypeId.INT_LL, -1),
        "y": (PrimitiveTypeId.INT_LL, 1),
        # "n": ["__int128"],
        # "o": ["unsigned", "__int128"],
        # "e": ["short", "float"], # gcc __float80, but here is __float16
        "f": (PrimitiveTypeId.FLT_F, 0),
        "d": (PrimitiveTypeId.FLT_D, 0),
        "g": (PrimitiveTypeId.FLT_LD, 0),  # __float128
        "D": None,
        "Ds": (PrimitiveTypeId.INT_C16, -1),
        "Dt": (PrimitiveTypeId.INT_C16, 1),
        "Di": (PrimitiveTypeId.INT_C32, -1),
        "Dj": (PrimitiveTypeId.INT_C32, 1),
    }
    inv_mangle_captures = {
        (PrimitiveTypeId.INT_I, True): "i",
        (PrimitiveTypeId.INT_I, False): "j",
        (PrimitiveTypeId.INT_L, True): "l",
        (PrimitiveTypeId.INT_L, False): "m",
        (PrimitiveTypeId.INT_LL, True): "x",
        (PrimitiveTypeId.INT_LL, False): "y",
        (PrimitiveTypeId.INT_S, True): "s",
        (PrimitiveTypeId.INT_S, False): "t",
        (PrimitiveTypeId.INT_C, True): "a",
        (PrimitiveTypeId.INT_C, False): "c",
        (PrimitiveTypeId.INT_C16, True): "Ds",
        (PrimitiveTypeId.INT_C16, False): "Dt",
        (PrimitiveTypeId.INT_C32, True): "Di",
        (PrimitiveTypeId.INT_C32, False): "Dj",
        (PrimitiveTypeId.INT_WC, False): "w",
        (PrimitiveTypeId.INT_WC, True): "h",
        (PrimitiveTypeId.FLT_F, True): "f",
        (PrimitiveTypeId.FLT_D, True): "d",
        (PrimitiveTypeId.FLT_LD, True): "g",
        (PrimitiveTypeId.TYP_BOOL, False): "b",
        (PrimitiveTypeId.TYP_VOID, False): "v",
    }

    @classmethod
    def from_mangle(cls, s: str, c: int) -> Tuple["PrimitiveType", int]:
        code = ""
        while s[c].isupper() and c < len(s):
            code += s[c]
            c += 1
        code += s[c]
        c += 1
        typ, signed = cls.mangle_captures[code]
        return PrimitiveType.from_type_code(typ, signed), c

    def to_mangle_str(self, top_decl: bool = False):
        return PrimitiveType.inv_mangle_captures[(self.typ, self.sign)]

    @classmethod
    def from_str_name(cls, str_name: List[str]) -> "PrimitiveType":
        signed = 0
        lst_int_mods = []
        typ = None
        for s in str_name:
            if s in BASE_TYPE_MODS:
                if signed == 0:
                    signed = -1 if s == "signed" else 1
                else:
                    raise SyntaxError("Cannot specify more than one signed specifier")
            elif s in dct_pt_s_type_codes:
                if typ is not None:
                    raise SyntaxError(
                        "Cannot use more than one single type: '%s' and '%s'" % (typ, s)
                    )
                typ = dct_pt_s_type_codes[s]
            elif s in set_pt_int_mods:
                lst_int_mods.append(s)
            else:
                raise SyntaxError("Unexpected Token '%s'" % s)
        if typ is None:
            typ = PrimitiveTypeId.INT_I
        if signed != 0 and (
            typ == PrimitiveTypeId.TYP_BOOL or typ not in INT_TYPE_CODES
        ):
            raise SyntaxError(
                "Unexpected signed specifier for %s" % LST_TYPE_CODES[typ]
            )
        for IntMod in lst_int_mods:
            if IntMod == "long":
                if typ == PrimitiveTypeId.INT_I:
                    typ = PrimitiveTypeId.INT_L
                elif typ == PrimitiveTypeId.INT_L:
                    typ = PrimitiveTypeId.INT_LL
                elif typ == PrimitiveTypeId.FLT_D:
                    typ = PrimitiveTypeId.FLT_LD
                else:
                    raise SyntaxError(
                        "Unexpected int modifier '%s' for %s"
                        % (IntMod, LST_TYPE_CODES[typ])
                    )
            elif IntMod == "short":
                if typ == PrimitiveTypeId.INT_I:
                    typ = PrimitiveTypeId.INT_S
                else:
                    raise SyntaxError(
                        "Unexpected int modifier '%s' for %s"
                        % (IntMod, LST_TYPE_CODES[typ])
                    )
        return cls.from_type_code(typ, signed)

    @classmethod
    def from_type_code(cls, typ: PrimitiveTypeId, signed: int = 0) -> "PrimitiveType":
        """
        :param signed: -1, 0 or 1 representing the signed-ness
        """
        size, sign = SIZE_SIGN_MAP[typ]
        if signed != 0:
            if typ in FLT_TYPE_CODES or typ in [
                PrimitiveTypeId.TYP_VOID,
                PrimitiveTypeId.TYP_BOOL,
            ]:
                raise TypeError(
                    "Cannot Explicitly specify the signed-ness for Type=%s"
                    % LST_TYPE_CODES[typ]
                )
            sign = signed < 0
        # str_name = cls.mangle_captures[cls.inv_mangle_captures[(typ, sign)]]
        return PrimitiveType(typ, sign)

    def to_user_str(self):
        return " ".join(self.get_str_name())

    def get_ctor_fn_types(self):
        return [make_void_fn(x) for x in [[], [self]]]

    def __init__(self, typ: PrimitiveTypeId, sign: bool):
        self.sign = sign
        self.typ = typ
        self.size = SIZE_SIGN_MAP[typ][0]

    def get_str_name(self, short=True):
        assert short
        lst = list(PrimitiveType.lst_user_str_map[self.typ])
        if self.sign != SIZE_SIGN_MAP[self.typ][1]:
            lst.insert(0, "signed" if self.sign else "unsigned")
        return lst

    def pretty_repr(self):
        return ["PrimitiveType", ".", "from_type_code", "("] + [
            "PrimitiveTypeId",
            ".",
            self.typ.name,
            ",",
            "0"
            if SIZE_SIGN_MAP[self.typ][1] == self.sign
            else ("-1" if self.sign else "1"),
            ")",
        ]

    def compile_var_init(
        self,
        cmpl_obj: "BaseCmplObj",
        init_args: List[Union["BaseExpr", "CurlyStmnt"]],
        context: "CompileContext",
        ref: "VarRef",
        cmpl_data: Optional["LocalCompileData"] = None,
        temp_links: Optional[List[Tuple[BaseType, "BaseLink"]]] = None,
    ):
        # TODO: result allocation for temp links of expressions used as init_args
        # actually maybe not
        sz_var = size_of(self)
        if sz_var == 0:
            print("SizeOf(%s) == 0" % get_user_str_from_type(self))
        if ref.ref_type == VAR_REF_TOS_NAMED:
            assert isinstance(ref, VarRefTosNamed)
            ctx_var = ref.ctx_var
            name = None
            is_local = True
            if ctx_var is not None:
                assert isinstance(ctx_var, ContextVariable)
                name = ctx_var.get_link_name()
                is_local = ctx_var.parent.is_local_scope()
            if len(init_args) > 1:
                raise TypeError(
                    "Cannot instantiate primitive types with more than one argument"
                )
            if is_local:
                assert (
                    cmpl_data is not None
                ), "Expected cmpl_data to not be None for LOCAL"
                if len(init_args) == 0:
                    sz_cls = emit_load_i_const(cmpl_obj.memory, sz_var, False)
                    cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
                else:
                    expr = init_args[0]
                    typ = expr.t_anot
                    src_pt = get_base_prim_type(typ)
                    src_vt = get_value_type(src_pt)
                    assert compare_no_cvr(self, src_vt), "self = %s, SrvVT = %s" % (
                        get_user_str_from_type(self),
                        get_user_str_from_type(src_vt),
                    )
                    sz = compile_expr(
                        cmpl_obj, expr, context, cmpl_data, src_pt, temp_links
                    )
                    if src_pt is src_vt:
                        assert sz == sz_var
                    else:
                        assert sz == 8
                        sz_cls = sz_var.bit_length() - 1
                        assert sz_var == (1 << sz_cls)
                        cmpl_obj.memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])
                if ctx_var is not None:
                    cmpl_data.put_local(ctx_var, name, sz_var, None, True)
            else:
                assert cmpl_data is None, "Expected cmpl_data to be None for GLOBAL"
                assert isinstance(cmpl_obj, Compilation)
                assert ctx_var is not None
                assert isinstance(ctx_var, ContextVariable)
                assert name is not None
                cmpl_obj1 = cmpl_obj.spawn_compile_object(
                    CompileObjectType.GLOBAL, name
                )
                cmpl_obj1.memory.extend([0] * sz_var)
                if len(init_args) == 1:
                    link = cmpl_obj.get_link(name)
                    src_pt = get_base_prim_type(init_args[0].t_anot)
                    src_vt = get_value_type(src_pt)
                    err0 = "Expected Expression sz == %s, but %u != %u (name = %r, linkName = '%s', expr = %r)"
                    if src_pt is src_vt:
                        sz = compile_expr(
                            cmpl_obj,
                            init_args[0],
                            context,
                            cmpl_data,
                            src_vt,
                            temp_links,
                        )
                        assert sz == sz_var, err0 % (
                            "sz_var",
                            sz,
                            sz_var,
                            ctx_var.name,
                            name,
                            init_args[0],
                        )
                    else:
                        sz = compile_expr(
                            cmpl_obj,
                            init_args[0],
                            context,
                            cmpl_data,
                            src_pt,
                            temp_links,
                        )
                        assert sz == 8, err0 % (
                            "sizeof(void*)",
                            sz,
                            8,
                            ctx_var.name,
                            name,
                            init_args[0],
                        )
                        sz_cls = sz_var.bit_length() - 1
                        assert sz_var == 1 << sz_cls
                        cmpl_obj.memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])
                    link.emit_stor(
                        cmpl_obj.memory, sz_var, cmpl_obj, byte_copy_cmpl_intrinsic
                    )
            return sz_var
        elif ref.ref_type == VAR_REF_LNK_PREALLOC:
            assert isinstance(ref, VarRefLnkPrealloc)
            if len(init_args) == 0:
                return sz_var
            link = ref.lnk
            sz = compile_expr(
                cmpl_obj,
                CastOpExpr(self, init_args[0], CastType.IMPLICIT),
                context,
                cmpl_data,
            )
            assert sz == sz_var
            link.emit_stor(cmpl_obj.memory, sz_var, cmpl_obj, byte_copy_cmpl_intrinsic)
            return sz_var
        else:
            raise TypeError("Unrecognized VarRef: %s" % repr(ref))

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        return -1

    def compile_conv(
        self,
        cmpl_obj: "BaseCmplObj",
        expr: "BaseExpr",
        context: "CompileContext",
        cmpl_data: Optional["LocalCompileData"] = None,
        temp_links: Optional[List[Tuple["BaseType", "BaseLink"]]] = None,
    ):
        from_type = get_value_type(expr.t_anot)
        err_msg = "error with expression type and size"
        err_msg += "\n  sz = %u\n  size_of(from_type) = %u\n  expr = %s\n  from_type = %s\n  self = %s"
        sz = compile_expr(cmpl_obj, expr, context, cmpl_data, from_type, temp_links)
        assert sz == size_of(from_type), err_msg % (
            sz,
            size_of(from_type),
            format_pretty(expr).replace("\n", "\n  "),
            format_pretty(from_type).replace("\n", "\n  "),
            format_pretty(self).replace("\n", "\n  "),
        )
        sz_cls = self.size.bit_length() - 1
        if 1 << sz_cls != self.size or sz_cls > 3:
            raise TypeError("Bad Primitive Type Size: %u for %r" % (self.size, self))
        if self.typ in INT_TYPE_CODES:
            out_bits = sz_cls << 1
            out_bits |= int(self.sign)
        elif self.typ in FLT_TYPE_CODES:
            sz_cls -= 1
            out_bits = sz_cls | 0x08
        else:
            raise TypeError("Cannot cast to Type %s" % repr(self))
        if from_type.type_class_id == TypeClass.PRIM:
            assert isinstance(from_type, PrimitiveType)
            if from_type.typ in INT_TYPE_CODES:
                sz_cls = from_type.size.bit_length() - 1
                if 1 << sz_cls != from_type.size or sz_cls > 3:
                    raise TypeError(
                        "Bad Primitive Type Size: %u for %r"
                        % (from_type.size, from_type)
                    )
                inp_bits = sz_cls << 1
                inp_bits |= int(from_type.sign)
            elif from_type.typ in FLT_TYPE_CODES:
                sz_cls = from_type.size.bit_length() - 2
                inp_bits = sz_cls | 0x08
            else:
                raise TypeError("Cannot cast from Type %s" % repr(from_type))
        elif from_type.type_class_id == TypeClass.QUAL:
            assert isinstance(from_type, QualType)
            if from_type.qual_id == QualType.QUAL_PTR:
                assert sz == 8
                inp_bits = 0x06
            else:
                raise TypeError("Cannot cast from Type %s" % repr(from_type))
        else:
            raise TypeError("Cannot cast from Type %s" % repr(from_type))

        if self.typ == PrimitiveTypeId.TYP_BOOL:
            emit_load_i_const(cmpl_obj.memory, 0, False, 0)
            cmpl_obj.memory.extend(
                [
                    BC_CONV,
                    (
                        inp_bits << 4
                    ),  # input bits (for this BC_CONV, not inp_bits) are all zero
                    BC_NOP,
                    BC_NE0,
                ]
            )
            code = (BC_FCMP_2 if inp_bits & 0x08 else BC_CMP1) + (inp_bits & 0x7)
            assert BC_FCMP_2 <= code <= BC_FCMP_16 or BC_CMP1 <= code <= BC_CMP8S, (
                "GOT: %u" % code
            )
            cmpl_obj.memory[-2] = code
        else:
            cmpl_obj.memory.extend([BC_CONV, inp_bits | (out_bits << 4)])
        return self.size


void_t = PrimitiveType.from_type_code(PrimitiveTypeId.TYP_VOID)
int_types = [
    PrimitiveType.from_str_name(x)
    for x in [
        ["unsigned", "char"],
        ["signed", "char"],
        ["unsigned", "short"],
        ["signed", "short"],
        ["unsigned", "char16_t"],
        ["signed", "char16_t"],
        ["unsigned", "int"],
        ["signed", "int"],
        ["unsigned", "char32_t"],
        ["signed", "char32_t"],
        ["unsigned", "wchar_t"],
        ["signed", "wchar_t"],
        ["unsigned", "long"],
        ["signed", "long"],
        ["unsigned", "long", "long"],
        ["signed", "long", "long"],
        ["bool"],
    ]
]
signed_num_types = [
    PrimitiveType.from_str_name(x)
    for x in [
        ["signed", "char"],
        ["signed", "short"],
        ["signed", "char16_t"],
        ["signed", "int"],
        ["signed", "char32_t"],
        ["signed", "wchar_t"],
        ["signed", "long"],
        ["signed", "long", "long"],
        ["float"],
        ["double"],
        ["long", "double"],
    ]
]
bool_t = int_types[-1]
prim_types = int_types + [
    PrimitiveType.from_str_name(x) for x in [["float"], ["double"], ["long", "double"]]
]
size_l_t = PrimitiveType.get_size_l_type()
snz_l_t = PrimitiveType.get_size_l_type(True)


class ClassType(CompileContext, BaseType):
    def to_user_str(self):
        raise NotImplementedError("Not Implemented")

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_var_init(
        self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None
    ):
        raise NotImplementedError("Not Implemented")

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TypeClass.CLASS
    mangle_captures = {"K": None}

    @classmethod
    def from_mangle(cls, s: str, c: int) -> Tuple["ClassType", int]:
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return ClassType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl: bool = False) -> str:
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "K%u%s" % (len(name), name)

    def __init__(
        self,
        parent: Optional["CompileContext"],
        name: Optional[str] = None,
        incomplete: bool = True,
        definition: Dict[str, int] = None,
        var_order: List["ContextVariable"] = None,
        defined: bool = False,
        the_base_type: Optional["BaseType"] = None,
    ):
        super(ClassType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.var_order = [] if var_order is None else var_order
        self.defined = defined
        self.the_base_type = the_base_type

    def offset_of(self, attr: str) -> int:
        # TODO: improve speed of OffsetOf by tracking the offsets along-side the types
        index = self.definition[attr]
        off = 0
        for c in range(index):
            off += size_of(self.var_order[0].typ)
        return off

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.parent,
                self.name,
                self.incomplete,
                self.definition,
                self.var_order,
                self.defined,
                self.the_base_type,
            )
        )

    def merge_to(self, other: "ClassType"):
        assert isinstance(other, ClassType)
        super(ClassType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.var_order = self.var_order
        other.defined = self.defined
        other.the_base_type = self.the_base_type

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            c += 1
            self.the_base_type, c = get_base_type(tokens, c, end, context)
            if self.the_base_type is None:
                raise ParsingError(
                    tokens, c, "Expected a Type to follow ':' in class declaration"
                )
        if tokens[c].str == "{":
            c += 1
            lvl = 1
            start = c
            while c < end and lvl > 0:
                s = tokens[c].str
                if s in OPEN_GROUPS:
                    lvl += 1
                elif s in CLOSE_GROUPS:
                    lvl -= 1
                c += 1
            if lvl > 0:
                raise ParsingError(tokens, start, "Expected closing '}' for class")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].str in {"public", "private", "protected"}:
                    # TODO: IDEA: store a current access specifier variable
                    # TODO:   then combine that with inst in the definition of function: 'NewVar(self, V, inst)'
                    raise ParsingError(
                        tokens, c, "access specifier keywords not allowed"
                    )
                stmnt, c = get_strict_stmnt(tokens, c, end_p, self)
            c = end_t
            self.defined = True
            self.incomplete = False
        return c

    def new_var(self, v: str, inst: "ContextVariable") -> "ContextVariable":
        if inst.mods == VarDeclMods.STATIC:
            return super(ClassType, self).new_var(v, inst)
        self.definition[v] = len(self.var_order)
        self.var_order.append(inst)
        return inst

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


class StructType(CompileContext, BaseType):
    def to_user_str(self) -> str:
        return "struct " + self.name

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TypeClass.STRUCT
    mangle_captures = {"B": None}

    @classmethod
    def from_mangle(cls, s: str, c: int) -> Tuple["StructType", int]:
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return StructType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl: bool = False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "B%u%s" % (len(name), name)

    def __init__(
        self,
        parent: Optional["CompileContext"],
        name: Optional[str] = None,
        incomplete: bool = True,
        definition: Dict[str, int] = None,
        var_order: List["ContextVariable"] = None,
        defined: bool = False,
        the_base_type: Optional["BaseType"] = None,
    ):
        super(StructType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.var_order = [] if var_order is None else var_order
        self.defined = defined
        self.the_base_type = the_base_type

    def offset_of(self, attr: str) -> int:
        # TODO: improve speed of OffsetOf by tracking the offsets along-side the types
        index = self.definition[attr]
        off = 0
        for c in range(index):
            off += size_of(self.var_order[0].typ)
        return off

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.parent,
                self.name,
                self.incomplete,
                self.definition,
                self.var_order,
                self.defined,
                self.the_base_type,
            )
        )

    def merge_to(self, other):
        assert isinstance(other, StructType)
        super(StructType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.var_order = self.var_order
        other.defined = self.defined
        other.the_base_type = self.the_base_type

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            c += 1
            self.the_base_type, c = get_base_type(tokens, c, end, context)
            if self.the_base_type is None:
                raise ParsingError(
                    tokens, c, "Expected a Type to follow ':' in class declaration"
                )
        if tokens[c].str == "{":
            c += 1
            lvl = 1
            start = c
            while c < end and lvl > 0:
                s = tokens[c].str
                if s in OPEN_GROUPS:
                    lvl += 1
                elif s in CLOSE_GROUPS:
                    lvl -= 1
                c += 1
            if lvl > 0:
                raise ParsingError(tokens, start, "Expected closing '}' for struct")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].str in {"public", "private", "protected"}:
                    # TODO: IDEA: store a current access specifier variable
                    # TODO:   then combine that with inst in the definition of function: 'NewVar(self, V, inst)'
                    raise ParsingError(
                        tokens, c, "access specifier keywords not allowed"
                    )
                try:
                    stmnt, c = get_strict_stmnt(tokens, c, end_p, self)
                except ParsingError:
                    print("self.name = " + repr(self.name))
                    raise
            c = end_t
            self.defined = True
            self.incomplete = False
        return c

    def compile_var_init(
        self,
        cmpl_obj: "BaseCmplObj",
        init_args: List[Union["BaseExpr", "CurlyStmnt"]],
        context: "CompileContext",
        ref: "VarRef",
        cmpl_data: Optional["LocalCompileData"] = None,
        temp_links: Optional[Tuple["BaseType", "BaseLink"]] = None,
    ):
        if self.incomplete:
            raise TypeError("struct %s is incomplete" % self.name)
        link = None
        name = None
        ctx_var = None
        is_local = True
        sz_var = size_of(self)
        if ref.ref_type == VAR_REF_TOS_NAMED:
            assert isinstance(ref, VarRefTosNamed)
            ctx_var = ref.ctx_var
            if ctx_var is not None:
                assert isinstance(ctx_var, ContextVariable)
                name = ctx_var.get_link_name()
                is_local = ctx_var.parent.is_local_scope()
                if not is_local:
                    assert isinstance(cmpl_obj, Compilation)
                    cmpl_obj1 = cmpl_obj.spawn_compile_object(
                        CompileObjectType.GLOBAL, name
                    )
                    cmpl_obj1.memory.extend([0] * sz_var)
                    link = cmpl_obj.get_link(name)
        elif ref.ref_type == VAR_REF_LNK_PREALLOC:
            assert isinstance(ref, VarRefLnkPrealloc)
            if len(init_args) == 0:
                return sz_var
            link = ref.lnk
        else:
            raise TypeError("Unrecognized VarRef: %s" % repr(ref))
        if len(init_args) > 1:
            raise TypeError(
                "Cannot instantiate struct types with more than one argument"
            )
        if link is None:
            assert is_local
            assert cmpl_data is not None, "Expected cmpl_data to not be None for LOCAL"
            if len(init_args) == 0:
                sz_cls = emit_load_i_const(cmpl_obj.memory, sz_var, False)
                cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
            else:
                expr = init_args[0]
                typ = expr.t_anot
                src_pt, src_vt, is_src_ref = get_tgt_ref_type(typ)
                assert compare_no_cvr(self, src_vt), "self = %s, SrvVT = %s" % (
                    get_user_str_from_type(self),
                    get_user_str_from_type(src_vt),
                )
                sz = compile_expr(
                    cmpl_obj, expr, context, cmpl_data, src_pt, temp_links
                )
                if is_src_ref:
                    assert sz == 8
                    sz_cls = sz_var.bit_length() - 1
                    assert sz_var == (1 << sz_cls)
                    cmpl_obj.memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])
                else:
                    assert sz == sz_var
            if ctx_var is not None:
                cmpl_data.put_local(ctx_var, name, sz_var, None, True)
        else:
            assert cmpl_data is None, "Expected cmpl_data to be None for GLOBAL"
            assert isinstance(cmpl_obj, Compilation)
            assert ctx_var is None or isinstance(ctx_var, ContextVariable)
            var_name = "<NONE>" if ctx_var is None else ctx_var.name
            assert name is not None
            if len(init_args):
                src_pt, src_vt, is_src_ref = get_tgt_ref_type(init_args[0].t_anot)
                err0 = "Expected Expression sz == %s, but %u != %u (name = %r, linkName = '%s', expr = %r)"
                if is_src_ref:
                    sz = compile_expr(
                        cmpl_obj, init_args[0], context, cmpl_data, src_pt, temp_links
                    )
                    assert sz == 8, err0 % (
                        "sizeof(void*)",
                        sz,
                        8,
                        var_name,
                        name,
                        init_args[0],
                    )
                    sz_cls = sz_var.bit_length() - 1
                    assert sz_var == 1 << sz_cls
                    cmpl_obj.memory.extend([BC_LOAD, BCR_ABS_S8 | (sz_cls << 5)])
                else:
                    sz = compile_expr(
                        cmpl_obj, init_args[0], context, cmpl_data, src_vt, temp_links
                    )
                    assert sz == sz_var, err0 % (
                        "sz_var",
                        sz,
                        sz_var,
                        var_name,
                        name,
                        init_args[0],
                    )
                link.emit_stor(
                    cmpl_obj.memory, sz_var, cmpl_obj, byte_copy_cmpl_intrinsic
                )
        return sz_var

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        return -1

    def new_var(self, v: str, inst: "ContextVariable") -> "ContextVariable":
        if inst.mods == VarDeclMods.STATIC:
            return super(StructType, self).new_var(v, inst)
        self.definition[v] = len(self.var_order)
        self.var_order.append(inst)
        return inst

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


class EnumType(CompileContext, BaseType):
    def to_user_str(self):
        raise NotImplementedError("Not Implemented")

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TypeClass.ENUM
    mangle_captures = {"E": None}

    @classmethod
    def from_mangle(cls, s: str, c: int) -> Tuple["EnumType", int]:
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return EnumType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl=False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "E%u%s" % (len(name), name)

    def __init__(
        self,
        parent: Optional["CompileContext"],
        name: Optional[str] = None,
        incomplete: bool = True,
        variables: Dict[str, "ContextVariable"] = None,
        defined: bool = False,
        the_base_type: Optional["BaseType"] = None,
    ):
        super(EnumType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.the_base_type = the_base_type
        if variables is not None:
            self.vars.update(variables)
        self.defined = defined

    def compile_var_init(
        self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None
    ):
        return self.the_base_type.compile_var_init(
            cmpl_obj, init_args, context, ref, cmpl_data, temp_links
        )

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.parent,
                self.name,
                self.incomplete,
                self.vars,
                self.defined,
                self.the_base_type,
            )
        )

    def merge_to(self, other):
        assert isinstance(other, EnumType)
        super(EnumType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.the_base_type = self.the_base_type
        other.defined = self.defined

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        # TODO: (mentioned later in this function)
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            c += 1
            self.the_base_type, c = get_base_type(tokens, c, end, context)
            if self.the_base_type is None:
                raise ParsingError(
                    tokens, c, "Expected a Type to follow ':' in enum declaration"
                )
        if tokens[c].str == "{":
            c += 1
            lvl = 1
            start = c
            while c < end and lvl > 0:
                s = tokens[c].str
                if s in OPEN_GROUPS:
                    lvl += 1
                elif s in CLOSE_GROUPS:
                    lvl -= 1
                c += 1
            if lvl > 0:
                raise ParsingError(tokens, c, "Expected closing '}' for enum")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].type_id == TokenType.NAME:
                    name = tokens[c].str
                    if self.has_var_strict(name):
                        raise ParsingError(
                            tokens, c, "Redefinition of enumerated name: '%s'" % name
                        )
                    expr, c = get_expr(tokens, c, ",", end_p, context)
                    self.new_var(
                        name, ContextVariable(name, self.the_base_type).const_init(expr)
                    )
                    # TODO: assert ConstExpr
                else:
                    raise ParsingError(
                        tokens, c, "Expected type_id=TokenType.NAME Token in enum"
                    )
                c += 1
            c = end_t
            self.defined = True
            self.incomplete = False
        return c

    def is_namespace(self):
        return False

    def is_type(self):
        return True


class UnionType(CompileContext, BaseType):
    def to_user_str(self):
        raise NotImplementedError("Not Implemented")

    def get_ctor_fn_types(self):
        raise NotImplementedError("Not Implemented")

    def compile_var_init(
        self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None
    ):
        raise NotImplementedError("Not Implemented")

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None):
        raise NotImplementedError("Not Implemented")

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        raise NotImplementedError("Not Implemented")

    def get_expr_arg_type(self, expr):
        raise NotImplementedError("Not Implemented")

    type_class_id = TypeClass.UNION
    mangle_captures = {"U": None}

    @classmethod
    def from_mangle(cls, s: str, c: int) -> Tuple["UnionType", int]:
        c += 1
        start = c
        while s[c].isdigit() and c < len(s):
            c += 1
        num_ch = int(s[start:c])
        start = c
        c += num_ch
        return UnionType(None, "::" + s[start:c].replace("@", "::")), c

    def to_mangle_str(self, top_decl: bool = False):
        name = self.get_full_name().replace("::", "@")
        if name.startswith("@"):
            name = name[1:]
        return "U%u%s" % (len(name), name)

    def __init__(
        self,
        parent: Optional["CompileContext"],
        name: Optional[str] = None,
        incomplete: bool = True,
        definition: Optional[Dict[str, "ContextVariable"]] = None,
        defined: bool = False,
        the_base_type: Optional["BaseType"] = None,
    ):
        super(UnionType, self).__init__(name, parent)
        self.incomplete = incomplete
        self.definition = {} if definition is None else definition
        self.defined = defined
        self.the_base_type = the_base_type

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (
                self.parent,
                self.name,
                self.incomplete,
                self.definition,
                self.defined,
                self.the_base_type,
            )
        )

    def merge_to(self, other: "UnionType"):
        assert isinstance(other, UnionType)
        super(UnionType, self).merge_to(other)
        other.incomplete = self.incomplete
        other.definition = self.definition
        other.defined = self.defined
        other.the_base_type = self.the_base_type

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        base_name, c = try_get_as_name(tokens, c, end, context)
        if base_name is not None:
            self.name = "".join(map(tok_to_str, base_name))
        if tokens[c].str == ":":
            raise ParsingError(tokens, c, "Inheritance is not allowed for unions")
        if tokens[c].str == "{":
            c += 1
            lvl = 1
            start = c
            while c < end and lvl > 0:
                s = tokens[c].str
                if s in OPEN_GROUPS:
                    lvl += 1
                elif s in CLOSE_GROUPS:
                    lvl -= 1
                c += 1
            if lvl > 0:
                raise ParsingError(tokens, start, "Expected closing '}' for union")
            end_t = c
            end_p = c - 1
            c = start
            while c < end_p:
                if tokens[c].str in {"public", "private", "protected"}:
                    # TODO: IDEA: store a current access specifier variable
                    # TODO:   then combine that with inst in the definition of function: 'NewVar(self, V, inst)'
                    raise ParsingError(
                        tokens, c, "access specifier keywords not allowed"
                    )
                stmnt, c = get_strict_stmnt(tokens, c, end_p, self)
            c = end_t
            self.defined = True
            self.incomplete = False
        return c

    def new_var(self, v: str, inst: "ContextVariable"):
        assert isinstance(inst, ContextVariable)
        if inst.mods == VarDeclMods.STATIC:
            super(UnionType, self).new_var(v, inst)
        else:
            self.definition[v] = inst

    def is_namespace(self):
        return False

    def is_type(self):
        return True

    def is_class(self):
        return True


def merge_type_context(
    typ: Union["EnumType", "ClassType", "UnionType", "StructType"],
    context: "CompileContext",
) -> Union["EnumType", "ClassType", "UnionType", "StructType", "ContextMember"]:
    other = context.type_name_strict(typ.name)
    assert other is None or isinstance(
        other, (ClassType, StructType, UnionType, EnumType)
    ), "Issue: %s is not a Composite Type" % repr(other)
    # TODO: account for other = typedef
    if other is None:
        if typ.defined:
            other = context.new_type(typ.name, typ)
        else:
            other = context.type_name(typ.name)
            if other is None:
                other = context.new_type(typ.name, typ)
    elif typ.defined and other.defined:
        raise NameError("Redefinition of Typename '%s' not allowed" % typ.name)
    elif typ.defined:
        typ.merge_to(other)
    return other


def get_base_type(
    tokens: List["Token"], c: int, end: int, context: "CompileContext"
) -> Tuple[Optional["BaseType"], int]:
    main_start = c
    str_name = []
    base_type = None
    is_prim = False
    while c < end:
        if tokens[c].type_id == TokenType.NAME and tokens[c].str in KEYWORDS:
            meta_type_type = -1
            try:
                meta_type_type = META_TYPE_LST.index(tokens[c].str)
            except ValueError:
                pass
            if meta_type_type != -1:
                c += 1
                cls = MetaTypeCtors[meta_type_type](context)
                c = cls.build(tokens, c, end, context)
                cls = merge_type_context(cls, context)
                assert cls is not None, "ISSUE with MergeType_Context"
                if base_type is None and not is_prim:
                    base_type = cls
                else:
                    # raise ParsingError(tokens, c, "Cannot specify different typenames as one type")
                    return None, main_start
            elif tokens[c].str == "typename":
                c += 1
                base_name, c = try_get_as_name(tokens, c, end, context)
                if base_name is None:
                    raise ParsingError(tokens, c, "Expected name after 'typename'")
                name = "".join(map(tok_to_str, base_name))
                cls = context.scoped_get(name)
                if not cls.is_type():
                    raise ParsingError(
                        tokens,
                        c,
                        "Expected a typename to follow 'typename', got %s" % name,
                    )
                if base_type is None and not is_prim:
                    base_type = cls.get_underlying_type()
                else:
                    raise ParsingError(
                        tokens, c, "Cannot specify different typenames as one type"
                    )
            elif tokens[c].str in PRIM_TYPE_WORDS:
                str_name.append(tokens[c].str)
                is_prim = True
                c += 1
            elif tokens[c].str in MODIFIERS:
                str_name.append(tokens[c].str)
                c += 1
            else:
                # raise ParsingError(tokens, c, "Keyword not allowed in declaration")
                return None, main_start
        else:
            start = c
            base_name, c = try_get_as_name(tokens, c, end, context)
            if base_name is None and base_type is None and not is_prim:
                # raise ParsingError(tokens, c, "Expected name after 'typename'")
                return None, main_start
            elif base_name is None:
                break
            elif is_prim or base_type is not None:
                # v = context.ScopedGet_Strict("".join(map(TokToStr, base_name)))
                # if v is not None: raise ParsingError(tokens, c, "??Redefinition ?")
                c = start  # Do something about the name
                break
            elif not is_prim and base_type is None:
                v = context.scoped_get("".join(map(tok_to_str, base_name)))
                if v is None:
                    raise ParsingError(tokens, c, "Undefined Identifier")
                elif v.is_type():
                    base_type = v.get_underlying_type()
                else:
                    return None, main_start
            else:
                raise ParsingError(tokens, c, "Unrecognized if path")
    if is_prim:
        str_name.sort(
            key=lambda k: (
                2
                if k in SINGLE_TYPES1
                else (0 if k in BASE_TYPE_MODS else (1 if k in INT_TYPES1 else 3))
            )
        )
        c0 = len(str_name)
        while c0 > 0:
            c0 -= 1
            if str_name[c0] in PRIM_TYPE_WORDS:
                c0 += 1
                break
        base_type = PrimitiveType.from_str_name(str_name[:c0])
        # assert c0 == len(str_name), "expected c0 = len(str_name), c0=%u, str_name=%r" % (c0, str_name)
        str_name = str_name[c0:]
    if base_type is None:
        print("BASE_TYPE NONE:", tokens[c - 2])
    assert isinstance(base_type, BaseType), "type = %s" % base_type.__class__.__name__
    for s in str_name:
        base_type = QualType(QualType.QUAL_Dct[s], base_type)
    return base_type, c


def get_strict_stmnt(
    tokens: List["Token"], c: int, end: int, context: "CompileContext"
):
    assert isinstance(context, (ClassType, StructType, UnionType))
    # TODO: place all members in host_scopeable (allows for scoped 'using' [namespace])
    start = c
    if (
        tokens[c].type_id == TokenType.NAME
        and tokens[c].str == context.name
        and tokens[c + 1].str == "("
    ):
        pos = StmntType.DECL
    elif tokens[c].type_id == TokenType.NAME and is_type_name_part(
        tokens[c].str, context
    ):
        pos = StmntType.DECL
    else:
        pos = STMNT_KEY_TO_ID.get(tokens[c].str, StmntType.SEMI_COLON)
    rtn = None
    if pos == StmntType.CURLY_STMNT:
        rtn = CurlyStmnt()
        c = rtn.build(tokens, c, end, context)
        if start == c:
            raise ParsingError(
                tokens, c, "Expected only '{' statement (not expression)"
            )
    elif pos == StmntType.DECL:
        rtn = DeclStmnt()
        # print "Before c = %u, end = %u, StmntType.DECL" % (c, end)
        c = rtn.build(tokens, c, end, context)
        # print "After c = %u, end = %u, StmntType.DECL" % (c, end)
    elif pos == StmntType.TYPEDEF:
        rtn = TypeDefStmnt()
        c = rtn.build(tokens, c, end, context)
    if rtn is None:
        raise ParsingError(
            tokens,
            c,
            "Expected only '{' statement or decl/typedef statement for strict statement",
        )
    return rtn, c


MetaTypeCtors = [EnumType, ClassType, StructType, UnionType]


class DeclStmnt(BaseStmnt):
    stmnt_type = StmntType.DECL
    # decl_lst added to init-args for __repr__

    def __init__(self, decl_lst: Optional[List["SingleVarDecl"]] = None):
        self.decl_lst = decl_lst

    def pretty_repr(self):
        return [self.__class__.__name__, "("] + get_pretty_repr(self.decl_lst) + [")"]

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        ext_spec = 0
        if tokens[c].type_id == TokenType.NAME:
            if tokens[c].str == "static":
                ext_spec = 1
                c += 1
            elif tokens[c].str == "extern":
                ext_spec = 2
                c += 1
        if (
            isinstance(context, BaseType)
            and context.type_class_id
            in [TypeClass.STRUCT, TypeClass.CLASS, TypeClass.UNION]
            and tokens[c].str == context.name
            and c + 1 < len(tokens)
            and tokens[c + 1].str == "("
        ):
            base_type = void_t
            # TODO: choose a value that will signal that this is a constructor
            #   or instead, don't enter the 'while c < end_stmnt + 1' loop
            named_qual_type, new_c = proc_typed_decl(tokens, c, end, context, base_type)
            assert isinstance(named_qual_type, IdentifiedQualType)
            assert isinstance(context, (StructType, ClassType, UnionType))
            typ = named_qual_type.typ
            assert isinstance(typ, BaseType)
            if (
                named_qual_type.name == context.name
                and typ.type_class_id == TypeClass.QUAL
            ):
                assert isinstance(typ, QualType)
                if typ.qual_id == QualType.QUAL_FN:
                    if ext_spec != 0:
                        raise ParsingError(
                            tokens,
                            c,
                            "unexpected 'extern' or 'const' in Constructor declaration",
                        )
                    typ.qual_id = QualType.QUAL_CTOR
                    params = typ.ext_inf
                    assert isinstance(params, list)
                    params.insert(
                        0,
                        IdentifiedQualType(
                            "this",
                            QualType(
                                QualType.QUAL_PTR,
                                QualType(QualType.QUAL_CONST, context),
                            ),
                        ),
                    )
                    stmnt = None
                    if tokens[new_c].str == "{":
                        stmnt = CurlyStmnt()
                        fn_ctx = context.new_scope(LocalScope(named_qual_type.name))
                        for param in params:
                            assert isinstance(param, (IdentifiedQualType, BaseType))
                            if isinstance(param, IdentifiedQualType):
                                fn_ctx.new_var(
                                    param.name,
                                    ContextVariable(
                                        param.name, param.typ, None, VarDeclMods.IS_ARG
                                    ),
                                )
                        new_c = stmnt.build(tokens, new_c, end, fn_ctx)
                    self.decl_lst = [
                        SingleVarDecl(
                            typ,
                            named_qual_type.name,
                            [] if stmnt is None else [stmnt],
                            0,
                            INIT_CURLY,
                        )
                    ]
                    return new_c
        base_type, c = get_base_type(tokens, c, end, context)
        end_stmnt = c
        lvl = 0
        # TODO: remove this limitation as this would break inline struct definitions (like struct {int a; char b} var)
        # TODO: Done
        while end_stmnt < end and (tokens[end_stmnt].str != ";" or lvl > 0):
            if tokens[end_stmnt].str in OPEN_GROUPS:
                lvl += 1
            elif tokens[end_stmnt].str in CLOSE_GROUPS:
                lvl -= 1
            end_stmnt += 1
        if base_type is None:
            raise SyntaxError("Expected Typename for DeclStmnt")
        self.decl_lst = []
        while c < end_stmnt + 1:
            is_non_semi_colon_end = False
            named_qual_type, c = proc_typed_decl(
                tokens, c, end_stmnt, context, base_type
            )
            if named_qual_type is None:
                raise ParsingError(tokens, c, "Expected Typename for DeclStmnt")
            assert isinstance(named_qual_type, IdentifiedQualType)
            cur_decl = None
            if named_qual_type.name is None:
                pass
            elif tokens[c].str == "=":
                c += 1
                expr, c = get_expr(tokens, c, ",", end_stmnt, context)
                cur_decl = SingleVarDecl(
                    named_qual_type.typ,
                    named_qual_type.name,
                    [expr],
                    ext_spec,
                    INIT_ASSIGN,
                )
            elif tokens[c].str == "(":
                c += 1
                lvl = 1
                c0 = c
                while lvl > 0 and c0 < end:
                    if tokens[c0].str in OPEN_GROUPS:
                        lvl += 1
                    elif tokens[c0].str in CLOSE_GROUPS:
                        lvl -= 1
                    c0 += 1
                end_p = c0 - 1
                if tokens[end_p].str != ")":
                    raise ParsingError(
                        tokens, end_p, "Expected closing ')' before end of statement"
                    )
                init_args = []
                while c < end_p:
                    expr, c = get_expr(tokens, c, ",", end_p, context)
                    init_args.append(expr)
                    c += 1
                cur_decl = SingleVarDecl(
                    named_qual_type.typ,
                    named_qual_type.name,
                    init_args,
                    ext_spec,
                    INIT_PARENTH,
                )
            elif tokens[c].str == "{":
                init_args = []
                prim_type = get_base_prim_type(named_qual_type.typ)
                start = c
                if prim_type.type_class_id == TypeClass.QUAL:
                    assert isinstance(prim_type, QualType)
                    if prim_type.qual_id == QualType.QUAL_FN:
                        stmnt = CurlyStmnt()
                        init_args.append(stmnt)
                        fn_ctx = context.new_scope(LocalScope(named_qual_type.name))
                        assert prim_type.ext_inf is not None
                        assert not isinstance(prim_type.ext_inf, int)
                        params = prim_type.ext_inf
                        if prim_type.qual_id == QualType.QUAL_CL_FN:
                            assert isinstance(context, BaseType)
                            assert context.type_class_id in [
                                TypeClass.STRUCT,
                                TypeClass.CLASS,
                                TypeClass.UNION,
                            ]
                            assert isinstance(
                                context, (StructType, ClassType, UnionType)
                            )
                            params.insert(
                                0,
                                IdentifiedQualType(
                                    "this",
                                    QualType(
                                        QualType.QUAL_PTR,
                                        QualType(QualType.QUAL_CONST, context),
                                    ),
                                ),
                            )
                        for param in prim_type.ext_inf:
                            assert isinstance(param, (IdentifiedQualType, BaseType))
                            if isinstance(param, IdentifiedQualType):
                                fn_ctx.new_var(
                                    param.name,
                                    ContextVariable(
                                        param.name, param.typ, None, VarDeclMods.IS_ARG
                                    ),
                                )
                        c = stmnt.build(tokens, c, end, fn_ctx)
                        is_non_semi_colon_end = True
                if len(init_args) == 0:
                    expr = CurlyExpr()
                    init_args.append(expr)
                    c = expr.build(tokens, c, end, context)
                if start == c:
                    raise ParsingError(
                        tokens, c, "Could not parse CurlyStmnt or CurlyExpr"
                    )
                cur_decl = SingleVarDecl(
                    named_qual_type.typ,
                    named_qual_type.name,
                    init_args,
                    ext_spec,
                    INIT_CURLY,
                )
            else:
                # print "else: tokens[%u] = %r" % (c, tokens[c])
                cur_decl = SingleVarDecl(
                    named_qual_type.typ, named_qual_type.name, [], ext_spec
                )
            if cur_decl is not None:
                self.decl_lst.append(cur_decl)
                ctx_var = context.new_var(
                    cur_decl.var_name,
                    ContextVariable(
                        cur_decl.var_name, cur_decl.type_name, None, ext_spec
                    ),
                )
                ctx_var.is_op_fn = named_qual_type.is_op_fn
                # NOTE the following must be true: SingleVarDecl(...).type_name is ContextVariable(...).typ
            if is_non_semi_colon_end:
                break
            elif tokens[c].str == ";":
                c += 1
                break
            elif tokens[c].str == ",":
                c += 1
        return c


def proc_typed_decl(
    tokens: List["Token"], c: int, end: int, context: "CompileContext", base_type=None
):
    # process the 'base' type before any parentheses, '*', '&', 'const', or 'volatile'
    if base_type is None:
        base_type, c = get_base_type(tokens, c, end, context)
        if base_type is None:
            return None, c
    rtn = base_type
    if not isinstance(rtn, IdentifiedQualType):
        rtn = IdentifiedQualType(None, rtn)
    s_start = c
    s_end = end
    i_type = 0  # inner type, 0: None, 1: '(' and ')', 2: name
    i_start = 0
    i_end = 0
    is_operator = False
    # collect tokens before the 'identifier' and place them in the pseudo-stack
    while c < end:
        if tokens[c].type_id == TokenType.BRK_OP:
            if tokens[c].str == "(":
                s_end = c
                c += 1
                lvl = 1
                i_start = c
                while c < end and lvl > 0:
                    if tokens[c].str in OPEN_GROUPS:
                        lvl += 1
                    elif tokens[c].str in CLOSE_GROUPS:
                        lvl -= 1
                    c += 1
                i_end = c - 1
                i_type = 1
                break
        elif (
            tokens[c].type_id == TokenType.NAME
            and tokens[c].str not in {"const", "auto", "volatile", "register"}
        ) or tokens[c].str == "::":
            i_type = 2
            i_start = c
            s_end = c
            c += 1
            while c < end:
                if tokens[c - 1].type_id == TokenType.NAME:
                    if tokens[c - 1].str == "operator":
                        if tokens[c].type_id == TokenType.OPERATOR:
                            c += 1
                        elif tokens[c].type_id == TokenType.BRK_OP:
                            if tokens[c].str == ",":
                                c += 1
                            elif tokens[c].str == "(":
                                c += 1
                                if tokens[c].str != ")":
                                    raise ParsingError(
                                        tokens, c, "Expected ')' for 'operator('"
                                    )
                                c += 1
                            elif tokens[c].str == "[":
                                c += 1
                                if tokens[c].str != "]":
                                    raise ParsingError(
                                        tokens, c, "Expected ']' for 'operator['"
                                    )
                                c += 1
                            else:
                                raise ParsingError(
                                    tokens,
                                    c,
                                    "Unrecognized operator found after operator keyword",
                                )
                        is_operator = True
                        break
                    elif tokens[c].str != "::":
                        break
                elif tokens[c - 1].str == "::":
                    if tokens[c].type_id != TokenType.NAME:
                        raise ParsingError(tokens, c, "Expected name to follow '::'")
                    elif tokens[c].str in KEYWORDS:
                        raise ParsingError(
                            tokens, c, "Unexpected keyword following '::'"
                        )
                c += 1
            i_end = c
            break
        c += 1
    # process items before the identifier starting from the higher index (like popping the pseudo-stack)
    c0 = s_end
    while c0 > s_start:
        c0 -= 1
        if tokens[c0].str in QualType.QUAL_Dct:
            rtn.add_qual_type(QualType.QUAL_Dct[tokens[c0].str])
        else:
            raise ParsingError(tokens, c0, "Unexpected token")
    # process items after the identifier by creating QualType instances
    while c < end:
        if tokens[c].type_id == TokenType.BRK_OP:
            if tokens[c].str == "(":
                cancel = False
                lvl = 1
                ext_inf = []
                c += 1
                n_start = c
                if tokens[c].str == ")":
                    lvl = 0
                    c += 1
                elif tokens[c].str == "void" and tokens[c + 1].str == ")":
                    lvl = 0
                    c += 2
                while c < end and lvl > 0:
                    if tokens[c].str in OPEN_GROUPS:
                        lvl += 1
                    elif tokens[c].str in CLOSE_GROUPS:
                        lvl -= 1
                    if (lvl == 1 and tokens[c].str == ",") or lvl == 0:
                        n_end = c
                        c = n_start
                        n_decl, c = proc_typed_decl(tokens, c, n_end, context)
                        if n_decl is None:
                            cancel = True
                            break
                        if c != n_end:
                            # raise SyntaxError("incomplete type at tokens[%u].str = %r and tokens[%u].str = %r" % (
                            #     c, tokens[c].str, n_end, tokens[n_end].str))
                            raise ParsingError(tokens, c, "Incomplete Type")
                        ext_inf.append(n_decl)
                        n_start = n_end + 1
                    c += 1
                if not cancel:
                    rtn.add_qual_type(QualType.QUAL_FN, ext_inf)
                else:
                    c = n_start - 1
                    break
            elif tokens[c].str == "[":
                c += 1
                ext_inf = None
                if tokens[c].str != "]":
                    expr, c = get_expr(tokens, c, "]", end, context)
                    if not isinstance(expr, LiteralExpr):
                        raise ParsingError(
                            tokens, c, "Expected Literal Integer for bounds of array"
                        )
                    else:
                        assert isinstance(expr, LiteralExpr)
                        if expr.t_lit != LiteralExpr.LIT_INT:
                            raise ParsingError(
                                tokens,
                                c,
                                "Expected Literal Integer for bounds of array",
                            )
                        else:
                            radix = 10
                            if len(expr.v_lit) > 1 and expr.v_lit.startswith("0"):
                                ch = expr.v_lit[1].lower()
                                if ch.isdigit() or ch == "o":
                                    radix = 8
                                elif ch == "x":
                                    radix = 16
                                elif ch == "b":
                                    radix = 2
                            ext_inf = int(expr.v_lit, radix)
                c += 1
                rtn.add_qual_type(QualType.QUAL_ARR, ext_inf)
            elif tokens[c].str == "," or tokens[c].str == ";" or tokens[c].str == "{":
                break
            else:
                raise ParsingError(tokens, c, "Unsupported Breaking operator")
        elif tokens[c].type_id == TokenType.OPERATOR and tokens[c].str == "=":
            break
        else:
            raise ParsingError(tokens, c, "Unexpected token")
    if i_type == 1:
        c0 = c
        c = i_start
        rtn, c = proc_typed_decl(tokens, c, i_end, context, rtn)
        if c != i_end:
            # raise SyntaxError("incomplete type at tokens[%u].str = %r and tokens[%u].str = %r" % (
            #     c, tokens[c].str, i_end, tokens[i_end].str))
            raise ParsingError(tokens, c, "Incomplete Type")
        c = c0
    elif i_type == 2:
        rtn.name = "".join(map(tok_to_str, tokens[i_start:i_end]))
        rtn.is_op_fn = is_operator
    return rtn, c


# TODO: Things to think about
# TODO:   Typenames -> struct Pt {int x; int y;}; ...function {Pt a = {0, 12}; return 0;}
# TODO:     Figure out that 'Pt a = {0, 12};' is a declaration


def flip_dct(dct: Dict[TypeVar("T"), TypeVar("U")]) -> Dict[TypeVar("U"), TypeVar("T")]:
    return {dct[k]: k for k in dct}


class QualType(BaseType):
    type_class_id = TypeClass.QUAL
    QUAL_DEF = 0
    QUAL_CONST = 1
    QUAL_PTR = 2
    QUAL_VOLATILE = 3
    QUAL_REG = 4
    QUAL_REF = 5
    QUAL_ARR = 6  # basically a pointer but defines how it is allocated (right where it is declared if not an argument)
    QUAL_FN = 7
    QUAL_CL_FN = 8
    QUAL_CTOR = 9
    QUAL_DTOR = 10
    QUAL_Lst = list(
        map(
            lambda x: "QUAL_" + x,
            "DEF CONST PTR VOLATILE REG REF ARR FN CL_FN CTOR DTOR".split(" "),
        )
    )
    QUAL_Dct = {
        "auto": QUAL_DEF,
        "const": QUAL_CONST,
        "*": QUAL_PTR,
        "volatile": QUAL_VOLATILE,
        "register": QUAL_REG,
        "&": QUAL_REF,
        "[": QUAL_ARR,
        "(": QUAL_FN,
    }
    mangle_captures = {
        "C": QUAL_CONST,
        "P": QUAL_PTR,
        "V": QUAL_VOLATILE,
        "S": QUAL_REG,
        "R": QUAL_REF,
        "A": QUAL_ARR,
        "F": QUAL_FN,
        "N": QUAL_CTOR,
        "r": QUAL_DTOR,
        "M": QUAL_CL_FN,
    }
    dct_qual_id_mangle = flip_dct(mangle_captures)
    mangle_captures["Z"] = QUAL_FN
    mangle_captures["z"] = QUAL_FN

    @classmethod
    def from_mangle(cls, s, c):
        qual_id = cls.mangle_captures[s[c]]
        c += 1
        if qual_id == QualType.QUAL_FN:
            tgt_type = None
            if s[c] == "Z":
                c += 1
                tgt_type, c = from_mangle(s, c)
            ext_inf = []
            while c < len(s) and s[c] != "z":
                typ, c = from_mangle(s, c)
                ext_inf.append(typ)
            if c < len(s):
                c += 1
            return QualType(qual_id, tgt_type, ext_inf), c
        else:
            tgt_type, c = from_mangle(s, c)
            return QualType(qual_id, tgt_type), c

    def get_ctor_fn_types(self):
        if self.qual_id in {
            QualType.QUAL_REG,
            QualType.QUAL_CONST,
            QualType.QUAL_VOLATILE,
            QualType.QUAL_DEF,
        }:
            return self.tgt_type.get_ctor_fn_types()
        elif self.qual_id == QualType.QUAL_REF:
            return [make_void_fn(x) for x in [[self]]]
        elif self.qual_id == QualType.QUAL_PTR:
            return [make_void_fn(x) for x in [[], [self]]]
        elif self.qual_id == QualType.QUAL_ARR:
            return [
                make_void_fn(x)
                for x in [
                    [],
                    [QualType(QualType.QUAL_REF, QualType(QualType.QUAL_CONST, self))],
                    [QualType(QualType.QUAL_PTR, self.tgt_type)],
                ]
            ]
        elif self.qual_id in [
            QualType.QUAL_FN,
            QualType.QUAL_CTOR,
            QualType.QUAL_CL_FN,
            QualType.QUAL_DTOR,
        ]:
            return []
        else:
            return super(QualType, self).get_ctor_fn_types()

    def __init__(
        self, qual_id, tgt_type, ext_inf: Optional[Union[int, List["BaseType"]]] = None
    ):
        """
        :param int qual_id:
        :param BaseType tgt_type:
        :param None|int|list[BaseType] ext_inf:
        """
        self.qual_id = qual_id
        self.tgt_type = tgt_type
        self.ext_inf = ext_inf

    def pretty_repr(self):
        c_name = self.__class__.__name__
        rtn = (
            [c_name, "(", c_name, ".", self.QUAL_Lst[self.qual_id], ","]
            + get_pretty_repr(self.tgt_type)
            + [")"]
        )
        if self.ext_inf is not None:
            rtn[-1:-1] = [","] + get_pretty_repr(self.ext_inf)
        return rtn

    def to_mangle_str(self, top_decl=False):
        ch = QualType.dct_qual_id_mangle[self.qual_id]
        if (
            self.qual_id != QualType.QUAL_FN
            and self.qual_id in QualType.dct_qual_id_mangle
        ):
            return ch + self.tgt_type.to_mangle_str()
        elif self.qual_id == QualType.QUAL_FN:
            rtn = ch
            if not top_decl:
                rtn += "Z" + self.tgt_type.to_mangle_str()
            return rtn + "".join(map(lambda x: x.to_mangle_str(), self.ext_inf)) + "z"
        else:
            raise TypeError("Unrecognized qual_id = %u" % self.qual_id)

    def to_user_str(self):
        s = "<UNKNOWN %u> "
        if self.qual_id == QualType.QUAL_DEF:
            s = "auto "
        elif self.qual_id == QualType.QUAL_CONST:
            s = "const "
        elif self.qual_id == QualType.QUAL_PTR:
            s = "pointer to "
        elif self.qual_id == QualType.QUAL_VOLATILE:
            s = "volatile "
        elif self.qual_id == QualType.QUAL_REG:
            s = "register "
        elif self.qual_id == QualType.QUAL_REF:
            s = "reference to "
        elif self.qual_id == QualType.QUAL_ARR:
            s = "array of "
            if self.ext_inf is not None:
                s += "%u " % self.ext_inf
        elif self.qual_id == QualType.QUAL_FN:
            s = "function (%s) -> " % ", ".join(
                map(get_user_str_from_type, self.ext_inf)
            )
        else:
            s %= self.qual_id
        s += get_user_str_from_type(self.tgt_type)
        if self.qual_id == QualType.QUAL_FN:
            s = "(" + s + ")"
        return s

    def get_expr_arg_type(self, expr: "BaseExpr") -> "BaseExpr":
        if expr.t_anot is None:
            raise TypeError("Expected Expression to have a type")
        if self.qual_id == QualType.QUAL_REF:
            if expr.t_anot.type_class_id != TypeClass.QUAL:
                pass
            if not compare_no_cvr(self.tgt_type, get_value_type(expr.t_anot)):
                raise TypeError("Bad Reference: %r, %r" % (self, expr.t_anot))

        else:
            if not compare_no_cvr(self, get_value_type(expr.t_anot)):
                raise TypeError("Bad Type: %r, %r" % (self, expr.t_anot))
        if expr.expr_id == ExprType.LITERAL:
            assert isinstance(expr, LiteralExpr)
            if expr.l_val in [
                LiteralExpr.LIT_INT,
                LiteralExpr.LIT_CHR,
                LiteralExpr.LIT_FLOAT,
            ]:
                pass
        return CastOpExpr(self, expr, CastType.IMPLICIT)

    def compile_conv(self, cmpl_obj, expr, context, cmpl_data=None, temp_links=None):
        from_type = expr.t_anot
        if from_type.type_class_id == TypeClass.PRIM:
            assert isinstance(from_type, PrimitiveType)
            if from_type.typ in INT_TYPE_CODES:
                sz_cls = from_type.size.bit_length() - 1
                if 1 << sz_cls != from_type.size or sz_cls > 3:
                    raise TypeError(
                        "Bad Primitive Type Size: %u for %r" % (from_type.size, self)
                    )
                inp_bits = sz_cls << 1
                inp_bits |= int(from_type.sign)
            elif from_type.typ in FLT_TYPE_CODES:
                sz_cls = from_type.size.bit_length() - 2
                inp_bits = sz_cls | 0x08
            else:
                raise TypeError("Cannot cast from Type %s" % repr(self))
            if self.qual_id == QualType.QUAL_PTR:
                out_bits = 3
            else:
                raise TypeError("Cannot cast from Type %r to %r" % (from_type, self))
            if inp_bits != out_bits:
                cmpl_obj.memory.extend([BC_CONV, inp_bits | (out_bits << 4)])
            return 8
        elif from_type.type_class_id == TypeClass.QUAL:
            assert isinstance(from_type, QualType)
            from_vt = (
                from_type.tgt_type
                if from_type.qual_id == QualType.QUAL_REF
                else from_type
            )
            if (
                self.qual_id == QualType.QUAL_REF
                and from_type.qual_id == QualType.QUAL_REF
            ):
                return compile_expr(
                    cmpl_obj, expr, context, cmpl_data, from_type, temp_links
                )
            elif self.qual_id == QualType.QUAL_PTR:
                if from_vt.qual_id == QualType.QUAL_PTR:
                    return compile_expr(
                        cmpl_obj, expr, context, cmpl_data, from_vt, temp_links
                    )
                elif from_vt.qual_id == QualType.QUAL_ARR:
                    # TODO: maybe type_coerce = from_type (the reference)
                    return compile_expr(
                        cmpl_obj, expr, context, cmpl_data, self, temp_links
                    )
                elif from_type.qual_id == QualType.QUAL_REF and is_fn_type(from_vt):
                    # assert CompareNoCVR(from_type.tgt_type, self.tgt_type)
                    return compile_expr(
                        cmpl_obj, expr, context, cmpl_data, from_type, temp_links
                    )
        raise ValueError("Unhandled Cast Type: %r to %r" % (from_type, self))

    def compile_var_init(
        self, cmpl_obj, init_args, context, ref, cmpl_data=None, temp_links=None
    ):
        if len(init_args) > 1:
            raise SyntaxError(
                "Invalid number of arguments for initialization of %s"
                % get_user_str_from_type(self)
            )
        if len(init_args) == 0 and self.qual_id == QualType.QUAL_REF:
            raise ValueError("Cannot declare a reference without instantiating it")
        sz_var = size_of(self)
        ctx_var = None
        link = None
        name = None
        is_local = True
        cmpl_obj1 = None
        # Verification and Setup stage (for compilation)
        if ref.ref_type == VAR_REF_TOS_NAMED:
            assert isinstance(ref, VarRefTosNamed)
            ctx_var = ref.ctx_var
            if ctx_var is not None:
                assert isinstance(ctx_var, ContextVariable)
                if ctx_var.typ.type_class_id == TypeClass.MULTI:
                    assert isinstance(ctx_var, OverloadedCtxVar)
                    assert ctx_var.specific_ctx_vars is not None
                    for var in ctx_var.specific_ctx_vars:
                        if var.typ is self:
                            ctx_var = var
                            break
                    else:
                        raise NameError(
                            "Could not resolve overloaded variable '%s'" % ctx_var.name
                        )
                    ref = VarRefTosNamed(ctx_var)
                assert isinstance(ctx_var, ContextVariable)
                name = ctx_var.get_link_name()
                is_local = ctx_var.parent.is_local_scope()
                if not is_local:
                    link = cmpl_obj.get_link(name)
            if self.qual_id == QualType.QUAL_FN:
                if is_local:
                    raise TypeError("Functions must be GLOBAL")
                assert isinstance(cmpl_obj, Compilation)
                if len(init_args) == 0:
                    return 0
                err0 = "Redefinition of function %s is not allowed"
                err1 = "Function %s cannot be defined with %s (only CurlyStmnt for now)"
                if name in cmpl_obj.objects:
                    raise ValueError(err0 % name)
                elif not isinstance(init_args[0], CurlyStmnt):
                    raise SyntaxError(err1 % (name, init_args[0].__class__.__name__))
                cmpl_obj1 = cmpl_obj.spawn_compile_object(
                    CompileObjectType.FUNCTION, name
                )
            elif not is_local:
                assert isinstance(cmpl_obj, Compilation)
                if ctx_var.mods != VarDeclMods.EXTERN:
                    cmpl_obj1 = cmpl_obj.spawn_compile_object(
                        CompileObjectType.GLOBAL, name
                    )
        elif ref.ref_type == VAR_REF_LNK_PREALLOC:
            assert isinstance(ref, VarRefLnkPrealloc)
            link = ref.lnk
            is_local = False
            if self.qual_id == QualType.QUAL_FN:
                raise TypeError("Functions must be NAMED")
        else:
            raise ValueError("Unrecognized VarRef (ref = %s)" % repr(ref))
        # Creation stage (in program)
        if self.qual_id in [
            QualType.QUAL_DEF,
            QualType.QUAL_CONST,
            QualType.QUAL_VOLATILE,
            QualType.QUAL_REG,
        ]:
            return self.tgt_type.compile_var_init(
                cmpl_obj, init_args, context, ref, cmpl_data, temp_links
            )
        elif self.qual_id in [QualType.QUAL_PTR, QualType.QUAL_REF, QualType.QUAL_ARR]:
            if len(init_args) == 1:
                expr = init_args[0]
                # assert CompareNoCVR(self, expr.t_anot), "self = %s, expr.t_anot = %s" % (
                #     GetUserStrFromType(self), GetUserStrFromType(expr.t_anot)
                # )
                sz = compile_expr(cmpl_obj, expr, context, cmpl_data, self, temp_links)
                assert (
                    sz == sz_var
                ), "sz = %u, sz_var = %u, type_name = %r, expr = %r" % (
                    sz,
                    sz_var,
                    self,
                    expr,
                )
            elif is_local:
                sz_cls = emit_load_i_const(cmpl_obj.memory, sz_var, False)
                cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
        elif self.qual_id == QualType.QUAL_FN:
            assert cmpl_obj1 is not None
            the_arg = init_args[0]
            assert isinstance(the_arg, CurlyStmnt)
            cmpl_data1 = LocalCompileData()
            variadic = False
            off = -16
            fn_ctx = the_arg.context.parent
            assert isinstance(fn_ctx, LocalScope)
            assert not isinstance(self.ext_inf, int)
            assert self.ext_inf is not None
            res_link = None
            res_type = self.tgt_type
            if variadic:
                sz1 = 8  # sizeof(T*)
                res_link = IndirectLink(LocalRef.from_bp_off_post_inc(off, sz1))
                off -= 8
            for Param in self.ext_inf:
                assert isinstance(Param, (IdentifiedQualType, BaseType))
                sz1 = size_of(Param)
                if isinstance(Param, IdentifiedQualType):
                    ctx_var = fn_ctx.var_name_strict(Param.name)
                    assert isinstance(ctx_var, ContextVariable)
                    cmpl_data1.setitem(
                        ctx_var.get_link_name(),
                        (ctx_var, LocalRef.from_bp_off_post_inc(off, sz1)),
                    )
                off -= sz1
            if not variadic:
                sz1 = size_of(res_type)
                res_link = LocalRef.from_bp_off_post_inc(off, sz1)
                off -= sz1
            assert res_link is not None
            cmpl_data1.res_data = (res_type, res_link)
            compile_curly(cmpl_obj1, init_args[0], fn_ctx, cmpl_data1)
            cmpl_obj1.memory.extend([BC_RET])
            return len(cmpl_obj1.memory)
        else:
            raise TypeError("Unrecognized type: %s" % get_user_str_from_type(self))
        # storage stage (GLOBAL:in program/LOCAL: compiler)
        if is_local:
            assert cmpl_data is not None, "Expected cmpl_data to not be None for LOCAL"
            assert isinstance(cmpl_data, LocalCompileData)
            if ctx_var is not None:
                cmpl_data.put_local(ctx_var, name, sz_var, None, True)
        else:
            if ref.ref_type == VAR_REF_TOS_NAMED:
                assert cmpl_data is None, "Expected cmpl_data to be None for GLOBAL"
                assert isinstance(cmpl_obj, Compilation)
                assert cmpl_obj1 is not None
                assert ctx_var is not None
                cmpl_obj1.memory.extend([0] * sz_var)
            if len(init_args) == 1:
                assert link is not None
                link.emit_stor(
                    cmpl_obj.memory, sz_var, cmpl_obj, byte_copy_cmpl_intrinsic
                )
        return sz_var

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None) -> int:
        if self.qual_id in [
            QualType.QUAL_CONST,
            QualType.QUAL_REG,
            QualType.QUAL_DEF,
            QualType.QUAL_VOLATILE,
        ]:
            return self.tgt_type.compile_var_de_init(cmpl_obj, context, ref, cmpl_data)
        elif self.qual_id == QualType.QUAL_ARR:
            # if self.ext_inf is None: return -1
            # if ref.ref_type == VAR_REF_TOS_NAMED:
            return -1
        elif self.qual_id == QualType.QUAL_FN:
            raise TypeError("cannot destroy a function")
        # QUAL_REF, QUAL_PTR, QUAL_FN
        return -1


def size_of(typ: "BaseType", is_arg: bool = False):
    if isinstance(typ, QualType):
        if typ.qual_id == QualType.QUAL_ARR:
            if is_arg or typ.ext_inf is None:
                return 8
            return size_of(typ.tgt_type) * typ.ext_inf
        elif typ.qual_id in {QualType.QUAL_FN, QualType.QUAL_PTR, QualType.QUAL_REF}:
            return 8
        elif typ.qual_id in {
            QualType.QUAL_CONST,
            QualType.QUAL_DEF,
            QualType.QUAL_REG,
            QualType.QUAL_VOLATILE,
        }:
            return size_of(typ.tgt_type)
        else:
            raise ValueError("Unrecognized QualType.qual_id = %u" % typ.qual_id)
    elif isinstance(typ, IdentifiedQualType):
        return size_of(typ.typ)
    elif isinstance(typ, PrimitiveType):
        return typ.size
    elif isinstance(typ, EnumType):
        return size_of(typ.the_base_type)
    elif isinstance(typ, (StructType, ClassType)):
        sz = 0 if typ.the_base_type is None else size_of(typ.the_base_type)
        # TODO: add 'packed' boolean attribute to StructType and ClassType1
        for ctx_var in typ.var_order:
            sz += size_of(ctx_var.typ)
        return sz
    elif isinstance(typ, UnionType):
        # TODO: remove BaseType from UnionType
        sz = 0
        for k in typ.definition:
            v = typ.definition[k]
            assert isinstance(v, ContextVariable)
            sz = max(sz, size_of(v.typ))
        return sz
    else:
        raise TypeError("Unrecognized type: %s" % typ.__class__.__name__)
    # TODO: add Typedef support


def get_base_prim_type(typ: Union["BaseType", "IdentifiedQualType"]) -> "BaseType":
    assert typ is not None
    if isinstance(typ, IdentifiedQualType):
        typ = typ.typ
    base_comp_types = {
        QualType.QUAL_FN,
        QualType.QUAL_PTR,
        QualType.QUAL_ARR,
        QualType.QUAL_REF,
    }
    pass_thru_types = {
        QualType.QUAL_REG,
        QualType.QUAL_CONST,
        QualType.QUAL_DEF,
        QualType.QUAL_VOLATILE,
    }
    if typ.type_class_id == TypeClass.PRIM:
        assert isinstance(typ, PrimitiveType)
        return typ
    elif typ.type_class_id == TypeClass.QUAL:
        assert isinstance(typ, QualType)
        if typ.qual_id in base_comp_types:
            return typ
        elif typ.qual_id in pass_thru_types:
            return get_base_prim_type(typ.tgt_type)
        else:
            raise ValueError("Bad qual_id = %u" % typ.qual_id)
    elif typ.type_class_id == TypeClass.ENUM:
        assert isinstance(typ, EnumType)
        return typ.the_base_type
    elif typ.type_class_id in [TypeClass.CLASS, TypeClass.STRUCT, TypeClass.UNION]:
        assert isinstance(typ, (ClassType, StructType, UnionType))
        return typ
    else:
        raise ValueError("Unrecognized Type: " + repr(typ))


def get_value_type(typ: "BaseType", do_arr_to_ptr_decay: bool = False):
    if isinstance(typ, (PrimitiveType, UnionType, ClassType, StructType)):
        return typ
    elif isinstance(typ, QualType):
        if typ.qual_id in [
            QualType.QUAL_CONST,
            QualType.QUAL_REG,
            QualType.QUAL_VOLATILE,
            QualType.QUAL_DEF,
        ]:
            return get_value_type(typ.tgt_type)
        elif typ.qual_id == QualType.QUAL_ARR:
            if do_arr_to_ptr_decay:
                return QualType(QualType.QUAL_PTR, typ.tgt_type)
            else:
                return typ
        elif typ.qual_id in [QualType.QUAL_FN, QualType.QUAL_PTR]:
            return typ
        elif typ.qual_id == QualType.QUAL_REF:
            return get_value_type(typ.tgt_type)
        else:
            raise ValueError("Unrecognized qual_id = %u" % typ.qual_id)
    elif isinstance(typ, IdentifiedQualType):
        return get_value_type(typ.typ)
    else:
        raise TypeError("Unrecognized Type: %s" % repr(typ))


# Compare types ignoring [C]onst [V]olatile and [R]egister
def compare_no_cvr(
    type_a: "BaseType", type_b: "BaseType", ignore_ref: bool = False
) -> bool:
    type_a = get_value_type(type_a) if ignore_ref else get_base_prim_type(type_a)
    type_b = get_value_type(type_b) if ignore_ref else get_base_prim_type(type_b)
    while (
        type_a.type_class_id == TypeClass.QUAL
        and type_b.type_class_id == TypeClass.QUAL
    ):
        assert isinstance(type_a, QualType)
        assert isinstance(type_b, QualType)
        if type_a.qual_id != type_b.qual_id:
            return False
        elif type_a.qual_id == QualType.QUAL_FN:
            if len(type_a.ext_inf) != len(type_b.ext_inf):
                return False
            if not compare_no_cvr(type_a.tgt_type, type_b.tgt_type):
                return False
            for c in range(len(type_a.ext_inf)):
                if not compare_no_cvr(type_a.ext_inf[c], type_b.ext_inf[c]):
                    return False
            return True
        elif type_a.qual_id == QualType.QUAL_ARR:
            if type_a.ext_inf is not None and type_b.ext_inf is not None:
                if type_a.ext_inf != type_b.ext_inf:
                    return False
        type_a = get_base_prim_type(type_a.tgt_type)
        type_b = get_base_prim_type(type_b.tgt_type)
    if type_a.type_class_id != type_b.type_class_id:
        return False
    elif type_a.type_class_id == TypeClass.PRIM:
        assert isinstance(type_a, PrimitiveType)
        assert isinstance(type_b, PrimitiveType)
        return type_a.typ == type_b.typ and type_a.sign == type_b.sign
    else:
        assert isinstance(type_a, (EnumType, UnionType, StructType, ClassType))
        assert isinstance(type_b, (EnumType, UnionType, StructType, ClassType))
        assert type_a.parent is not None, "parent should not be None"
        assert type_b.parent is not None, "parent should not be None"
        if type_a.parent is not type_b.parent:
            return False
        elif type_a.name != type_b.name:
            return False
    return True


class TypeDefStmnt(BaseStmnt):
    stmnt_type = StmntType.TYPEDEF

    def __init__(self, id_qual_types: Optional[List["IdentifiedQualType"]] = None):
        self.id_qual_types = id_qual_types

    def pretty_repr(self):
        return (
            [self.__class__.__name__, "("] + get_pretty_repr(self.id_qual_types) + [")"]
        )

    def build(
        self, tokens: List["Token"], c: int, end: int, context: "CompileContext"
    ) -> int:
        c += 1
        base_type, c = get_base_type(tokens, c, end, context)
        end_stmnt = c
        # TODO: remove this limitation as this would break inline struct definitions (like struct {int a; char b} var)
        # TODO: DONE
        lvl = 0
        while end_stmnt < end and (tokens[end_stmnt].str != ";" or lvl > 0):
            if tokens[end_stmnt].str in OPEN_GROUPS:
                lvl += 1
            elif tokens[end_stmnt].str in CLOSE_GROUPS:
                lvl -= 1
            end_stmnt += 1
        if base_type is None:
            raise SyntaxError("Expected Typename for DeclStmnt")
        self.id_qual_types = []
        while c < end_stmnt + 1:
            named_qual_type, c = proc_typed_decl(
                tokens, c, end_stmnt, context, base_type
            )
            if named_qual_type is None:
                raise ParsingError(tokens, c, "Expected Typename for DeclStmnt")
            assert isinstance(named_qual_type, IdentifiedQualType)
            if named_qual_type.name is None:
                raise ParsingError(tokens, c, "Expected a name for typedef")
            elif tokens[c].str == "," or tokens[c].str == ";":
                self.id_qual_types.append(named_qual_type)
                context.new_type(
                    named_qual_type.name,
                    TypeDefCtxMember(
                        named_qual_type.name, context, named_qual_type.typ
                    ),
                )
                c += 1
                if tokens[c].str == ";":
                    break
            else:
                raise ParsingError(
                    tokens, c, "Expected a ',' or ';' to delimit the typedef"
                )
        return c


def is_prim_type_id(typ: "BaseType", type_id: int) -> bool:
    if typ.type_class_id == TypeClass.PRIM:
        assert isinstance(typ, PrimitiveType)
        return typ.typ == type_id
    return False


def is_prim_or_ptr(typ: "BaseType") -> bool:
    if typ.type_class_id == TypeClass.PRIM:
        return True
    elif typ != TypeClass.QUAL:
        return False
    assert isinstance(typ, QualType)
    return typ.qual_id == QualType.QUAL_PTR


class IdentifiedQualType(PrettyRepr):
    def __init__(self, name, typ):
        self.name = name
        self.typ = typ
        self.is_op_fn = False

    def add_qual_type(self, qual_id, ext_inf=None):
        self.typ = QualType(qual_id, self.typ, ext_inf)

    def to_mangle_str(self):
        return self.typ.to_mangle_str()

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr((self.name, self.typ))

    def to_user_str(self):
        return self.name + " is a " + get_user_str_from_type(self.typ)


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
        # self.size = size_of(typ, mods == VarDeclMods.IS_ARG)
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


class MultiType(BaseType):
    type_class_id = TypeClass.MULTI


# TODO: add code to deal with this type of context variable
class OverloadedCtxVar(ContextVariable):
    def __init__(
        self, name: str, specific_ctx_vars: Optional[List[ContextVariable]] = None
    ):
        super(OverloadedCtxVar, self).__init__(name, MultiType())
        self.specific_ctx_vars = [] if specific_ctx_vars is None else specific_ctx_vars

    def pretty_repr(self):
        return [self.__class__.__name__] + get_pretty_repr(
            (self.name, self.specific_ctx_vars)
        )

    def add_ctx_var(self, inst: ContextVariable):
        self.specific_ctx_vars.append(inst)


class TypeDefCtxMember(ContextMember):
    def __init__(self, name: str, parent: Optional["CompileContext"], typ: "BaseType"):
        super(TypeDefCtxMember, self).__init__(name, parent)
        self.typ = typ

    def is_type(self):
        return True

    def get_underlying_type(self):
        return self.typ


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
                raise ValueError(
                    "Cannot define functions in LocalScope (attempt to define '%s')" % v
                )
        var = self.vars.get(v, None)
        if var is not None:
            raise NameError(
                "Redefinition of Variable '%s' not allowed in LocalScope" % v
            )
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


def from_mangle(s: str, c: int) -> Tuple["BaseType", int]:
    if s[c] in QualType.mangle_captures:
        return QualType.from_mangle(s, c)
    elif s[c] in PrimitiveType.mangle_captures:
        return PrimitiveType.from_mangle(s, c)
    elif s[c] in ClassType.mangle_captures:
        return ClassType.from_mangle(s, c)
    elif s[c] in StructType.mangle_captures:
        return StructType.from_mangle(s, c)
    elif s[c] in UnionType.mangle_captures:
        return UnionType.from_mangle(s, c)
    elif s[c] in EnumType.mangle_captures:
        return EnumType.from_mangle(s, c)
    else:
        raise ValueError(
            "Unrecognized mangle capture: '%s' at c = %u in %r" % (s[c], c, s)
        )


def get_tgt_ref_type(typ: "BaseType") -> Tuple["BaseType", "BaseType", bool]:
    """
    returns primitive type, v value type, is reference
    """
    vt = pt = get_base_prim_type(typ)
    is_ref = False
    if pt.type_class_id == TypeClass.QUAL:
        assert isinstance(pt, QualType)
        if pt.qual_id == QualType.QUAL_REF:
            is_ref = True
            vt = get_base_prim_type(pt.tgt_type)
    return pt, vt, is_ref


from .get_user_str_from_type import get_user_str_from_type
from .is_fn_type import is_fn_type
from .is_type_name_part import is_type_name_part
from .make_void_fn import make_void_fn
from ..ParsingError import ParsingError
from ..constants import (
    BASE_TYPE_MODS,
    INT_TYPES1,
    KEYWORDS,
    MODIFIERS,
    PRIM_TYPE_WORDS,
    SINGLE_TYPES1,
)
from ..try_get_as_name import try_get_as_name
from .helpers.VarRef import (
    VAR_REF_LNK_PREALLOC,
    VAR_REF_TOS_NAMED,
    VarRef,
    VarRefLnkPrealloc,
    VarRefTosNamed,
)
from ...ParseConstants import (
    CLOSE_GROUPS,
    INIT_ASSIGN,
    INIT_CURLY,
    INIT_PARENTH,
    META_TYPE_LST,
    OPEN_GROUPS,
)
from ..expr.BaseExpr import BaseExpr, ExprType
from ..expr.CastOpExpr import CastOpExpr, CastType
from ..expr.CurlyExpr import CurlyExpr
from ..expr.LiteralExpr import LiteralExpr
from ..expr.get_expr import get_expr
from ..stmnt.CurlyStmnt import CurlyStmnt
from ..type.BaseType import BaseType, TypeClass
from ..type.types import ContextVariable, VarDeclMods
from ...StackVM.PyStackVM import (
    BCR_ABS_S8,
    BC_ADD_SP1,
    BC_CMP1,
    BC_CMP8S,
    BC_CONV,
    BC_FCMP_16,
    BC_FCMP_2,
    BC_LOAD,
    BC_NE0,
    BC_NOP,
    BC_RET,
)
from ...code_gen.BaseCmplObj import BaseCmplObj
from ...code_gen.BaseLink import BaseLink
from ...code_gen.Compilation import Compilation, CompileObjectType
from ...code_gen.IndirectLink import IndirectLink
from ...code_gen.LocalCompileData import LocalCompileData
from ...code_gen.LocalRef import LocalRef
from ...code_gen.byte_copy_cmpl_intrinsic import byte_copy_cmpl_intrinsic
from ...code_gen.compile_curly import compile_curly
from ...code_gen.compile_expr import compile_expr
from ...lexer.lexer import Token, TokenType, tok_to_str
from ..stmnt.helpers.SingleVarDecl import SingleVarDecl
from ...code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
