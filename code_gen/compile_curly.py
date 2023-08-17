from typing import Optional


def compile_curly(
        cmpl_obj: "CompileObject",
        stmnt: "CurlyStmnt",
        context: "CompileContext",
        cmpl_data: Optional["LocalCompileData"] = None
):
    # key format is "name@fullscopename"
    #   fullscopename format is cur.name.rsplit(" ", 1)[-1][:-1] + ("-" + cur.parent.fullscopename)
    #     if cur.parent is not cur.host_scopeable else ""
    assert stmnt.stmnts is not None
    if cmpl_data is None:
        print("WARN: Curly Statement usually requires cmpl_data")
    cmpl_data = LocalCompileData(cmpl_data)
    for cur_stmnt in stmnt.stmnts:
        compile_stmnt(cmpl_obj, cur_stmnt, stmnt.context, cmpl_data)
    cmpl_data.compile_leave_scope(cmpl_obj, stmnt.context)
    return 0


from .CompileObject import CompileObject
from .LocalCompileData import LocalCompileData
from .compile_stmnt import compile_stmnt
from ..parser.context.CompileContext import CompileContext
from ..parser.stmnt.CurlyStmnt import CurlyStmnt
