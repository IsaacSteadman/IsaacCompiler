from typing import List, Optional, Tuple
from ..parser.type.align_util import align_up


def setup_temp_links(
    cmpl_obj: "BaseCmplObj",
    expr: "BaseExpr",
    context: "CompileContext",
    cmpl_data: Optional["LocalCompileData"] = None,
) -> List[Tuple["BaseType", "BaseLink"]]:
    if context.Optimize != OPT_CODE_GEN:
        raise ValueError(
            "context must be in the optimal representation for Code Generation (Optimize = OPT_CODE_GEN)"
        )
    temp_links: List[Optional[Tuple[BaseType, BaseLink]]] = (
        [] if expr.temps is None else ([None] * len(expr.temps))
    )
    assert (
        expr.temps is not None or len(temp_links) == 0
    ), "len(temp_links) must be 0 if expr.temps is None"
    expr.temps_stack_size = 0
    bp_off_start = cmpl_data.bp_off
    bp_off = bp_off_start
    for c in range(len(temp_links)):
        sz_var = size_of(expr.temps[c])
        align = align_of(expr.temps[c])
        if align > 1:
            bp_off = align_up(bp_off + sz_var, align) - sz_var
        temp_links[c] = (
            expr.temps[c],
            LocalRef.from_bp_off_pre_inc(bp_off, sz_var),
        )
        bp_off += sz_var
    sz_add = bp_off - bp_off_start
    expr.temps_stack_size = sz_add
    if sz_add == 0:
        return temp_links
    sz_cls = emit_load_i_const(cmpl_obj.memory, sz_add, False)
    cmpl_obj.memory.extend([BC_ADD_SP1 + sz_cls])
    cmpl_data.bp_off = bp_off
    return temp_links


from .BaseCmplObj import BaseCmplObj
from .BaseLink import BaseLink
from .LocalCompileData import LocalCompileData
from .LocalRef import LocalRef
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..StackVM.PyStackVM import BC_ADD_SP1
from ..parser.expr.BaseExpr import BaseExpr
from ..parser.type.BaseType import BaseType
from ..parser.type.align_size_of import align_of, size_of
from ..parser.type.CompileContext import CompileContext, OPT_CODE_GEN
