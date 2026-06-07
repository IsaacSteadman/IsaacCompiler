from typing import List, Optional, Tuple


def _get_int128_subop(expr_type, is_sign):
    if expr_type in {BinaryExprSubType.ASSGN_MOD, BinaryExprSubType.MOD}:
        return BC128_MOD128S if is_sign else BC128_MOD128U
    if expr_type in {BinaryExprSubType.ASSGN_DIV, BinaryExprSubType.DIV}:
        return BC128_DIV128S if is_sign else BC128_DIV128U
    if expr_type in {BinaryExprSubType.ASSGN_MUL, BinaryExprSubType.MUL}:
        return BC128_MUL128S if is_sign else BC128_MUL128U
    if expr_type in {BinaryExprSubType.ASSGN_MINUS, BinaryExprSubType.MINUS}:
        return BC128_SUB128S if is_sign else BC128_SUB128U
    if expr_type in {BinaryExprSubType.ASSGN_PLUS, BinaryExprSubType.PLUS}:
        return BC128_ADD128S if is_sign else BC128_ADD128U
    if expr_type in {BinaryExprSubType.ASSGN_AND, BinaryExprSubType.AND}:
        return BC128_AND128
    if expr_type in {BinaryExprSubType.ASSGN_OR, BinaryExprSubType.OR}:
        return BC128_OR128
    if expr_type in {BinaryExprSubType.ASSGN_XOR, BinaryExprSubType.XOR}:
        return BC128_XOR128
    if expr_type in {BinaryExprSubType.ASSGN_RSHIFT, BinaryExprSubType.RSHIFT}:
        return BC128_RSHIFT128S if is_sign else BC128_RSHIFT128U
    if expr_type in {BinaryExprSubType.ASSGN_LSHIFT, BinaryExprSubType.LSHIFT}:
        return BC128_LSHIFT128
    if expr_type in CMP_OPS:
        return BC128_CMP128S if is_sign else BC128_CMP128U
    return None


def _compile_bit_field_assign(cmpl_obj, expr, context, cmpl_data, temp_links, bfi, typ):
    """Emit a read-modify-write sequence for a simple bit-field assignment.

    Stack on entry: [..., ptr(8)]  — ptr to the storage-unit byte.
    Stack on exit:  [...] (res_none=True).
    """
    sz_cls_bf = bfi.storage_sz.bit_length() - 1
    all_bits = (1 << (bfi.storage_sz * 8)) - 1
    clear_mask = all_bits & ~(bfi.bit_mask << bfi.bit_shift)

    # DUP the storage-unit pointer: [..., ptr(8), ptr_dup(8)]
    cmpl_obj.memory.extend([BC_LOAD, BCR_TOS | BCR_SZ_8])
    # LOAD storage unit through the dup: [..., ptr(8), su(storage_sz)]
    emit_tracked_abs_s8_load(
        cmpl_obj,
        bfi.storage_sz,
        is_volatile_storage_type(expr.a.t_anot, through_ref=True),
        atomic_access=is_atomic_storage_type(expr.a.t_anot, through_ref=True),
    )
    # AND with the clear mask to zero the target field bits
    emit_load_i_const(cmpl_obj.memory, clear_mask, False, sz_cls_bf)
    cmpl_obj.memory.append(BC_AND1 + sz_cls_bf)
    # Compile the RHS new value: [..., ptr(8), su_cleared(storage_sz), new_val]
    compile_expr(cmpl_obj, expr.b, context, cmpl_data, typ, temp_links)
    # Mask new value to the bit-field width
    emit_load_i_const(cmpl_obj.memory, bfi.bit_mask, False, sz_cls_bf)
    cmpl_obj.memory.append(BC_AND1 + sz_cls_bf)
    # Shift into position
    if bfi.bit_shift > 0:
        emit_load_i_const(cmpl_obj.memory, bfi.bit_shift, False, 0)
        cmpl_obj.memory.append(BC_LSHIFT1 + sz_cls_bf)
    # OR the cleared unit with the shifted new value
    cmpl_obj.memory.append(BC_OR1 + sz_cls_bf)
    # SWAP to bring ptr to TOS: [..., modified_su(storage_sz), ptr(8)]
    cmpl_obj.memory.extend([BC_SWAP, (sz_cls_bf << 3) | BCS_SZ8_A])
    # STOR modified storage unit through ptr: [...]
    emit_tracked_abs_s8_stor(
        cmpl_obj,
        bfi.storage_sz,
        is_volatile_storage_type(expr.a.t_anot, through_ref=True),
        atomic_access=is_atomic_storage_type(expr.a.t_anot, through_ref=True),
    )
    return 0, void_t


