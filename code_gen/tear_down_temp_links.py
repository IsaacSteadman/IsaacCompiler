from typing import List, Optional, Tuple


def tear_down_temp_links(
    cmpl_obj: "BaseCmplObj",
    temp_links: List[Tuple["BaseType", "BaseLink"]],
    expr: "BaseExpr",
    context: "CompileContext",
    cmpl_data: Optional["LocalCompileData"] = None,
):
    c = len(temp_links)
    sz_reset = 0
    while c > 0:
        c -= 1
        assert isinstance(c, int)
        typ, link = temp_links[c]
        typ.compile_var_de_init(cmpl_obj, context, VarRefLnkPrealloc(link), cmpl_data)
        sz_reset += size_of(typ)
    if sz_reset:
        sz_cls = emit_load_i_const(cmpl_obj.memory, sz_reset, False)
        cmpl_obj.memory.extend([BC_RST_SP1 + sz_cls])


from .BaseCmplObj import BaseCmplObj
from .BaseLink import BaseLink
from .LocalCompileData import LocalCompileData
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..StackVM.PyStackVM import BC_RST_SP1
from ..parser.context.CompileContext import CompileContext
from ..parser.expr.BaseExpr import BaseExpr
from ..parser.type.BaseType import BaseType
from ..parser.type.helpers.VarRef import VarRefLnkPrealloc
from ..parser.type.size_of import size_of
