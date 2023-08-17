from typing import List, Optional, Tuple


def get_vars_from_compile_data(
    cmpl_data: "LocalCompileData",
) -> List[Tuple["ContextVariable", "LocalRef"]]:
    if cmpl_data.parent is None:
        return cmpl_data.vars
    else:
        return get_vars_from_compile_data(cmpl_data.parent) + cmpl_data.vars


def compile_stmnt(
    cmpl_obj: "BaseCmplObj",
    stmnt: "BaseStmnt",
    context: "CompileContext",
    cmpl_data: Optional["LocalCompileData"] = None,
):
    if stmnt.stmnt_type == StmntType.ASM:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, AsmStmnt)
        if (
            stmnt.condition is None
            or stmnt.condition.get("arch", CURRENT_CMPL_CONDITIONS["arch"])
            == CURRENT_CMPL_CONDITIONS["arch"]
        ):
            rel_bp_names = {}
            for ctx_var, local_ref in get_vars_from_compile_data(cmpl_data):
                rel_bp_names[ctx_var.get_link_name()] = (
                    local_ref.rel_addr,
                    local_ref.sz,
                )
            if stmnt.condition is not None and stmnt.condition.get(
                "display_links", False
            ):
                print(
                    "Links for assembly named '%s' are as follows: %s"
                    % (
                        stmnt.condition.get("name", "<UNNAMED>"),
                        format_pretty(rel_bp_names),
                    )
                )
            assemble(cmpl_obj, rel_bp_names, "\n".join(stmnt.inner_asm))
    elif stmnt.stmnt_type == StmntType.CURLY_STMNT:
        assert isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, CurlyStmnt)
        return compile_curly(cmpl_obj, stmnt, context, cmpl_data)
    elif stmnt.stmnt_type == StmntType.DECL:
        assert isinstance(stmnt, DeclStmnt)
        assert stmnt.decl_lst is not None
        sz_off = 0
        for cur_decl in stmnt.decl_lst:
            assert isinstance(cur_decl, SingleVarDecl)
            ctx_var = context.scoped_get_strict(cur_decl.var_name)
            sz_off += cur_decl.type_name.compile_var_init(
                cmpl_obj,
                cur_decl.init_args,
                context,
                VarRefTosNamed(ctx_var),
                cmpl_data,
            )
        return sz_off
    elif stmnt.stmnt_type == StmntType.IF:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, IfElse)
        assert stmnt.stmnt is not None
        assert stmnt.cond.t_anot is not None, "type annotation required: " + repr(
            stmnt.cond
        )
        # assert stmnt.cond.t_anot is bool
        sz = compile_expr(
            cmpl_obj, stmnt.cond, context, cmpl_data, get_value_type(stmnt.cond.t_anot)
        )
        assert sz == 1, "Error:\n  cond = %r\n  cond.t_anot = %r" % (
            stmnt.cond,
            stmnt.cond.t_anot,
        )
        # assert sz == sizeof(bool)
        cmpl_obj.memory.extend(
            [BC_EQ0, BC_LOAD, BCR_EA_R_IP | BCR_SZ_8, 0, 0, 0, 0, 0, 0, 0, 0, BC_JMPIF]
        )
        lnk_ref = LinkRef(len(cmpl_obj.memory) - 9, 0)
        compile_stmnt(cmpl_obj, stmnt.stmnt, context, cmpl_data)
        if stmnt.else_stmnt is not None:
            # jump past the else-statement
            cmpl_obj.memory.extend(
                [
                    BC_LOAD,
                    BCR_EA_R_IP | BCR_SZ_8,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    BC_JMP,
                ]
            )
            lnk_ref.fill_ref(cmpl_obj.memory, len(cmpl_obj.memory))
            lnk_ref = LinkRef(len(cmpl_obj.memory) - 9, 0)
            compile_stmnt(cmpl_obj, stmnt.else_stmnt, context, cmpl_data)
        lnk_ref.fill_ref(cmpl_obj.memory, len(cmpl_obj.memory))
    elif stmnt.stmnt_type == StmntType.FOR:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, ForLoop)
        assert stmnt.init is not None
        assert stmnt.cond is not None
        assert stmnt.stmnt is not None
        cmpl_data1 = LocalCompileData(cmpl_data)
        lnk_begin_loop = Linkage()
        lnk_end_loop = Linkage()
        cmpl_data1.cur_breakable = (lnk_begin_loop, lnk_end_loop)
        sz0 = compile_stmnt(cmpl_obj, stmnt.init, stmnt.context, cmpl_data1)
        lnk_begin_loop.src = len(cmpl_obj.memory)
        lnk_end_body = Linkage()
        sz = compile_expr(cmpl_obj, stmnt.cond, stmnt.context, cmpl_data1)
        assert sz == 1
        cmpl_obj.memory.extend([BC_EQ0])
        lnk_end_loop.emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMPIF])
        compile_stmnt(cmpl_obj, stmnt.stmnt, stmnt.context, cmpl_data1)
        lnk_end_body.src = len(cmpl_obj.memory)
        if stmnt.incr is not None:
            sz = compile_expr(cmpl_obj, stmnt.incr, stmnt.context, cmpl_data1, void_t)
            assert sz == 0
        lnk_begin_loop.emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMP])
        lnk_end_loop.src = len(cmpl_obj.memory)
        sz_cls = emit_load_i_const(cmpl_obj.memory, sz0, False)
        cmpl_obj.memory.extend([BC_RST_SP1 + sz_cls])
        lnk_begin_loop.fill_all(cmpl_obj.memory)
        lnk_end_body.fill_all(cmpl_obj.memory)
        lnk_end_loop.fill_all(cmpl_obj.memory)
    elif stmnt.stmnt_type == StmntType.WHILE:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, WhileLoop)
        # assert stmnt.cond.t_anot is bool
        cmpl_data1 = LocalCompileData(cmpl_data)
        lnk_begin_loop = Linkage()
        lnk_end_loop = Linkage()
        cmpl_data1.cur_breakable = (lnk_begin_loop, lnk_end_loop)
        lnk_begin_loop.src = len(cmpl_obj.memory)
        sz = compile_expr(cmpl_obj, stmnt.cond, context, cmpl_data)
        assert sz == 1  # assert sz == sizeof(bool)
        cmpl_obj.memory.extend([BC_EQ0])
        lnk_end_loop.emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMPIF])
        compile_stmnt(cmpl_obj, stmnt.stmnt, context, cmpl_data1)
        lnk_begin_loop.emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMP])
        lnk_end_loop.src = len(cmpl_obj.memory)
        lnk_begin_loop.fill_all(cmpl_obj.memory)
        lnk_end_loop.fill_all(cmpl_obj.memory)
    elif stmnt.stmnt_type == StmntType.CONTINUE:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert cmpl_data.cur_breakable is not None
        cmpl_data.cur_breakable[0].emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMP])
    elif stmnt.stmnt_type == StmntType.BRK:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert cmpl_data.cur_breakable is not None
        cmpl_data.cur_breakable[1].emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_JMP])
    elif stmnt.stmnt_type == StmntType.RTN:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, ReturnStmnt)
        cmpl_data1 = cmpl_data
        # Leave all the scopes except for the scope that has no parent (ie the function argument scope)
        scopes_to_leave = []
        while cmpl_data1.parent is not None:
            scopes_to_leave.append(cmpl_data1)
            cmpl_data1 = cmpl_data1.parent
        assert cmpl_data1.res_data is not None
        res_type, res_link = cmpl_data1.res_data
        sz_res = size_of(
            res_type
        )  # TODO: right now return values are treated like variable values
        sz_res1 = res_type.compile_var_init(
            cmpl_obj, [stmnt.expr], context, VarRefLnkPrealloc(res_link), cmpl_data
        )
        assert (
            sz_res1 == sz_res
        ), "Size returned from CompileVarInit is inconsistent with SizeOf(res_type)"
        for Scope in scopes_to_leave:
            assert isinstance(Scope, LocalCompileData)
            Scope.compile_leave_scope(cmpl_obj, context)
        # TODO: change function calling convention
        # TODO:   convention: caller pushes args just like it does now
        # TODO:   except there is an additional argument that represents the return value
        # already sortof done
        cmpl_obj.memory.extend([BC_RET])
    elif stmnt.stmnt_type == StmntType.SEMI_COLON:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, SemiColonStmnt)
        if stmnt.expr is not None:
            sz = compile_expr(cmpl_obj, stmnt.expr, context, cmpl_data, void_t)
            assert sz == 0
    elif stmnt.stmnt_type == StmntType.NAMESPACE:
        assert isinstance(stmnt, NamespaceStmnt)
        for inner_stmnt in stmnt.lst_stmnts:
            compile_stmnt(cmpl_obj, inner_stmnt, stmnt.ns, cmpl_data)
    elif stmnt.stmnt_type == StmntType.TYPEDEF:
        pass  # Do nothing for typedef statement
    else:
        raise ValueError("Unrecognized Statement Type")
    return 0


