from typing import Optional


def compile_curly(
    cmpl_obj: "CompileObject",
    stmnt: "CurlyStmnt",
    context: "CompileContext",
    cmpl_data: Optional["LocalCompileData"] = None,
):
    # key format is "name@fullscopename"
    #   fullscopename format is cur.name.rsplit(" ", 1)[-1][:-1] + ("-" + cur.parent.fullscopename)
    #     if cur.parent is not cur.host_scopeable else ""
    assert stmnt.stmnts is not None
    if cmpl_data is None:
        print("WARN: Curly Statement usually requires cmpl_data")
    cmpl_data = LocalCompileData(cmpl_data)
    terminated = False
    for cur_stmnt in stmnt.stmnts:
        if terminated:
            if cur_stmnt.stmnt_type != StmntType.LABEL:
                continue
            terminated = False
        terminated = compile_stmnt(cmpl_obj, cur_stmnt, stmnt.context, cmpl_data)
    implicit_cmpl_obj = (
        cmpl_obj if isinstance(cmpl_obj, Compilation) else cmpl_obj.parent
    )
    for ctx_var in stmnt.implicit_ctx_vars:
        link = cmpl_obj.linkages.get(ctx_var.get_link_name())
        if link is None or not link.lst_tgt:
            continue
        ctx_var.typ.compile_var_init(
            implicit_cmpl_obj,
            [] if ctx_var.init_expr is None else [ctx_var.init_expr],
            stmnt.context,
            VarRefTosNamed(ctx_var),
            cmpl_data,
        )
    if not terminated:
        cmpl_data.compile_leave_scope(cmpl_obj, stmnt.context)
    return terminated


from .CompileObject import CompileObject
from .Compilation import Compilation
from .LocalCompileData import LocalCompileData
from .compile_stmnt import compile_stmnt
from ..parser.type.helpers.VarRef import VarRefTosNamed
from ..parser.stmnt.BaseStmnt import StmntType
from ..parser.stmnt.CurlyStmnt import CurlyStmnt
from ..parser.type.CompileContext import CompileContext