def compile_bin_op_expr(
    cmpl_obj: "BaseCmplObj",
    expr: "BinaryOpExpr",
    context: "CompileContext",
    cmpl_data: Optional["LocalCompileData"],
    type_coerce: Optional["BaseType"],
    temp_links: Optional[List[Tuple["BaseType", "BaseLink"]]],
    res_type: Optional["BaseType"],
) -> Tuple[int, "BaseType"]:
    assert expr.t_anot is not None
    typ = None
    is_flt = False
    is_sign = False
    sz_type = 8
    sz_cls = 3
    inc_by = 1
    inc_by_before = True
    if expr.op_fn_type == OperatorType.PTR_GENERIC:
        src_pt, typ, is_src_ref = get_tgt_ref_type(expr.a.t_anot)
        assert isinstance(typ, QualType)
        assert typ.qual_id == QualType.QUAL_PTR
        if expr.op_fn_data < 2:
            is_sign = bool(expr.op_fn_data & 1)
        else:
            assert expr.op_fn_data == 2
            is_sign = True
    elif expr.op_fn_type == OperatorType.NATIVE:
        # src_pt = get_base_prim_type(expr.a.t_anot)
        typ = prim_types[expr.op_fn_data]
        is_flt = typ.typ in FLT_TYPE_CODES
        is_sign = typ.sign
        sz_type = typ.size
        sz_cls = sz_type.bit_length() - 1
    if typ is None:
        raise NotImplementedError("Not Implemented: op_fn_type = %u" % expr.op_fn_type)
    assert (1 << sz_cls) == sz_type
    sz1 = 0
    if (
        expr.type_id == BinaryExprSubType.ASSGN
        and expr.a.expr_id == ExprType.NAME
        and type_coerce is void_t
    ):
        a = expr.a
        b = expr.b
        res_type = void_t
        sz = 0
        assert isinstance(a, NameRefExpr)
        ctx_var = a.ctx_var
        assert isinstance(ctx_var, ContextVariable)
        lnk_name = ctx_var.get_link_name()
        lnk = (
            cmpl_data.get_local(lnk_name)
            if ctx_var.uses_stack_storage()
            else cmpl_obj.get_link(lnk_name)
        )
        assert isinstance(lnk, BaseLink)
        lnk = wrap_tls_link(cmpl_obj, ctx_var, lnk)
        a_value_type = ctx_var.typ
        sizeof_a = size_of(ctx_var.typ)
        sz_out_b = compile_expr(
            cmpl_obj, b, context, cmpl_data, a_value_type, temp_links
        )
        assert sz_out_b == sizeof_a
        lnk.emit_stor(
            cmpl_obj.memory,
            sizeof_a,
            cmpl_obj,
            byte_copy_cmpl_intrinsic,
            volatile_access=is_volatile_storage_type(a_value_type),
            atomic_access=is_atomic_storage_type(a_value_type),
        )
    elif expr.type_id in ASSIGNMENT_OPS:
        sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
        assert sz == 8, "Expression should be a reference"
        sz1 += sz
        res_none = type_coerce is void_t
        if res_none:
            res_type = void_t
        # Bit-field assignment: intercept before result-dup and compound-load
        bfi = expr.a.bit_field_info
        if bfi is not None:
            if expr.type_id != BinaryExprSubType.ASSGN:
                raise NotImplementedError(
                    "Compound assignment to bit field not yet supported"
                )
            sz, res_type = _compile_bit_field_assign(
                cmpl_obj, expr, context, cmpl_data, temp_links, bfi, typ
            )
            return sz, res_type
        if not res_none:
            cmpl_obj.memory.extend([BC_LOAD, BCR_TOS | BCR_SZ_8])
            sz1 += 8
        if expr.type_id != BinaryExprSubType.ASSGN:
            cmpl_obj.memory.extend([BC_LOAD, BCR_TOS | BCR_SZ_8])
            emit_tracked_abs_s8_load(
                cmpl_obj,
                sz_type,
                is_volatile_storage_type(expr.a.t_anot, through_ref=True),
                atomic_access=is_atomic_storage_type(expr.a.t_anot, through_ref=True),
            )
            sz1 += sz_type
        try:
            if expr.type_id not in [
                BinaryExprSubType.ASSGN_LSHIFT,
                BinaryExprSubType.ASSGN_RSHIFT,
            ]:
                assert compare_no_cvr(
                    expr.b.t_anot, typ
                ), "expr.b.t_anot = %s, typ = %s, expr = %s" % (
                    get_user_str_from_type(expr.b.t_anot),
                    get_user_str_from_type(typ),
                    format_pretty(expr),
                )
            else:
                assert compare_no_cvr(
                    expr.b.t_anot,
                    PrimitiveType.from_type_code(PrimitiveTypeId.INT_C, 1),
                ), "expr.b.t_anot = %s, typ = %s, expr = %s" % (
                    get_user_str_from_type(expr.b.t_anot),
                    get_user_str_from_type(typ),
                    format_pretty(expr),
                )
        except Exception as exc:
            raise CompileExprException(
                {
                    "stage": "compiling",
                    "expr": expr,
                    "context": context,
                    "cmpl_obj": cmpl_obj,
                }
            ) from exc
        sz_type1 = sz_type
        if expr.type_id in [
            BinaryExprSubType.ASSGN_LSHIFT,
            BinaryExprSubType.ASSGN_RSHIFT,
        ]:
            sz_type1 = 1
            sz = compile_expr(
                cmpl_obj,
                expr.b,
                context,
                cmpl_data,
                PrimitiveType.from_type_code(PrimitiveTypeId.INT_C, 1),
                temp_links,
            )
        else:
            sz = compile_expr(cmpl_obj, expr.b, context, cmpl_data, typ, temp_links)
        if inc_by != 1 and inc_by_before:
            emit_load_i_const(cmpl_obj.memory, inc_by, is_sign, sz_cls)
            cmpl_obj.memory.extend([BC_MUL1 + 2 * sz_cls + int(is_sign)])
        sz1 += sz
        assert (
            sz_type1 == sz
        ), "sz_type1 = %u, sz = %u; expr.b.t_anot = %s, typ = %s, expr.b = %r" % (
            sz_type,
            sz,
            get_user_str_from_type(expr.b.t_anot),
            get_user_str_from_type(typ),
            expr.b,
        )
        if expr.type_id != BinaryExprSubType.ASSGN:
            if sz_type == 16 and not is_flt:
                op_code = _get_int128_subop(expr.type_id, is_sign)
                if op_code is None:
                    raise ValueError("Unsupported operator %s" % expr.type_id.name)
                cmpl_obj.memory.extend([BC_INT128, op_code])
            else:
                op_code_u, op_code_s, op_code_f = {
                    BinaryExprSubType.ASSGN_MOD: (BC_MOD1, BC_MOD1S, BC_FMOD_2),
                    BinaryExprSubType.ASSGN_DIV: (BC_DIV1, BC_DIV1S, BC_FDIV_2),
                    BinaryExprSubType.ASSGN_MUL: (BC_MUL1, BC_MUL1S, BC_FMUL_2),
                    BinaryExprSubType.ASSGN_MINUS: (BC_SUB1, BC_SUB1, BC_FSUB_2),
                    BinaryExprSubType.ASSGN_PLUS: (BC_ADD1, BC_ADD1, BC_FADD_2),
                    BinaryExprSubType.ASSGN_AND: (BC_AND1, BC_AND1, BC_NOP),
                    BinaryExprSubType.ASSGN_OR: (BC_OR1, BC_OR1, BC_NOP),
                    BinaryExprSubType.ASSGN_XOR: (BC_XOR1, BC_XOR1, BC_NOP),
                    BinaryExprSubType.ASSGN_RSHIFT: (BC_RSHIFT1, BC_RSHIFT1, BC_NOP),
                    BinaryExprSubType.ASSGN_LSHIFT: (BC_LSHIFT1, BC_LSHIFT1, BC_NOP),
                }[expr.type_id]
                op_code = BC_NOP
                if is_flt:
                    if op_code_f != BC_NOP:
                        op_code = op_code_f - 1 + sz_cls
                else:
                    op_code = op_code_s if is_sign else op_code_u
                    if op_code != BC_NOP:
                        op_code += sz_cls if op_code_s == op_code_u else (2 * sz_cls)
                if op_code == BC_NOP:
                    raise ValueError("Unsupported operator %s" % expr.type_id.name)
                cmpl_obj.memory.append(op_code)
            sz1 -= sz_type1
        cmpl_obj.memory.extend([BC_SWAP, (sz_cls << 3) | BCS_SZ8_A])
        emit_tracked_abs_s8_stor(
            cmpl_obj,
            sz_type,
            is_volatile_storage_type(expr.a.t_anot, through_ref=True),
            atomic_access=is_atomic_storage_type(expr.a.t_anot, through_ref=True),
        )
        sz1 -= sz_type + 8
        if res_none:
            sz = 0
        else:
            sz = 8
        assert sz1 == sz, "sz1 = %r" % sz1
    else:
        sz = compile_expr(cmpl_obj, expr.a, context, cmpl_data, None, temp_links)
        assert (
            sz == sz_type
        ), "Expected typ = %r, expr.a.t_anot = %r, expr.a = %r, got sz = %u" % (
            typ,
            expr.a.t_anot,
            expr.a,
            sz,
        )
        sz_type1 = sz_type
        if expr.type_id in [BinaryExprSubType.LSHIFT, BinaryExprSubType.RSHIFT]:
            sz_type1 = 1
        sz = compile_expr(cmpl_obj, expr.b, context, cmpl_data, None, temp_links)
        if inc_by != 1 and inc_by_before:
            emit_load_i_const(cmpl_obj.memory, inc_by, is_sign, sz_cls)
            cmpl_obj.memory.extend([BC_MUL1 + 2 * sz_cls + int(is_sign)])
        assert sz == sz_type1, "sz = %u, sz_type1 = %u" % (sz, sz_type1)
        sz = sz_type
        if sz_type == 16 and not is_flt:
            op_code = _get_int128_subop(expr.type_id, is_sign)
            if op_code is None:
                raise ValueError("Unsupported operator %s" % expr.type_id.name)
            cmpl_obj.memory.extend([BC_INT128, op_code])
        else:
            op_code_u, op_code_s, op_code_f = {
                BinaryExprSubType.MOD: (BC_MOD1, BC_MOD1S, BC_FMOD_2),
                BinaryExprSubType.DIV: (BC_DIV1, BC_DIV1S, BC_FDIV_2),
                BinaryExprSubType.MUL: (BC_MUL1, BC_MUL1S, BC_FMUL_2),
                BinaryExprSubType.MINUS: (BC_SUB1, BC_SUB1, BC_FSUB_2),
                BinaryExprSubType.PLUS: (BC_ADD1, BC_ADD1, BC_FADD_2),
                BinaryExprSubType.AND: (BC_AND1, BC_AND1, BC_NOP),
                BinaryExprSubType.OR: (BC_OR1, BC_OR1, BC_NOP),
                BinaryExprSubType.XOR: (BC_XOR1, BC_XOR1, BC_NOP),
                BinaryExprSubType.LT: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
                BinaryExprSubType.GT: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
                BinaryExprSubType.LE: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
                BinaryExprSubType.GE: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
                BinaryExprSubType.NE: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
                BinaryExprSubType.EQ: (BC_CMP1, BC_CMP1S, BC_FCMP_2),
                BinaryExprSubType.RSHIFT: (BC_RSHIFT1, BC_RSHIFT1, BC_NOP),
                BinaryExprSubType.LSHIFT: (BC_LSHIFT1, BC_LSHIFT1, BC_NOP),
            }[expr.type_id]
            op_code = BC_NOP
            if is_flt:
                if op_code_f != BC_NOP:
                    op_code = op_code_f - 1 + sz_cls
            else:
                op_code = op_code_s if is_sign else op_code_u
                if op_code != BC_NOP:
                    op_code += sz_cls if op_code_s == op_code_u else (2 * sz_cls)
            if op_code == BC_NOP:
                raise ValueError("Unsupported operator %s" % expr.type_id.name)
            cmpl_obj.memory.append(op_code)
        cmp_op_map = {
            BinaryExprSubType.LT: BC_LT0,
            BinaryExprSubType.GT: BC_GT0,
            BinaryExprSubType.LE: BC_LE0,
            BinaryExprSubType.GE: BC_GE0,
            BinaryExprSubType.NE: BC_NE0,
            BinaryExprSubType.EQ: BC_EQ0,
        }
        if expr.type_id in cmp_op_map:
            cmp_op_code = cmp_op_map[expr.type_id]
            cmpl_obj.memory.append(cmp_op_code)
            sz = 1
        elif inc_by != 1 and not inc_by_before:
            emit_load_i_const(cmpl_obj.memory, inc_by, is_sign, sz_cls)
            cmpl_obj.memory.extend([BC_DIV1 + 2 * sz_cls + int(is_sign)])
    return sz, res_type


