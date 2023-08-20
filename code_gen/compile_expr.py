from typing import Optional, List, Tuple
from ..parser.util import try_catch_wrapper_co_expr


@try_catch_wrapper_co_expr
def compile_expr(
    cmpl_obj: "BaseCmplObj",
    expr: "BaseExpr",
    context: "CompileContext",
    cmpl_data: Optional["LocalCompileData"] = None,
    type_coerce: Optional["BaseType"] = None,
    temp_links: Optional[List[Tuple["BaseType", "BaseLink"]]] = None,
):
    if type_coerce is void_t:
        if expr.expr_id in {ExprType.LITERAL, ExprType.NAME}:
            return 0
    owns_temps = temp_links is None
    if owns_temps:
        temp_links = setup_temp_links(cmpl_obj, expr, context, cmpl_data)
    sz = 0 if expr.t_anot is None else size_of(expr.t_anot)
    res_type = expr.t_anot
    assert isinstance(res_type, BaseType)
    if expr.expr_id == ExprType.LITERAL:
        assert isinstance(expr, LiteralExpr)
        assert expr.t_anot is not None
        sz = size_of(expr.t_anot)
        if expr.t_lit in [
            LiteralExpr.LIT_CHR,
            LiteralExpr.LIT_FLOAT,
            LiteralExpr.LIT_INT,
        ]:
            sz_cls = sz.bit_length() - 1
            assert 0 <= sz_cls <= 3, "Invalid Size Class"
            sz1 = 1 << sz_cls
            if sz1 != sz:
                print(
                    "WARNING: Literal %r does not conform to a specific SizeClass sz=%u"
                    % (expr, sz)
                )
            prim_type = get_base_prim_type(expr.t_anot)
            assert isinstance(prim_type, PrimitiveType)
            cmpl_obj.memory.extend([BC_LOAD, BCR_ABS_C | (sz_cls << 5)])
            if expr.t_lit == LiteralExpr.LIT_FLOAT:
                if sz_cls == 2:
                    cmpl_obj.memory.extend(float_t.pack(expr.l_val))
                elif sz_cls == 3:
                    cmpl_obj.memory.extend(double_t.pack(expr.l_val))
                else:
                    raise TypeError("Only 4 and 8 byte floats are supported")
            else:
                cmpl_obj.memory.extend(
                    sz_cls_align_long(expr.l_val, prim_type.sign, sz_cls)
                )
            sz = sz1
        elif expr.t_lit == LiteralExpr.LIT_STR:
            prim_type, val_type, is_ref = get_tgt_ref_type(res_type)
            assert isinstance(prim_type, QualType)
            assert isinstance(val_type, QualType)
            assert is_ref
            assert val_type.qual_id == QualType.QUAL_ARR
            prim_type_coerce = (
                prim_type if type_coerce is None else get_base_prim_type(type_coerce)
            )
            elem_type = val_type.tgt_type
            sz_elem = size_of(elem_type)
            v_lit_bytes = bytearray(size_of(val_type))
            for c in range(len(expr.l_val)):
                v_lit_bytes[c * sz_elem : (c + 1) * sz_elem] = expr.l_val[c].to_bytes(
                    sz_elem, "little"
                )
            link = cmpl_obj.get_string_link(bytes(v_lit_bytes))
            if prim_type_coerce is not None and isinstance(prim_type_coerce, QualType):
                if prim_type_coerce.qual_id == QualType.QUAL_ARR:
                    sz = len(v_lit_bytes)
                    link.emit_load(
                        cmpl_obj.memory, sz, cmpl_obj, byte_copy_cmpl_intrinsic
                    )
                    res_type = val_type
                    """Link1 = cmpl_obj.GetLink("@@ByteCopyFn1")
                    Byts1 = SzClsAlignLong(len(v_lit_bytes), False, 3)
                    # Begin add Stack
                    cmpl_obj.memory.extend([
                        BC_LOAD, BCR_ABS_C | BCR_SZ_8])
                    cmpl_obj.memory.extend(Byts1)
                    cmpl_obj.memory.extend([BC_ADD_SP8])
                    # end add Stack
                    # push [src]
                    link.EmitLEA(cmpl_obj.memory)
                    # Begin push [Size]
                    cmpl_obj.memory.extend([
                        BC_LOAD, BCR_ABS_C | BCR_SZ_8])
                    cmpl_obj.memory.extend(Byts1)
                    # end push [Size]
                    Link1.EmitLEA(cmpl_obj.memory)
                    cmpl_obj.memory.extend([BC_CALL])
                    sz = len(v_lit_bytes)"""
                elif prim_type_coerce.qual_id == QualType.QUAL_PTR:
                    assert compare_no_cvr(prim_type_coerce.tgt_type, elem_type)
                    link.emit_lea(cmpl_obj.memory)
                    sz = 8
                    res_type = QualType(QualType.QUAL_PTR, elem_type)
                elif prim_type_coerce.qual_id == QualType.QUAL_REF:
                    assert compare_no_cvr(prim_type_coerce.tgt_type, val_type)
                    link.emit_lea(cmpl_obj.memory)
                    sz = 8
                    res_type = prim_type
                else:
                    raise TypeError(
                        "Unsupported type_coerce = %s"
                        % get_user_str_from_type(type_coerce)
                    )
            else:
                raise TypeError("Unknown annotated type: %r" % expr.t_anot)
    elif expr.expr_id == ExprType.PARENTH:
        assert isinstance(expr, ParenthExpr)
        if len(expr.lst_expr) != 1:
            raise NotImplementedError(
                "ParenthExpr compilation is not supported when len(lst_expr) != 1"
            )
        if type_coerce is not None:
            res_type = type_coerce
        sz = compile_expr(
            cmpl_obj, expr.lst_expr[0], context, cmpl_data, type_coerce, temp_links
        )
    elif expr.expr_id == ExprType.FN_CALL:
        assert isinstance(expr, FnCallExpr)
        if expr.fn.expr_id != ExprType.NAME:
            raise SyntaxError("Only Named functions can be called")
        assert isinstance(expr.fn, NameRefExpr)
        variadic = False
        sz0 = 0
        lst_arg_types = []
        fn_type = None if expr.fn.t_anot is None else get_value_type(expr.fn.t_anot)
        if fn_type is None:
            print("Cannot call an expression that is not type-annotated")
            # raise TypeError("Cannot call an expression that is not type-annotated")
        elif fn_type.type_class_id != TypeClass.QUAL:
            print("Cannot call a non-function expression")
            # raise TypeError("Cannot call a non-function expression")
        else:
            assert isinstance(fn_type, QualType)
            if fn_type.qual_id != QualType.QUAL_FN:
                print("Cannot call a non-function expression")
                # raise TypeError("Cannot call a non-function expression")
            else:
                lst_arg_types = list(fn_type.ext_inf)
                for c in range(len(lst_arg_types)):
                    cur = lst_arg_types[c]
                    if cur is not None and isinstance(cur, IdentifiedQualType):
                        cur = cur.typ
                        lst_arg_types[c] = cur
        res_type = fn_type.tgt_type
        sz_ret = size_of(res_type)
        sz_cls_ret = emit_load_i_const(cmpl_obj.memory, sz_ret, False)
        cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls_ret])
        lnk_ret = LocalRef.from_bp_off_pre_inc(cmpl_data.bp_off, sz_ret)
        cmpl_data.bp_off += sz_ret
        c = len(expr.lst_args)
        while c > 0:
            c -= 1
            arg = expr.lst_args[c]
            coerce_t = None
            if c < len(lst_arg_types):
                coerce_t = fn_type.ext_inf[c]
                if isinstance(coerce_t, IdentifiedQualType):
                    coerce_t = coerce_t.typ
            assert coerce_t is None or isinstance(coerce_t, BaseType)
            sz = compile_expr(cmpl_obj, arg, context, cmpl_data, coerce_t, temp_links)
            cmpl_data.bp_off += sz
            sz0 += sz
        if variadic:
            lnk_ret.emit_lea(cmpl_obj.memory)
            cmpl_data.bp_off += 8
            sz0 += 8
        sz_addr = compile_expr(cmpl_obj, expr.fn, context, cmpl_data, None, temp_links)
        assert sz_addr == 8
        cmpl_obj.memory.extend([BC_CALL])
        sz_cls = emit_load_i_const(cmpl_obj.memory, sz0, False)
        cmpl_obj.memory.extend([BC_RST_SP1 + sz_cls])
        cmpl_data.bp_off -= sz0
        cmpl_data.bp_off -= sz_ret
        sz = sz_ret
    elif expr.expr_id == ExprType.PTR_MEMBER:
        assert isinstance(expr, SpecialPtrMemberExpr)
        prim_type = get_base_prim_type(expr.obj.t_anot)
        assert prim_type.type_class_id == TypeClass.QUAL, "Must be pointer"
        assert isinstance(prim_type, QualType)
        assert prim_type.qual_id == QualType.QUAL_PTR, "Must be pointer"
        val_type = get_base_prim_type(prim_type.tgt_type)
        if val_type.type_class_id == TypeClass.UNION:
            assert isinstance(val_type, UnionType)
            return compile_expr(
                cmpl_obj, expr.obj, context, cmpl_data, prim_type, temp_links
            )
        raise NotImplementedError("Not Implemented")
    elif expr.expr_id == ExprType.DOT:
        assert isinstance(expr, SpecialDotExpr)
        prim_type, val_type, is_ref = get_tgt_ref_type(expr.obj.t_anot)
        if not is_ref:
            raise TypeError("Cannot use dot operator on non-reference type")
        if val_type.type_class_id == TypeClass.UNION:
            assert isinstance(val_type, UnionType)
            return compile_expr(
                cmpl_obj, expr.obj, context, cmpl_data, prim_type, temp_links
            )
        elif val_type.type_class_id == TypeClass.STRUCT:
            assert isinstance(val_type, StructType)
            compile_expr(cmpl_obj, expr.obj, context, cmpl_data, prim_type, temp_links)
            emit_load_i_const(cmpl_obj.memory, val_type.offset_of(expr.attr), False, 3)
            cmpl_obj.memory.extend([BC_ADD8])
            return 8
        elif val_type.type_class_id == TypeClass.CLASS:
            assert isinstance(val_type, ClassType)
            compile_expr(cmpl_obj, expr.obj, context, cmpl_data, prim_type, temp_links)
            emit_load_i_const(cmpl_obj.memory, val_type.offset_of(expr.attr), False, 3)
            cmpl_obj.memory.extend([BC_ADD8])
            return 8
        # TODO: add 2 opcodes or use a memory reference (BCR_R_BP)
        #   one for this ---keep----[data you don't want][data you want] -> -keep--[data you want]
        #   one for getting the current stack pointer
    elif expr.expr_id == ExprType.NAME:
        # TODO: right now name resolution is done at CodeGen time
        # TODO:   maybe this needs to be changed so that name resolution
        # TODO:   is done at Parse Time
        assert isinstance(expr, NameRefExpr)
        ctx_var = expr.ctx_var
        assert isinstance(ctx_var, ContextVariable)
        lnk_name = ctx_var.get_link_name()
        lnk = (
            cmpl_data.get_local(lnk_name)
            if ctx_var.parent.is_local_scope()
            else cmpl_obj.get_link(lnk_name)
        )
        assert isinstance(lnk, BaseLink)
        if type_coerce is None:
            if res_type is None:
                raise TypeError("Cannot process NameRefExpr without t_anot")
            assert isinstance(res_type, QualType)
            assert res_type.qual_id == QualType.QUAL_REF
            lnk.emit_lea(cmpl_obj.memory)
            sz = 8
        else:
            prim_type_coerce = get_base_prim_type(type_coerce)
            val_type = get_base_prim_type(ctx_var.typ)
            do_as_ref = False
            # do_as_val = False
            if prim_type_coerce.type_class_id == TypeClass.QUAL:
                assert isinstance(prim_type_coerce, QualType)
                do_as_ref = prim_type_coerce.qual_id == QualType.QUAL_REF
            if do_as_ref:
                lnk.emit_lea(cmpl_obj.memory)
                sz = 8
            else:
                res_type = val_type
                if compare_no_cvr(prim_type_coerce, val_type):
                    sz = size_of(val_type)
                    # TODO: change this so that the BaseType subclasses are responsible for construction
                    # TODO:   from a pointer already on the stack
                    lnk.emit_load(
                        cmpl_obj.memory, sz, cmpl_obj, byte_copy_cmpl_intrinsic
                    )
                else:
                    raise TypeError(
                        "Expected type_coerce to be reference or value type: type_coerce = %r, val_type = %r"
                        % (type_coerce, val_type)
                    )
    elif expr.expr_id == ExprType.CAST:
        assert isinstance(expr, CastOpExpr)
        assert expr.t_anot is not None
        if expr.cast_type == CastType.EXPLICIT:
            print("WARN: Explicit casts are treated the same way as implicit casts")
        sz = compile_conv_general(cmpl_obj, expr, context, cmpl_data, temp_links)
    elif expr.expr_id == ExprType.BIN_OP:
        assert isinstance(expr, BinaryOpExpr)
        sz, res_type = compile_bin_op_expr(
            cmpl_obj, expr, context, cmpl_data, type_coerce, temp_links, res_type
        )
    elif expr.expr_id == ExprType.SPARENTH:
        assert isinstance(expr, SParenthExpr)
        assert expr.t_anot is not None
        sz = compile_expr(
            cmpl_obj, expr.left_expr, context, cmpl_data, None, temp_links
        )
        assert sz == 8
        sz_elem = size_of(get_value_type(expr.t_anot))
        sz = compile_expr(
            cmpl_obj, expr.inner_expr, context, cmpl_data, None, temp_links
        )
        assert sz == 8, "expr = %r, expr.t_anot = %r" % (
            expr,
            expr.t_anot,
        )  # sizeof(SizeL)
        if sz_elem != 1:
            emit_load_i_const(cmpl_obj.memory, sz_elem, False, 3)
            cmpl_obj.memory.extend([BC_MUL8, BC_ADD8])
        else:
            cmpl_obj.memory.append(BC_ADD8)
    elif expr.expr_id == ExprType.UNI_OP:
        assert isinstance(expr, UnaryOpExpr)
        assert expr.t_anot is not None
        if expr.type_id in [UnaryExprSubType.REFERENCE, UnaryExprSubType.STAR]:
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
            assert sz == 8
        elif expr.type_id == UnaryExprSubType.BOOL_NOT:
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, bool_t, temp_links)
            assert sz == 1
            cmpl_obj.memory.append(BC_EQ0)
            res_type = bool_t
        elif expr.type_id == UnaryExprSubType.BIT_NOT:
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
            sz_cls = sz.bit_length() - 1
            assert 1 << sz_cls == sz and 0 <= sz_cls <= 3
            cmpl_obj.memory.append(BC_NOT1 + sz_cls)
        elif expr.type_id == UnaryExprSubType.MINUS:
            typ_bits = get_bc_conv_bits(expr.a.t_anot)
            sz_cls = (typ_bits & 0x7) >> (0 if typ_bits & 0x8 else 1)
            sub_code = (BC_FSUB_2 if typ_bits & 0x8 else BC_SUB1) + sz_cls
            assert BC_FSUB_2 <= sub_code <= BC_FSUB_16 or BC_SUB1 <= sub_code <= BC_SUB8
            emit_load_i_const(cmpl_obj.memory, 0, False, 0)
            cmpl_obj.memory.extend(
                [
                    BC_CONV,
                    typ_bits << 4,  # input bits are 0 for unsigned byte
                ]
            )
            res_type = expr.a.t_anot
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
            cmpl_obj.memory.append(sub_code)
        elif expr.type_id == UnaryExprSubType.PLUS:
            res_type = expr.a.t_anot
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
        elif expr.type_id in [
            UnaryExprSubType.PRE_DEC,
            UnaryExprSubType.PRE_INC,
            UnaryExprSubType.POST_DEC,
            UnaryExprSubType.POST_INC,
        ]:
            inc_by = 0
            sz_num = 8
            if expr.op_fn_type == OperatorType.NATIVE:
                inc_by = 1
                sz_num = size_of(prim_types[expr.op_fn_data])
            elif expr.op_fn_type == OperatorType.PTR_GENERIC:
                inc_by = expr.op_fn_data
                sz_num = 8
            if inc_by == 0:
                raise NotImplementedError(
                    "Expression (id = UnaryExprSubType.OP_EXPR, type_id = %u) compilation of OperatorType.FUNCTION or void *"
                    % expr.type_id
                )
            sz_cls = sz_num.bit_length() - 1
            assert 1 << sz_cls == sz_num
            a_type = expr.a.t_anot
            sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
            assert sz == 8 and a_type.type_class_id == TypeClass.QUAL
            assert isinstance(a_type, QualType)
            assert a_type.qual_id == QualType.QUAL_REF
            swap_byte = (sz_cls << 3) | BCS_SZ8_A
            load_byte = BCR_ABS_S8 | (sz_cls << 5)
            is_add = expr.type_id in [
                UnaryExprSubType.PRE_INC,
                UnaryExprSubType.POST_INC,
            ]
            if expr.type_id in [UnaryExprSubType.PRE_DEC, UnaryExprSubType.PRE_INC]:
                if type_coerce is void_t:
                    res_type = void_t
                    sz = 0
                else:
                    cmpl_obj.memory.extend(
                        [
                            BC_LOAD,
                            BCR_TOS | BCR_SZ_8,  # reference that is returned
                        ]
                    )
                cmpl_obj.memory.extend(
                    [
                        BC_LOAD,
                        BCR_TOS | BCR_SZ_8,
                        BC_LOAD,
                        load_byte,
                    ]
                )
            else:
                if type_coerce is void_t:
                    res_type = void_t
                    sz = 0
                    cmpl_obj.memory.extend(
                        [
                            BC_LOAD,
                            BCR_TOS | BCR_SZ_8,
                            BC_LOAD,
                            load_byte,
                        ]
                    )
                else:
                    res_type = get_value_type(a_type)
                    sz = size_of(res_type)
                    cmpl_obj.memory.extend(
                        [
                            BC_LOAD,
                            BCR_TOS | BCR_SZ_8,
                            BC_LOAD,
                            load_byte,
                            BC_SWAP,
                            swap_byte,
                            BC_LOAD,
                            BCR_TOS | BCR_SZ_8,
                            BC_LOAD,
                            load_byte,
                        ]
                    )
            emit_load_i_const(cmpl_obj.memory, inc_by, False, sz_cls)
            cmpl_obj.memory.extend(
                [
                    (BC_ADD1 if is_add else BC_SUB1) + sz_cls,
                    BC_SWAP,
                    swap_byte,
                    BC_STOR,
                    load_byte,
                ]
            )

        else:
            raise NotImplementedError(
                "Expression (id = UnaryExprSubType.OP_EXPR, type_id = %u) compilation is not supported"
                % expr.type_id
            )
    else:
        raise NotImplementedError(
            "Expression (id = %u) compilation is not supported" % expr.expr_id
        )
    if owns_temps:
        tear_down_temp_links(cmpl_obj, temp_links, expr, context, cmpl_data)
    if type_coerce is void_t and not compare_no_cvr(res_type, type_coerce):
        sz_cls_rst = emit_load_i_const(cmpl_obj.memory, sz, False)
        cmpl_obj.memory.extend([BC_RST_SP1 + sz_cls_rst])
        # res_type = void_t
        sz = 0
    elif type_coerce is not None and not compare_no_cvr(res_type, type_coerce):
        raise CompileExprException(
            {
                "message": "The Expression result type is %s and cannot coerce to %s; expr = %r, sz = %d"
                % (
                    get_user_str_from_type(res_type),
                    get_user_str_from_type(type_coerce),
                    expr,
                    sz,
                ),
                "expr": expr,
                "type_coerce": type_coerce,
                "res_type": res_type,
            }
        )
    return sz


