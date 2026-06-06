import struct
from typing import List, Union, Optional


def _unwrap_static_init_expr(expr: "BaseExpr") -> "BaseExpr":
    from ..expr.ParenthExpr import ParenthExpr

    while True:
        if isinstance(expr, ParenthExpr) and len(expr.lst_expr) == 1:
            expr = expr.lst_expr[0]
            continue
        if isinstance(expr, CastOpExpr):
            expr = expr.expr
            continue
        return expr


def _write_symbol_relocation(
    storage_obj: "CompileObject", offset: int, symbol_name: str
) -> None:
    storage_obj.memory[offset : offset + 8] = b"\0" * 8
    storage_obj.get_link(symbol_name).lst_tgt.append(LinkRef(offset, None))


def _write_string_relocation(
    storage_obj: "CompileObject", offset: int, byts: bytes, alignment: int = 1
) -> None:
    storage_obj.memory[offset : offset + 8] = b"\0" * 8
    storage_obj.get_string_link(byts, alignment).lst_tgt.append(LinkRef(offset, None))


def _write_numeric_static_value(
    storage_obj: "CompileObject",
    offset: int,
    target_type: "BaseType",
    value,
) -> bool:
    value_type = get_value_type(target_type)
    if isinstance(value_type, EnumType):
        value_type = value_type.the_base_type
    if isinstance(value_type, QualType) and value_type.qual_id in {
        QualType.QUAL_PTR,
        QualType.QUAL_REF,
    }:
        intval = int(value) & ((1 << 64) - 1)
        storage_obj.memory[offset : offset + 8] = intval.to_bytes(
            8, "little", signed=False
        )
        return True
    if not isinstance(value_type, PrimitiveType):
        return False
    size = size_of(value_type)
    if value_type.typ in FLT_TYPE_CODES:
        if size == 4:
            storage_obj.memory[offset : offset + 4] = struct.pack("<f", float(value))
            return True
        if size == 8:
            storage_obj.memory[offset : offset + 8] = struct.pack("<d", float(value))
            return True
        return False
    if value_type.typ == PrimitiveTypeId.TYP_BOOL:
        intval = 1 if value else 0
        storage_obj.memory[offset : offset + 1] = intval.to_bytes(
            1, "little", signed=False
        )
        return True
    bits = size * 8
    intval = int(value)
    mask = (1 << bits) - 1
    intval &= mask
    if value_type.sign:
        sign_bit = 1 << (bits - 1)
        if intval & sign_bit:
            intval -= 1 << bits
    storage_obj.memory[offset : offset + size] = intval.to_bytes(
        size, "little", signed=value_type.sign
    )
    return True