from .BaseCmplObj import BaseCmplObj
from .CompileObject import CompileObject
from .LinkRef import LinkRef
from .Linkage import Linkage
from .LocalRef import LocalRef
from .compile_curly import compile_curly
from .compile_expr import compile_expr
from .constants import CURRENT_CMPL_CONDITIONS
from .stackvm_binutils import assemble
from ..PrettyRepr import format_pretty
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..StackVM.PyStackVM import (
    BCR_EA_R_IP,
    BCR_SZ_8,
    BC_EQ0,
    BC_JMP,
    BC_JMPIF,
    BC_LOAD,
    BC_RET,
    BC_RST_SP1,
)
from ..parser.context.CompileContext import CompileContext
from ..parser.context.ContextVariable import ContextVariable
from ..parser.stmnt.AsmStmnt import AsmStmnt
from ..parser.stmnt.BaseStmnt import BaseStmnt, StmntType
from ..parser.stmnt.CurlyStmnt import CurlyStmnt
from ..parser.stmnt.DeclStmnt import DeclStmnt
from ..parser.stmnt.ForLoop import ForLoop
from ..parser.stmnt.IfElse import IfElse
from ..parser.stmnt.NamespaceStmnt import NamespaceStmnt
from ..parser.stmnt.ReturnStmnt import ReturnStmnt
from ..parser.stmnt.SemiColonStmnt import SemiColonStmnt
from ..parser.stmnt.WhileLoop import WhileLoop
from ..parser.type.PrimitiveType import void_t
from ..parser.type.get_value_type import get_value_type
from ..parser.type.size_of import size_of
from ..parser.stmnt.helpers.SingleVarDecl import SingleVarDecl
from ..parser.type.helpers.VarRef import VarRefLnkPrealloc, VarRefTosNamed
from .LocalCompileData import LocalCompileData