from .BaseCmplObj import BaseCmplObj
from .BaseLink import BaseLink
from .CompileExprException import CompileExprException
from .LocalCompileData import LocalCompileData
from .LocalRef import LocalRef
from .byte_copy_cmpl_intrinsic import byte_copy_cmpl_intrinsic
from .compile_bin_op_expr import compile_bin_op_expr
from .compile_conv_general import compile_conv_general
from .compile_expr import compile_expr
from .get_bc_conv_bits import get_bc_conv_bits
from .setup_temp_links import setup_temp_links
from .tear_down_temp_links import tear_down_temp_links
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from .stackvm_binutils.sz_cls_align_long import sz_cls_align_long
from ..StackVM.PyStackVM import (
    BCR_ABS_C,
    BCR_ABS_S8,
    BCR_SZ_8,
    BCR_TOS,
    BCS_SZ8_A,
    BC_ADD1,
    BC_ADD8,
    BC_ADD_SP1,
    BC_CALL,
    BC_CONV,
    BC_EQ0,
    BC_FSUB_16,
    BC_FSUB_2,
    BC_LOAD,
    BC_MUL8,
    BC_NOT1,
    BC_RST_SP1,
    BC_STOR,
    BC_SUB1,
    BC_SUB8,
    BC_SWAP,
    double_t,
    float_t,
)
from ..parser.expr.BaseExpr import BaseExpr, ExprType
from ..parser.expr.BinaryOpExpr import BinaryOpExpr
from ..parser.expr.CastOpExpr import CastOpExpr, CastType
from ..parser.expr.FnCallExpr import FnCallExpr
from ..parser.expr.LiteralExpr import LiteralExpr
from ..parser.expr.NameRefExpr import NameRefExpr
from ..parser.expr.OperatorType import OperatorType
from ..parser.expr.ParenthExpr import ParenthExpr
from ..parser.expr.SParenthExpr import SParenthExpr
from ..parser.expr.SpecialDotExpr import SpecialDotExpr
from ..parser.expr.SpecialPtrMemberExpr import SpecialPtrMemberExpr
from ..parser.expr.UnaryOpExpr import UnaryExprSubType, UnaryOpExpr
from ..parser.type.BaseType import BaseType, TypeClass
from ..parser.type.get_user_str_from_type import get_user_str_from_type
from ..parser.type.types import (
    ClassType,
    CompileContext,
    ContextVariable,
    IdentifiedQualType,
    PrimitiveType,
    QualType,
    StructType,
    UnionType,
    bool_t,
    compare_no_cvr,
    get_base_prim_type,
    get_tgt_ref_type,
    get_value_type,
    prim_types,
    size_of,
    void_t,
)