def try_encode_static_initializer(
    storage_obj: "CompileObject",
    decl_type: "BaseType",
    expr: "BaseExpr",
    context: "CompileContext",
    base_offset: int = 0,
) -> bool:
    value_type = get_value_type(decl_type)
    if isinstance(value_type, EnumType):
        value_type = value_type.the_base_type
    if isinstance(value_type, PrimitiveType):
        value = eval_const_expr(expr)
        if value is None or isinstance(value, StaticAddress):
            return False
        return _write_numeric_static_value(storage_obj, base_offset, value_type, value)
    if isinstance(value_type, QualType):
        if value_type.qual_id in {
            QualType.QUAL_CONST,
            QualType.QUAL_DEF,
            QualType.QUAL_REG,
            QualType.QUAL_VOLATILE,
            QualType.QUAL_ATOMIC,
        }:
            return try_encode_static_initializer(
                storage_obj, value_type.tgt_type, expr, context, base_offset
            )
        if value_type.qual_id == QualType.QUAL_ARR:
            maybe_deduce_array_extent(value_type, [expr])
            if value_type.ext_inf is None:
                return False
            elem_type = value_type.tgt_type
            elem_size = size_of(elem_type)
            arr_len = value_type.ext_inf
            literal_expr = _unwrap_static_init_expr(expr)
            if (
                isinstance(literal_expr, LiteralExpr)
                and literal_expr.t_lit == LiteralExpr.LIT_STR
            ):
                elems = list(literal_expr.l_val) + [0]
                if len(elems) > arr_len:
                    return False
                for index, elem_val in enumerate(elems):
                    if not _write_numeric_static_value(
                        storage_obj,
                        base_offset + index * elem_size,
                        elem_type,
                        elem_val,
                    ):
                        return False
                return True
            if not isinstance(expr, CurlyExpr) or expr.lst_expr is None:
                return False
            next_index = 0
            for elem in expr.lst_expr:
                target_index = next_index
                subexpr = elem
                if isinstance(elem, DesigInitExpr):
                    if elem.kind != DesigInitExpr.KIND_INDEX:
                        return False
                    target_index = elem.designator
                    subexpr = elem.expr
                if target_index >= arr_len or subexpr is None:
                    return False
                if not try_encode_static_initializer(
                    storage_obj,
                    elem_type,
                    subexpr,
                    context,
                    base_offset + target_index * elem_size,
                ):
                    return False
                next_index = target_index + 1
            return True
        if value_type.qual_id in {QualType.QUAL_PTR, QualType.QUAL_REF}:
            literal_expr = _unwrap_static_init_expr(expr)
            if (
                isinstance(literal_expr, LiteralExpr)
                and literal_expr.t_lit == LiteralExpr.LIT_STR
            ):
                elem_type = get_value_type(literal_expr.t_anot).tgt_type
                assert isinstance(value_type.tgt_type, BaseType)
                if not compare_no_cvr(value_type.tgt_type, elem_type):
                    return False
                elem_size = size_of(elem_type)
                lit_bytes = bytearray((len(literal_expr.l_val) + 1) * elem_size)
                for index, elem_val in enumerate(literal_expr.l_val):
                    lit_bytes[index * elem_size : (index + 1) * elem_size] = int(
                        elem_val
                    ).to_bytes(elem_size, "little")
                _write_string_relocation(
                    storage_obj,
                    base_offset,
                    bytes(lit_bytes),
                    elem_size,
                )
                return True
            value = eval_const_expr(expr)
            if isinstance(value, StaticAddress):
                _write_symbol_relocation(storage_obj, base_offset, value.symbol_name)
                return True
            if value is None:
                return False
            return _write_numeric_static_value(
                storage_obj, base_offset, value_type, value
            )
        return False
    if isinstance(value_type, StructType):
        if not isinstance(expr, CurlyExpr) or expr.lst_expr is None:
            return False
        if value_type.the_base_type is not None:
            return False
        next_field_index = 0
        for elem in expr.lst_expr:
            target_index = next_field_index
            subexpr = elem
            if isinstance(elem, DesigInitExpr):
                if elem.kind != DesigInitExpr.KIND_FIELD:
                    return False
                try:
                    target_index = value_type.definition[elem.designator]
                except KeyError:
                    return False
                subexpr = elem.expr
            if target_index >= len(value_type.var_order) or subexpr is None:
                return False
            field_var = value_type.var_order[target_index]
            if is_flexible_array_type(field_var.typ):
                return False
            if field_var.bit_field_width is not None:
                return False
            if not try_encode_static_initializer(
                storage_obj,
                field_var.typ,
                subexpr,
                context,
                base_offset + value_type.offset_of(field_var.name),
            ):
                return False
            next_field_index = target_index + 1
        return True
    return False


def _ensure_static_storage_object(
    cmpl_obj: "BaseCmplObj", link_name: str, size: int, alignment: int = 1
) -> "CompileObject":
    compilation = get_compilation(cmpl_obj)
    storage_obj = compilation.ensure_compile_object(CompileObjectType.GLOBAL, link_name)
    registry_symbol = compilation.symbol_registry.get(link_name)
    if registry_symbol is not None:
        storage_obj.section_name = registry_symbol.section_name
    storage_obj.alignment = max(storage_obj.alignment, alignment)
    if len(storage_obj.memory) < size:
        storage_obj.memory.extend([0] * (size - len(storage_obj.memory)))
    return storage_obj


def _emit_guarded_static_local_initializer(
    decl_type: "BaseType",
    cmpl_obj: "BaseCmplObj",
    init_args: List[Union["BaseExpr", "CurlyStmnt"]],
    context: "CompileContext",
    cmpl_data: "LocalCompileData",
    link_name: str,
    temp_links,
) -> None:
    guard_name = link_name + "$init_guard"
    _ensure_static_storage_object(cmpl_obj, guard_name, 1)
    get_compilation(cmpl_obj).register_symbol(
        guard_name,
        guard_name,
        None,
        SymbolBinding.LOCAL,
        ObjectSegment.DATA,
        SymbolType.OBJECT,
        True,
        True,
        1,
        1,
    )
    guard_link = cmpl_obj.get_link(guard_name)
    skip_link = Linkage()
    guard_link.emit_load(cmpl_obj.memory, 1, cmpl_obj, byte_copy_cmpl_intrinsic)
    cmpl_obj.memory.extend([BC_NE0])
    emit_rel_jumpif(cmpl_obj.memory, skip_link)
    decl_type.compile_var_init(
        cmpl_obj,
        init_args,
        context,
        VarRefLnkPrealloc(cmpl_obj.get_link(link_name)),
        cmpl_data,
        temp_links,
    )
    emit_load_i_const(cmpl_obj.memory, 1, False, 0)
    guard_link.emit_stor(cmpl_obj.memory, 1, cmpl_obj, byte_copy_cmpl_intrinsic)
    skip_link.src = len(cmpl_obj.memory)
    skip_link.fill_all(cmpl_obj.memory)


