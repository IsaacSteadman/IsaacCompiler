from typing import List, Optional, Tuple


def emit_runtime_sizeof(
    cmpl_obj: "BaseCmplObj",
    typ: "BaseType",
    context: "CompileContext",
    cmpl_data: "LocalCompileData",
    temp_links: Optional[List[Tuple["BaseType", "BaseLink"]]] = None,
) -> int:
    typ = strip_cv_qualifiers(typ)
    if isinstance(typ, QualType) and typ.qual_id == QualType.QUAL_ARR:
        if typ.ext_inf is None:
            raise TypeError("Cannot allocate an array with an unknown extent")
        if isinstance(typ.ext_inf, int):
            emit_load_i_const(cmpl_obj.memory, typ.ext_inf, False, 3)
        elif isinstance(typ.ext_inf, BaseExpr):
            from .compile_expr import compile_expr

            bound_type = get_value_type(typ.ext_inf.t_anot)
            sz = compile_expr(
                cmpl_obj, typ.ext_inf, context, cmpl_data, bound_type, temp_links
            )
            if sz != 8 or not compare_no_cvr(bound_type, size_l_t):
                cmpl_obj.memory.extend(
                    [BC_CONV, get_bc_conv_bits(bound_type) | (get_bc_conv_bits(size_l_t) << 4)]
                )
        else:
            raise TypeError("Unsupported array extent %r" % (typ.ext_inf,))
        emit_runtime_sizeof(cmpl_obj, typ.tgt_type, context, cmpl_data, temp_links)
        cmpl_obj.memory.extend([BC_MUL8])
        return 8
    static_size = size_of(typ)
    emit_load_i_const(cmpl_obj.memory, static_size, False, 3)
    return 8


from .BaseCmplObj import BaseCmplObj
from .BaseLink import BaseLink
from .LocalCompileData import LocalCompileData
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from .get_bc_conv_bits import get_bc_conv_bits
from ..StackVM.PyStackVM import BC_CONV, BC_MUL8
from ..parser.expr.BaseExpr import BaseExpr
from ..parser.type.BaseType import BaseType
from ..parser.type.CompileContext import CompileContext
from ..parser.type.PrimitiveType import size_l_t
from ..parser.type.QualType import QualType
from ..parser.type.align_size_of import size_of
from ..parser.type.qual_atomic_type_util import strip_cv_qualifiers
from ..parser.type.qual_atomic_type_util import compare_no_cvr, get_value_type
