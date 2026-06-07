from typing import Dict, TypeVar, Union, List, Optional

from .BaseType import BaseType, TypeClass

_T = TypeVar("_T")
_U = TypeVar("_U")


def flip_dct(dct: Dict[_T, _U]) -> Dict[_U, _T]:
    return {dct[k]: k for k in dct}


class QualType(BaseType):
    type_class_id = TypeClass.QUAL
    QUAL_DEF = 0
    QUAL_CONST = 1
    QUAL_PTR = 2
    QUAL_VOLATILE = 3
    QUAL_ATOMIC = 4
    QUAL_REG = 5
    QUAL_REF = 6
    QUAL_ARR = 7  # basically a pointer but defines how it is allocated (right where it is declared if not an argument)
    QUAL_FN = 8
    QUAL_CL_FN = 9
    QUAL_CTOR = 10
    QUAL_DTOR = 11
    QUAL_Lst = list(
        map(
            lambda x: "QUAL_" + x,
            "DEF CONST PTR VOLATILE ATOMIC REG REF ARR FN CL_FN CTOR DTOR".split(" "),
        )
    )
    QUAL_Dct = {
        "auto": QUAL_DEF,
        "const": QUAL_CONST,
        "*": QUAL_PTR,
        "volatile": QUAL_VOLATILE,
        "_Atomic": QUAL_ATOMIC,
        "register": QUAL_REG,
        "&": QUAL_REF,
        "[": QUAL_ARR,
        "(": QUAL_FN,
    }
    mangle_captures = {
        "C": QUAL_CONST,
        "P": QUAL_PTR,
        "V": QUAL_VOLATILE,
        "Q": QUAL_ATOMIC,
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
            QualType.QUAL_ATOMIC,
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

    def pretty_repr(self, pretty_repr_ctx=None):
        c_name = self.__class__.__name__
        rtn = (
            [c_name, "(", c_name, ".", self.QUAL_Lst[self.qual_id], ","]
            + get_pretty_repr(self.tgt_type, pretty_repr_ctx)
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
            _variadic = (
                isinstance(self.ext_inf, list)
                and len(self.ext_inf) > 0
                and self.ext_inf[-1] is None
            )
            _params = self.ext_inf[:-1] if _variadic else self.ext_inf
            rtn = ch
            if not top_decl:
                rtn += "Z" + self.tgt_type.to_mangle_str()
            rtn += "".join(map(lambda x: x.to_mangle_str(), _params))
            if _variadic:
                rtn += "."
            return rtn + "z"
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
        elif self.qual_id == QualType.QUAL_ATOMIC:
            s = "_Atomic "
        elif self.qual_id == QualType.QUAL_REG:
            s = "register "
        elif self.qual_id == QualType.QUAL_REF:
            s = "reference to "
        elif self.qual_id == QualType.QUAL_ARR:
            s = "array of "
            if self.ext_inf is not None:
                if isinstance(self.ext_inf, int):
                    s += "%u " % self.ext_inf
                else:
                    s += "<runtime-bound> "
        elif self.qual_id == QualType.QUAL_FN:
            _variadic = (
                isinstance(self.ext_inf, list)
                and len(self.ext_inf) > 0
                and self.ext_inf[-1] is None
            )
            _params = self.ext_inf[:-1] if _variadic else self.ext_inf
            _params_str = ", ".join(map(get_user_str_from_type, _params))
            if _variadic:
                _params_str += (", " if _params else "") + "..."
            s = "function (%s) -> " % _params_str
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
            inp_bits = get_primitive_conv_bits(from_type)
            if self.qual_id == QualType.QUAL_PTR:
                out_bits = 6  # 8-byte unsigned (pointer size); was 3 (2-byte signed) which was wrong
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
                    return compile_expr(
                        cmpl_obj, expr, context, cmpl_data, None, temp_links
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
        maybe_deduce_array_extent(self, init_args)
        is_vla = contains_variable_length_array_type(self)
        sz_var = vla_metadata_size(self) if is_vla else size_of(self)
        ctx_var = None
        decl_ctx_var = None
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
                        if var.typ is self or compare_no_cvr(var.typ, self):
                            ctx_var = var
                            break
                    else:
                        raise NameError(
                            "Could not resolve overloaded variable '%s'" % ctx_var.name
                        )
                    ref = VarRefTosNamed(ctx_var)
                assert isinstance(ctx_var, ContextVariable)
                decl_ctx_var = ctx_var
                name = ctx_var.get_link_name()
                is_local = ctx_var.uses_stack_storage()
                if not is_local:
                    link = cmpl_obj.get_link(name)
            if self.qual_id == QualType.QUAL_FN:
                if is_local:
                    raise TypeError("Functions must be GLOBAL")
                assert isinstance(cmpl_obj, Compilation)
                assert decl_ctx_var is not None
                register_context_symbol(
                    cmpl_obj,
                    decl_ctx_var,
                    self,
                    bool(init_args),
                    0,
                )
                cmpl_obj.register_lifecycle_function(
                    decl_ctx_var.get_link_name(),
                    self,
                    decl_ctx_var.attributes,
                )
                if decl_ctx_var.alias_name is not None and init_args:
                    raise TypeError("alias declarations cannot define a function body")
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
        static_res = None
        if self.qual_id != QualType.QUAL_FN:
            static_res = compile_static_storage_decl(
                self, cmpl_obj, init_args, context, ref, cmpl_data, temp_links
            )
        if static_res is not None:
            return static_res
        # Creation stage (in program)
        if self.qual_id in [
            QualType.QUAL_DEF,
            QualType.QUAL_CONST,
            QualType.QUAL_VOLATILE,
            QualType.QUAL_ATOMIC,
            QualType.QUAL_REG,
        ]:
            return self.tgt_type.compile_var_init(
                cmpl_obj, init_args, context, ref, cmpl_data, temp_links
            )
        elif self.qual_id in [QualType.QUAL_PTR, QualType.QUAL_REF, QualType.QUAL_ARR]:
            if is_vla:
                if self.qual_id != QualType.QUAL_ARR:
                    raise TypeError(
                        "Variable-length array qualifiers must resolve to an array"
                    )
                if len(init_args) != 0:
                    raise TypeError("Variable-length arrays cannot be initialized")
                if not is_local or ctx_var is None or cmpl_data is None:
                    raise TypeError("Variable-length arrays require local stack storage")
                from ...code_gen.vla import emit_runtime_sizeof

                sz_cls = emit_load_i_const(
                    cmpl_obj.memory, vla_metadata_size(self), False
                )
                cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
                size_lnk = cmpl_data.reserve_stack_storage(
                    ctx_var, vla_metadata_size(self), None, True
                )
                emit_runtime_sizeof(
                    cmpl_obj, self, context, cmpl_data, temp_links
                )
                size_lnk.emit_stor(
                    cmpl_obj.memory, 8, cmpl_obj, byte_copy_cmpl_intrinsic
                )
                size_lnk.emit_load(
                    cmpl_obj.memory, 8, cmpl_obj, byte_copy_cmpl_intrinsic
                )
                cmpl_obj.memory.extend([BC_ADD_SP8])
                vla_lnk = DynamicLocalRef(
                    cmpl_data.bp_off,
                    0,
                    cmpl_data.dynamic_stack_size_links + [size_lnk],
                    vla_size_link=size_lnk,
                )
                cmpl_data.setitem(name, (ctx_var, vla_lnk), vla_metadata_size(self))
                cmpl_data.dynamic_stack_size_links.append(size_lnk)
                return vla_metadata_size(self)
            if (
                self.qual_id == QualType.QUAL_ARR
                and len(init_args) == 1
                and isinstance(init_args[0], CurlyExpr)
                and init_args[0].lst_expr is not None
            ):
                curly = init_args[0]
                arr_len = self.ext_inf
                if arr_len is None:
                    raise TypeError(
                        "Array extent could not be deduced from initializer"
                    )
                elem_sz = size_of(self.tgt_type)
                if link is None:
                    assert is_local
                    sz_cls = emit_load_i_const(cmpl_obj.memory, sz_var, False)
                    cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
                    assert ctx_var is not None
                    assert cmpl_data is not None
                    lnk = cmpl_data.put_local(ctx_var, name, sz_var, None, True)
                else:
                    lnk = link
                zero_init_link(
                    cmpl_obj,
                    lnk,
                    sz_var,
                    volatile_access=is_volatile_storage_type(
                        self if ctx_var is None else ctx_var.typ
                    ),
                )
                next_index = 0
                for elem in curly.lst_expr:
                    target_index = next_index
                    subexpr = elem
                    if isinstance(elem, DesigInitExpr):
                        if elem.kind != DesigInitExpr.KIND_INDEX:
                            raise TypeError(
                                "Cannot use field designators in an array initializer"
                            )
                        target_index = elem.designator
                        subexpr = elem.expr
                    if target_index >= arr_len or subexpr is None:
                        raise TypeError("Too many elements in array initializer")
                    elem_lnk = lnk.get_offset_link(target_index * elem_sz)
                    self.tgt_type.compile_var_init(
                        cmpl_obj,
                        [subexpr],
                        context,
                        VarRefLnkPrealloc(elem_lnk),
                        cmpl_data,
                        temp_links,
                    )
                    next_index = target_index + 1
                return sz_var
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
            variadic = (
                isinstance(self.ext_inf, list)
                and len(self.ext_inf) > 0
                and self.ext_inf[-1] is None
            )
            params = self.ext_inf[:-1] if variadic else self.ext_inf
            off = -16
            fn_ctx = the_arg.context.parent
            assert isinstance(fn_ctx, LocalScope)
            assert not isinstance(params, int)
            res_link = None
            res_type = self.tgt_type
            if variadic:
                sz1 = 8  # sizeof(T*)
                res_link = IndirectLink(LocalRef.from_bp_off_post_inc(off, sz1))
                off -= 8
            for Param in params:
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
            cmpl_obj1.debug_frame_size = cmpl_data1.max_frame_size
            cmpl_obj1.debug_return_address_offset = 0
            cmpl_obj1.debug_previous_bp_offset = 8
            # Backpatch goto and asm-goto labels after the full body is emitted.
            for _label_name, _lnk in cmpl_data1.local_labels.items():
                if _lnk.src is None:
                    if _lnk.lst_tgt or _label_name in cmpl_data1.local_label_references:
                        raise NameError(
                            "Undefined label '%s' referenced by goto" % _label_name
                        )
                else:
                    _lnk.fill_all(cmpl_obj1.memory)
            cmpl_obj1.memory.extend([BC_RET])
            assert decl_ctx_var is not None
            register_context_symbol(
                cmpl_obj,
                decl_ctx_var,
                self,
                True,
                len(cmpl_obj1.memory),
            )
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
                    cmpl_obj.memory,
                    sz_var,
                    cmpl_obj,
                    byte_copy_cmpl_intrinsic,
                    volatile_access=is_volatile_storage_type(self),
                    atomic_access=is_atomic_storage_type(self),
                )
        return sz_var

    def compile_var_de_init(self, cmpl_obj, context, ref, cmpl_data=None) -> int:
        if self.qual_id in [
            QualType.QUAL_CONST,
            QualType.QUAL_REG,
            QualType.QUAL_DEF,
            QualType.QUAL_VOLATILE,
            QualType.QUAL_ATOMIC,
        ]:
            return self.tgt_type.compile_var_de_init(cmpl_obj, context, ref, cmpl_data)
        elif self.qual_id == QualType.QUAL_ARR:
            if contains_variable_length_array_type(self):
                if ref.ref_type != VAR_REF_TOS_NAMED:
                    raise TypeError("Cannot de-initialize unnamed VLA storage")
                assert isinstance(ref, VarRefTosNamed)
                if cmpl_data is None:
                    raise TypeError("VLA de-initialization requires local data")
                lnk = cmpl_data.get_local(ref.ctx_var.get_link_name())
                size_lnk = getattr(lnk, "vla_size_link", None)
                if size_lnk is None:
                    raise TypeError("Missing VLA size metadata for de-initialization")
                size_lnk.emit_load(
                    cmpl_obj.memory, 8, cmpl_obj, byte_copy_cmpl_intrinsic
                )
                cmpl_obj.memory.extend([BC_RST_SP8])
                return 0
            return -1
        elif self.qual_id == QualType.QUAL_FN:
            raise TypeError("cannot destroy a function")
        # QUAL_REF, QUAL_PTR, QUAL_FN
        return -1


from ...code_gen.byte_copy_cmpl_intrinsic import byte_copy_cmpl_intrinsic
from ...code_gen.zero_init_link import zero_init_link
from ...code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from ...PrettyRepr import get_pretty_repr
from .ContextVariable import ContextVariable, VarDeclMods
from .IdentifiedQualType import IdentifiedQualType
from .OverloadedCtxVar import OverloadedCtxVar
from .qual_atomic_type_util import (
    is_atomic_storage_type,
    compare_no_cvr,
    is_volatile_storage_type,
    get_value_type,
)
from .align_size_of import size_of
from ...code_gen.LocalRef import LocalRef
from ...code_gen.DynamicLocalRef import DynamicLocalRef
from ...code_gen.Compilation import CompileObjectType, Compilation
from ...code_gen.LocalCompileData import LocalCompileData
from .LocalScope import LocalScope
from .get_user_str_from_type import get_user_str_from_type
from ..expr.DesigInitExpr import DesigInitExpr
from ..expr.LiteralExpr import LiteralExpr
from .maybe_deduce_array_extent import maybe_deduce_array_extent
from ...code_gen.IndirectLink import IndirectLink
from ...code_gen.compile_expr import compile_expr
from ..stmnt.CurlyStmnt import CurlyStmnt
from ..expr.CurlyExpr import CurlyExpr
from ..expr.CastOpExpr import CastOpExpr, CastType
from .from_mangle import from_mangle
from .make_void_fn import make_void_fn
from ..expr.BaseExpr import BaseExpr, ExprType
from .PrimitiveType import PrimitiveType, get_primitive_conv_bits
from .compile_static_storage_decl import compile_static_storage_decl
from .vla import contains_variable_length_array_type, vla_metadata_size
from .helpers.VarRef import (
    VAR_REF_LNK_PREALLOC,
    VAR_REF_TOS_NAMED,
    VarRefLnkPrealloc,
    VarRefTosNamed,
)
from .register_context_symbol import register_context_symbol
from ...code_gen.compile_curly import compile_curly
from ...StackVM.PyStackVM import BC_RET, BC_ADD_SP1, BC_ADD_SP8, BC_RST_SP8
from .is_fn_type import is_fn_type