def emit_global_runtime_initializer(
    decl_type: "BaseType",
    cmpl_obj: "BaseCmplObj",
    init_args: List[Union["BaseExpr", "CurlyStmnt"]],
    context: "CompileContext",
    link_name: str,
    temp_links,
) -> None:
    compilation = get_compilation(cmpl_obj)
    init_obj = compilation.ensure_compile_object(
        CompileObjectType.FUNCTION, INIT_GLOBALS_LINK_NAME
    )
    compilation.register_symbol(
        INIT_GLOBALS_LINK_NAME,
        "__init_globals",
        None,
        SymbolBinding.LOCAL,
        ObjectSegment.CODE,
        SymbolType.FUNCTION,
        True,
        True,
    )
    init_cmpl_data = LocalCompileData()
    decl_type.compile_var_init(
        init_obj,
        init_args,
        context,
        VarRefLnkPrealloc(init_obj.get_link(link_name)),
        init_cmpl_data,
        temp_links,
    )


def compile_static_storage_decl(
    decl_type: "BaseType",
    cmpl_obj: "BaseCmplObj",
    init_args: List[Union["BaseExpr", "CurlyStmnt"]],
    context: "CompileContext",
    ref: "VarRef",
    cmpl_data: Optional["LocalCompileData"] = None,
    temp_links=None,
) -> Optional[int]:
    if ref.ref_type != VAR_REF_TOS_NAMED:
        return None
    assert isinstance(ref, VarRefTosNamed)
    ctx_var = ref.ctx_var
    if ctx_var is None:
        return None
    assert isinstance(ctx_var, ContextVariable)
    if ctx_var.uses_stack_storage():
        return None
    maybe_deduce_array_extent(decl_type, init_args)
    if contains_variable_length_array_type(decl_type):
        raise TypeError("Variable-length arrays require automatic local storage")
    size = size_of(decl_type)
    register_context_symbol(
        cmpl_obj,
        ctx_var,
        decl_type,
        ctx_var.mods != VarDeclMods.EXTERN or bool(init_args),
        size,
        ctx_var.effective_alignment(),
    )
    if ctx_var.mods == VarDeclMods.EXTERN and not init_args:
        return 0
    link_name = ctx_var.get_link_name()
    storage_obj = _ensure_static_storage_object(
        cmpl_obj, link_name, size, ctx_var.effective_alignment()
    )
    if len(init_args) == 1 and not try_encode_static_initializer(
        storage_obj, decl_type, init_args[0], context
    ):
        if ctx_var.is_static_local():
            assert cmpl_data is not None
            _emit_guarded_static_local_initializer(
                decl_type,
                cmpl_obj,
                init_args,
                context,
                cmpl_data,
                link_name,
                temp_links,
            )
        else:
            emit_global_runtime_initializer(
                decl_type, cmpl_obj, init_args, context, link_name, temp_links
            )
    return 0 if ctx_var.is_static_local() else size


from .BaseType import BaseType
from .maybe_deduce_array_extent import maybe_deduce_array_extent
from .align_size_of import size_of
from ..expr.BaseExpr import BaseExpr
from ..stmnt.CurlyStmnt import CurlyStmnt
from ...code_gen.LocalCompileData import LocalCompileData
from ...code_gen.BaseCmplObj import BaseCmplObj
from .CompileContext import CompileContext
from .helpers.VarRef import (
    VAR_REF_TOS_NAMED,
    VarRef,
    VarRefTosNamed,
)
from .register_context_symbol import register_context_symbol
from .get_compilation import get_compilation
from .ContextVariable import ContextVariable
from .VarDeclMods import VarDeclMods
from ...code_gen.CompileObject import CompileObject
from ...code_gen.Compilation import CompileObjectType, INIT_GLOBALS_LINK_NAME
from ...code_gen.stackvm_binutils.object_file import (
    SymbolBinding,
    ObjectSegment,
    SymbolType,
)
from ...code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from .helpers.VarRef import VarRefLnkPrealloc
from ...code_gen.branch_emit import emit_rel_jumpif
from .QualType import QualType
from .is_fn_type import is_fn_type
from ..expr.CurlyExpr import CurlyExpr
from ..expr.DesigInitExpr import DesigInitExpr
from ..expr.LiteralExpr import LiteralExpr
from .StaticAddress import StaticAddress
from .PrimitiveType import PrimitiveType, PrimitiveTypeId, FLT_TYPE_CODES
from .EnumType import EnumType
from ...code_gen.Linkage import Linkage
from .qual_atomic_type_util import (
    get_value_type,
    compare_no_cvr,
    is_flexible_array_type,
)
from .vla import contains_variable_length_array_type
from .eval_const_expr import eval_const_expr
from ...StackVM.PyStackVM import BC_NE0
from ...code_gen.byte_copy_cmpl_intrinsic import byte_copy_cmpl_intrinsic
from .StructType import StructType
from ..expr.CastOpExpr import CastOpExpr
from ...code_gen.LinkRef import LinkRef
