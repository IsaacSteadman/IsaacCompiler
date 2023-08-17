from typing import List, Optional, Tuple


def setup_temp_links(
        cmpl_obj: "BaseCmplObj",
        expr: "BaseExpr",
        context: "CompileContext",
        cmpl_data: Optional["LocalCompileData"] = None
) -> List[Tuple["BaseType", "BaseLink"]]:
    if context.Optimize != OPT_CODE_GEN:
        raise ValueError("context must be in the optimal representation for Code Generation (Optimize = OPT_CODE_GEN)")
    temp_links: List[Optional[Tuple[BaseType, BaseLink]]] = [] if expr.temps is None else ([None] * len(expr.temps))
    assert expr.temps is not None or len(temp_links) == 0, "len(temp_links) must be 0 if expr.temps is None"
    sz_add = 0
    for c in range(len(temp_links)):
        sz_var = size_of(expr.temps[c])
        temp_links[c] = (expr.temps[c], LocalRef.from_bp_off_pre_inc(cmpl_data.bp_off, sz_var))
        sz_add += sz_var
    if sz_add == 0:
        return temp_links
    sz_cls = emit_load_i_const(cmpl_obj.memory, sz_add, False)
    cmpl_obj.memory.extend([
        BC_ADD_SP1 + sz_cls
    ])
    cmpl_data.bp_off += sz_add
    return temp_links


from .BaseCmplObj import BaseCmplObj
from .BaseLink import BaseLink
from .LocalCompileData import LocalCompileData
from .LocalRef import LocalRef
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..StackVM.PyStackVM import BC_ADD_SP1
from ..parser.context.CompileContext import CompileContext, OPT_CODE_GEN
from ..parser.expr.BaseExpr import BaseExpr
from ..parser.type.BaseType import BaseType
from ..parser.type.size_of import size_of