from .BaseCmplObj import BaseCmplObj
from .BaseLink import BaseLink
from .CompileExprException import CompileExprException
from .LocalCompileData import LocalCompileData
from .byte_copy_cmpl_intrinsic import byte_copy_cmpl_intrinsic
from .compile_expr import compile_expr
from .memory_access import emit_tracked_abs_s8_load, emit_tracked_abs_s8_stor
from .tls import wrap_tls_link
from ..PrettyRepr import format_pretty
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..StackVM.PyStackVM import (
    BC128_ADD128S,
    BC128_ADD128U,
    BC128_AND128,
    BC128_CMP128S,
    BC128_CMP128U,
    BC128_DIV128S,
    BC128_DIV128U,
    BC128_LSHIFT128,
    BC128_MOD128S,
    BC128_MOD128U,
    BC128_MUL128S,
    BC128_MUL128U,
    BC128_OR128,
    BC128_RSHIFT128S,
    BC128_RSHIFT128U,
    BC128_SUB128S,
    BC128_SUB128U,
    BC128_XOR128,
    BCR_ABS_S8,
    BCR_SZ_8,
    BCR_TOS,
    BCS_SZ8_A,
    BC_ADD1,
    BC_AND1,
    BC_CMP1,
    BC_CMP1S,
    BC_DIV1,
    BC_DIV1S,
    BC_EQ0,
    BC_FADD_2,
    BC_FCMP_2,
    BC_FDIV_2,
    BC_FMOD_2,
    BC_FMUL_2,
    BC_FSUB_2,
    BC_GE0,
    BC_GT0,
    BC_INT128,
    BC_LE0,
    BC_LOAD,
    BC_LSHIFT1,
    BC_LT0,
    BC_MOD1,
    BC_MOD1S,
    BC_MUL1,
    BC_MUL1S,
    BC_NE0,
    BC_NOP,
    BC_OR1,
    BC_RSHIFT1,
    BC_STOR,
    BC_SUB1,
    BC_SWAP,
    BC_XOR1,
)
from ..parser.expr.BaseExpr import ExprType
from ..parser.expr.BinaryOpExpr import (
    ASSIGNMENT_OPS,
    CMP_OPS,
    BinaryExprSubType,
    BinaryOpExpr,
)
from ..parser.expr.NameRefExpr import NameRefExpr
from ..parser.expr.OperatorType import OperatorType
from ..parser.type.BaseType import BaseType
from ..parser.type.get_user_str_from_type import get_user_str_from_type
from ..parser.type.CompileContext import CompileContext
from ..parser.type.ContextVariable import ContextVariable
from ..parser.type.PrimitiveType import (
    PrimitiveType,
    PrimitiveTypeId,
    FLT_TYPE_CODES,
    void_t,
    prim_types,
)
from ..parser.type.QualType import QualType
from ..parser.type.qual_atomic_type_util import (
    compare_no_cvr,
    get_tgt_ref_type,
    is_atomic_storage_type,
    is_volatile_storage_type,
)
from ..parser.type.align_size_of import size_of
