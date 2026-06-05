from enum import Enum
from typing import List, Optional, Tuple, Union

from .BaseType import BaseType, TypeClass
from ..constants import BASE_TYPE_MODS


class PrimitiveTypeId(Enum):
    INT_I = 0
    INT_L = 1
    INT_LL = 2
    INT_I128 = 3
    INT_S = 4
    INT_C = 5
    INT_C16 = 6
    INT_C32 = 7
    INT_WC = 8
    FLT_F = 9
    FLT_D = 10
    FLT_LD = 11
    TYP_BOOL = 12
    TYP_VOID = 13
    TYP_AUTO = 14


LST_TYPE_CODES = [
    "INT_I",
    "INT_L",
    "INT_LL",
    "INT_I128",
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
    PrimitiveTypeId.INT_I128,
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
    PrimitiveTypeId.INT_I128: (16, True),
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
    "__int128": PrimitiveTypeId.INT_I128,
    "_Bool": PrimitiveTypeId.TYP_BOOL,
    "bool": PrimitiveTypeId.TYP_BOOL,
}


class PrimitiveType(BaseType):
    def get_expr_arg_type(self, expr: "BaseExpr") -> "BaseType":
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
        PrimitiveTypeId.INT_I128: ["__int128"],
        PrimitiveTypeId.INT_S: ["short"],
        PrimitiveTypeId.INT_C: ["char"],
        PrimitiveTypeId.INT_C16: ["char16_t"],
        PrimitiveTypeId.INT_C32: ["char32_t"],
        PrimitiveTypeId.INT_WC: ["wchar_t"],
        PrimitiveTypeId.FLT_F: ["float"],
        PrimitiveTypeId.FLT_D: ["double"],
        PrimitiveTypeId.FLT_LD: ["long", "double"],
        PrimitiveTypeId.TYP_BOOL: ["_Bool"],
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
        "n": (PrimitiveTypeId.INT_I128, -1),
        "o": (PrimitiveTypeId.INT_I128, 1),
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
        (PrimitiveTypeId.INT_I128, True): "n",
        (PrimitiveTypeId.INT_I128, False): "o",
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

    def pretty_repr(self, pretty_repr_ctx=None):
        return ["PrimitiveType", ".", "from_type_code", "("] + [
            "PrimitiveTypeId",
            ".",
            self.typ.name,
            ",",
            (
                "0"
                if SIZE_SIGN_MAP[self.typ][1] == self.sign
                else ("-1" if self.sign else "1")
            ),
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
            static_res = compile_static_storage_decl(
                self, cmpl_obj, init_args, context, ref, cmpl_data, temp_links
            )
            if static_res is not None:
                return static_res
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
                        emit_tracked_abs_s8_load(
                            cmpl_obj,
                            sz_var,
                            is_volatile_storage_type(expr.t_anot, through_ref=True),
                            atomic_access=is_atomic_storage_type(
                                expr.t_anot, through_ref=True
                            ),
                        )
                if ctx_var is not None:
                    cmpl_data.put_local(ctx_var, name, sz_var, None, True)
            else:
                raise AssertionError(
                    "Named static-storage declarations should be handled before the global branch"
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
            link.emit_stor(
                cmpl_obj.memory,
                sz_var,
                cmpl_obj,
                byte_copy_cmpl_intrinsic,
                volatile_access=is_volatile_storage_type(self),
                atomic_access=is_atomic_storage_type(self),
            )
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
        out_bits = get_primitive_conv_bits(self)
        if from_type.type_class_id == TypeClass.PRIM:
            assert isinstance(from_type, PrimitiveType)
            inp_bits = get_primitive_conv_bits(from_type)
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
            if inp_bits in {0x0C, 0x0D}:
                cmpl_obj.memory[-2] = BC_INT128
                cmpl_obj.memory[-1] = (
                    BC128_CMP128S if inp_bits == 0x0D else BC128_CMP128U
                )
            else:
                code = (BC_FCMP_2 if inp_bits & 0x08 else BC_CMP1) + (inp_bits & 0x7)
                assert BC_FCMP_2 <= code <= BC_FCMP_16 or BC_CMP1 <= code <= BC_CMP8S, (
                    "GOT: %u" % code
                )
                cmpl_obj.memory[-2] = code
        else:
            cmpl_obj.memory.extend([BC_CONV, inp_bits | (out_bits << 4)])
        return self.size


def get_primitive_conv_bits(typ: "PrimitiveType") -> int:
    if typ.typ in INT_TYPE_CODES:
        if typ.size == 16:
            return 0x0D if typ.sign else 0x0C
        sz_cls = typ.size.bit_length() - 1
        if 1 << sz_cls != typ.size or sz_cls > 3:
            raise TypeError("Bad Primitive Type Size: %u for %r" % (typ.size, typ))
        return (sz_cls << 1) | int(typ.sign)
    if typ.typ in FLT_TYPE_CODES:
        sz_cls = typ.size.bit_length() - 2
        return sz_cls | 0x08
    raise TypeError("Cannot cast to Type %s" % repr(typ))


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
        ["unsigned", "__int128"],
        ["signed", "__int128"],
        ["_Bool"],
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
        ["signed", "__int128"],
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


def is_prim_type_id(typ: "BaseType", type_id: int) -> bool:
    if typ.type_class_id == TypeClass.PRIM:
        assert isinstance(typ, PrimitiveType)
        return typ.typ == type_id
    return False


from ...PrettyRepr import format_pretty
from ...code_gen.byte_copy_cmpl_intrinsic import byte_copy_cmpl_intrinsic
from .helpers.VarRef import (
    VAR_REF_LNK_PREALLOC,
    VAR_REF_TOS_NAMED,
    VarRef,
    VarRefLnkPrealloc,
    VarRefTosNamed,
)
from .make_void_fn import make_void_fn
from .align_size_of import size_of
from ...StackVM.PyStackVM import (
    BC128_CMP128S,
    BC128_CMP128U,
    BC_ADD_SP1,
    BC_CMP1,
    BC_CMP8S,
    BC_CONV,
    BC_FCMP_16,
    BC_FCMP_2,
    BC_INT128,
    BC_NE0,
    BC_NOP,
)
from ...code_gen.BaseCmplObj import BaseCmplObj
from ...code_gen.BaseLink import BaseLink
from ...code_gen.LocalCompileData import LocalCompileData
from ...code_gen.compile_expr import compile_expr
from ...code_gen.memory_access import emit_tracked_abs_s8_load
from ...code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from .ContextVariable import ContextVariable
from .qual_atomic_type_util import (
    compare_no_cvr,
    get_base_prim_type,
    get_value_type,
    is_atomic_storage_type,
    is_volatile_storage_type,
)
from .CompileContext import CompileContext
from ..stmnt.CurlyStmnt import CurlyStmnt
from .get_user_str_from_type import get_user_str_from_type
from ..expr.CastOpExpr import CastOpExpr, CastType
from .compile_static_storage_decl import compile_static_storage_decl
from .QualType import QualType
from ..expr.BaseExpr import BaseExpr
