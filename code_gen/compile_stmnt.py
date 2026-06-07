import re
from typing import Dict, List, Optional, Tuple

_ASM_GOTO_LABEL_RE = re.compile(r"%l(?:\[([A-Za-z_$][A-Za-z0-9_$]*)\]|([0-9]+))")


def _prepare_asm_goto(
    stmnt: "AsmStmnt", cmpl_data: "LocalCompileData", asm_text: str
) -> Tuple[str, Dict[str, "Linkage"]]:
    labels_by_name = {
        name: cmpl_data.reference_label(name) for name in stmnt.goto_labels
    }
    external_code_links = {}
    for match in _ASM_GOTO_LABEL_RE.finditer(asm_text):
        named_label, operand_number = match.groups()
        if named_label is not None:
            if named_label not in labels_by_name:
                raise ValueError(
                    "asm goto template references label '%s' not present in its label list"
                    % named_label
                )
            link = labels_by_name[named_label]
        else:
            label_index = int(operand_number) - stmnt.goto_label_operand_base
            if label_index < 0 or label_index >= len(stmnt.goto_labels):
                raise ValueError(
                    "asm goto label operand %s is outside its label list"
                    % match.group(0)
                )
            link = labels_by_name[stmnt.goto_labels[label_index]]
        external_code_links[match.group(0)] = link

    # A bare label operand is useful StackVM shorthand for loading its address.
    # The explicit native form, lRa*:%l[label], is left unchanged.
    lines = []
    for line in asm_text.split("\n"):
        stripped = line.strip()
        if stripped in external_code_links:
            line = "lRa*:" + stripped
        else:
            load_match = re.fullmatch(r"LOAD\s+(%l(?:\[[^\]]+\]|[0-9]+))", stripped)
            if load_match is not None and load_match.group(1) in external_code_links:
                line = "lRa*:" + load_match.group(1)
        lines.append(line)
    return "\n".join(lines), external_code_links


def get_vars_from_compile_data(
    cmpl_data: "LocalCompileData",
) -> List[Tuple["ContextVariable", "LocalRef"]]:
    if cmpl_data.parent is None:
        return cmpl_data.vars
    else:
        return get_vars_from_compile_data(cmpl_data.parent) + cmpl_data.vars


def _leave_scopes_until(
    cmpl_obj: "BaseCmplObj",
    cmpl_data: "LocalCompileData",
    target: Optional["LocalCompileData"],
    context: "CompileContext",
) -> None:
    cur = cmpl_data
    while cur is not target:
        if cur is None:
            raise ValueError("Control-flow cleanup target is not an ancestor scope")
        cur.compile_leave_scope(cmpl_obj, context)
        cur = cur.parent


def _record_statement_debug_line(
    cmpl_obj: "BaseCmplObj",
    stmnt: "BaseStmnt",
    start_offset: int,
) -> None:
    if not isinstance(cmpl_obj, CompileObject):
        return
    parent = getattr(cmpl_obj, "parent", None)
    if parent is None or not getattr(parent, "keep_local_syms", False):
        return
    if stmnt.stmnt_type not in _DEBUG_STMNT_TYPES:
        return
    if len(cmpl_obj.memory) <= start_offset:
        return
    line, column = getattr(stmnt, "position", (-1, -1))
    source_file = getattr(cmpl_obj, "debug_source_file", None)
    if source_file is None:
        source_file = getattr(parent, "source_path", None)
    cmpl_obj.add_debug_line(start_offset, source_file, line, column)


def compile_stmnt(
    cmpl_obj: "BaseCmplObj",
    stmnt: "BaseStmnt",
    context: "CompileContext",
    cmpl_data: Optional["LocalCompileData"] = None,
):
    debug_start_offset = (
        len(cmpl_obj.memory) if isinstance(cmpl_obj, CompileObject) else None
    )
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
            asm_text = "\n".join(stmnt.inner_asm)
            external_code_links = None
            if stmnt.is_goto:
                asm_text, external_code_links = _prepare_asm_goto(
                    stmnt, cmpl_data, asm_text
                )
            assemble(cmpl_obj, rel_bp_names, asm_text, external_code_links)
    elif stmnt.stmnt_type == StmntType.CURLY_STMNT:
        assert isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, CurlyStmnt)
        result = compile_curly(cmpl_obj, stmnt, context, cmpl_data)
        _record_statement_debug_line(cmpl_obj, stmnt, debug_start_offset)
        return result
    elif stmnt.stmnt_type == StmntType.DECL:
        assert isinstance(stmnt, DeclStmnt)
        assert stmnt.decl_lst is not None
        sz_off = 0
        for cur_decl in stmnt.decl_lst:
            assert isinstance(cur_decl, SingleVarDecl)
            ctx_var = context.scoped_get_strict(cur_decl.var_name)
            if ctx_var.alias_name is not None and ctx_var.uses_stack_storage():
                raise TypeError("alias attribute requires static storage")
            sz_off += cur_decl.type_name.compile_var_init(
                cmpl_obj,
                cur_decl.init_args,
                context,
                VarRefTosNamed(ctx_var),
                cmpl_data,
            )
        _record_statement_debug_line(cmpl_obj, stmnt, debug_start_offset)
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
        cmpl_obj.memory.append(BC_EQ0)
        lnk_after_if = Linkage()
        emit_rel_jumpif(cmpl_obj.memory, lnk_after_if)
        compile_stmnt(cmpl_obj, stmnt.stmnt, context, cmpl_data)
        if stmnt.else_stmnt is not None:
            # jump past the else-statement
            lnk_after_else = Linkage()
            emit_rel_jump(cmpl_obj.memory, lnk_after_else)
            lnk_after_if.src = len(cmpl_obj.memory)
            lnk_after_if.fill_all(cmpl_obj.memory)
            compile_stmnt(cmpl_obj, stmnt.else_stmnt, context, cmpl_data)
            lnk_after_else.src = len(cmpl_obj.memory)
            lnk_after_else.fill_all(cmpl_obj.memory)
        else:
            lnk_after_if.src = len(cmpl_obj.memory)
            lnk_after_if.fill_all(cmpl_obj.memory)
    elif stmnt.stmnt_type == StmntType.FOR:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, ForLoop)
        assert stmnt.init is not None
        assert stmnt.cond is not None
        assert stmnt.stmnt is not None
        cmpl_data1 = LocalCompileData(cmpl_data)
        lnk_begin_loop = Linkage()
        lnk_end_loop = Linkage()
        lnk_continue = Linkage()
        cmpl_data1.cur_breakable = BreakableScope(
            lnk_continue, lnk_end_loop, cmpl_data1, cmpl_data1
        )
        compile_stmnt(cmpl_obj, stmnt.init, stmnt.context, cmpl_data1)
        lnk_begin_loop.src = len(cmpl_obj.memory)
        lnk_end_body = Linkage()
        sz = compile_expr(cmpl_obj, stmnt.cond, stmnt.context, cmpl_data1)
        assert sz == 1
        cmpl_obj.memory.extend([BC_EQ0])
        emit_rel_jumpif(cmpl_obj.memory, lnk_end_loop)
        compile_stmnt(cmpl_obj, stmnt.stmnt, stmnt.context, cmpl_data1)
        lnk_end_body.src = len(cmpl_obj.memory)
        lnk_continue.src = len(cmpl_obj.memory)
        if stmnt.incr is not None:
            sz = compile_expr(cmpl_obj, stmnt.incr, stmnt.context, cmpl_data1, void_t)
            assert sz == 0
        emit_rel_jump(cmpl_obj.memory, lnk_begin_loop)
        lnk_end_loop.src = len(cmpl_obj.memory)
        cmpl_data1.compile_leave_scope(cmpl_obj, stmnt.context)
        lnk_begin_loop.fill_all(cmpl_obj.memory)
        lnk_end_body.fill_all(cmpl_obj.memory)
        lnk_continue.fill_all(cmpl_obj.memory)
        lnk_end_loop.fill_all(cmpl_obj.memory)
    elif stmnt.stmnt_type == StmntType.WHILE:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, WhileLoop)
        # assert stmnt.cond.t_anot is bool
        cmpl_data1 = LocalCompileData(cmpl_data)
        lnk_begin_loop = Linkage()
        lnk_end_loop = Linkage()
        cmpl_data1.cur_breakable = BreakableScope(
            lnk_begin_loop, lnk_end_loop, cmpl_data1, cmpl_data1
        )
        lnk_begin_loop.src = len(cmpl_obj.memory)
        sz = compile_expr(cmpl_obj, stmnt.cond, context, cmpl_data)
        assert sz == 1  # assert sz == sizeof(bool)
        cmpl_obj.memory.extend([BC_EQ0])
        emit_rel_jumpif(cmpl_obj.memory, lnk_end_loop)
        compile_stmnt(cmpl_obj, stmnt.stmnt, context, cmpl_data1)
        emit_rel_jump(cmpl_obj.memory, lnk_begin_loop)
        lnk_end_loop.src = len(cmpl_obj.memory)
        cmpl_data1.compile_leave_scope(cmpl_obj, context)
        lnk_begin_loop.fill_all(cmpl_obj.memory)
        lnk_end_loop.fill_all(cmpl_obj.memory)
    elif stmnt.stmnt_type == StmntType.CONTINUE:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert cmpl_data.cur_breakable is not None
        breakable = cmpl_data.cur_breakable
        if breakable.continue_link is None:
            raise SyntaxError("continue statement is not inside a loop")
        _leave_scopes_until(
            cmpl_obj, cmpl_data, breakable.continue_cleanup_target, context
        )
        emit_rel_jump(cmpl_obj.memory, breakable.continue_link)
    elif stmnt.stmnt_type == StmntType.BRK:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert cmpl_data.cur_breakable is not None
        breakable = cmpl_data.cur_breakable
        _leave_scopes_until(cmpl_obj, cmpl_data, breakable.break_cleanup_target, context)
        emit_rel_jump(cmpl_obj.memory, breakable.break_link)
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
    elif stmnt.stmnt_type == StmntType.STATIC_ASSERT:
        pass  # Evaluated at parse time; no code to emit
    elif stmnt.stmnt_type == StmntType.SWITCH:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, SwitchStmnt)
        assert stmnt.expr is not None
        assert stmnt.expr.t_anot is not None, "switch expression must be type-annotated"

        # --- Step 1: evaluate the switch expression once ---
        sz = size_of(get_value_type(stmnt.expr.t_anot))
        assert sz in (1, 2, 4, 8), "switch expression must be an integer scalar"
        sz_cls = sz.bit_length() - 1  # 0→1B, 1→2B, 2→4B, 3→8B
        compile_expr(
            cmpl_obj,
            stmnt.expr,
            context,
            cmpl_data,
            get_value_type(stmnt.expr.t_anot),
        )
        # sz bytes of the switch expression now sit at TOS.

        # --- Step 2: build a child LocalCompileData with break → switch end ---
        cmpl_data1 = LocalCompileData(cmpl_data)
        lnk_end_switch = Linkage()
        old_breakable = cmpl_data.cur_breakable
        # Keep the enclosing continue target; replace break target with ours.
        cmpl_data1.cur_breakable = BreakableScope(
            old_breakable.continue_link if old_breakable is not None else None,
            lnk_end_switch,
            (
                old_breakable.continue_cleanup_target
                if old_breakable is not None
                else None
            ),
            cmpl_data1,
        )

        # One Linkage per segment (points to the start of that segment's body).
        seg_linkages = [Linkage() for _ in stmnt.segments]
        default_lnk = None  # will point at the default segment's Linkage, if any

        # CMP opcode appropriate for the expression size.
        cmp_opcode = (
            None if sz_cls == 4 else (BC_CMP1, BC_CMP2, BC_CMP4, BC_CMP8)[sz_cls]
        )

        # --- Step 3: emit the compare chain ---
        for seg_idx, (seg_labels, _) in enumerate(stmnt.segments):
            for label_val in seg_labels:
                if label_val is None:
                    # default label — record the target; no compare needed here.
                    default_lnk = seg_linkages[seg_idx]
                else:
                    # Duplicate TOS (the switch expression value) without consuming it.
                    cmpl_obj.memory.extend([BC_LOAD, BCR_TOS | (sz_cls << 5)])
                    # Load the case constant at the same size.
                    emit_load_i_const(cmpl_obj.memory, label_val, label_val < 0, sz_cls)
                    # Compare: pushes sign(switch_val - case_val) as 1 signed byte.
                    # Result is 0 iff switch_val == case_val.
                    if sz_cls == 4:
                        cmpl_obj.memory.extend([BC_INT128, BC128_CMP128U, BC_EQ0])
                    else:
                        cmpl_obj.memory.extend([cmp_opcode, BC_EQ0])
                    # Jump to this segment's body if equal (condition == 1).
                    emit_rel_jumpif(cmpl_obj.memory, seg_linkages[seg_idx])

        # After all comparisons: jump to default (or skip the whole switch).
        if default_lnk is not None:
            emit_rel_jump(cmpl_obj.memory, default_lnk)
        else:
            emit_rel_jump(cmpl_obj.memory, lnk_end_switch)

        # --- Step 4: emit segment bodies in order (fall-through is automatic) ---
        for seg_idx, (_, seg_stmnts) in enumerate(stmnt.segments):
            seg_linkages[seg_idx].src = len(cmpl_obj.memory)
            for seg_stmnt in seg_stmnts:
                compile_stmnt(cmpl_obj, seg_stmnt, stmnt.context, cmpl_data1)

        # --- Step 5: end-of-switch — pop the switch expression off the stack ---
        lnk_end_switch.src = len(cmpl_obj.memory)
        sz_cls2 = emit_load_i_const(cmpl_obj.memory, sz, False)
        cmpl_obj.memory.extend([BC_RST_SP1 + sz_cls2])

        # Back-fill all forward references.
        for lnk in seg_linkages:
            lnk.fill_all(cmpl_obj.memory)
        lnk_end_switch.fill_all(cmpl_obj.memory)

    elif stmnt.stmnt_type == StmntType.GOTO:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, GotoStmnt)
        if stmnt.indirect_expr is not None:
            assert stmnt.indirect_expr.t_anot is not None
            _target_pt, _target_vt, is_target_ref = get_tgt_ref_type(
                stmnt.indirect_expr.t_anot
            )
            sz = compile_expr(
                cmpl_obj,
                stmnt.indirect_expr,
                context,
                cmpl_data,
                None,
            )
            assert sz == 8
            if is_target_ref:
                emit_tracked_abs_s8_load(
                    cmpl_obj,
                    8,
                    is_volatile_storage_type(
                        stmnt.indirect_expr.t_anot, through_ref=True
                    ),
                    atomic_access=is_atomic_storage_type(
                        stmnt.indirect_expr.t_anot, through_ref=True
                    ),
                )
            cmpl_obj.memory.append(BC_JMP)
        else:
            emit_rel_jump(cmpl_obj.memory, cmpl_data.reference_label(stmnt.label_name))
    elif stmnt.stmnt_type == StmntType.LABEL:
        assert cmpl_data is not None and isinstance(cmpl_obj, CompileObject)
        assert isinstance(stmnt, LabelStmnt)
        lnk = cmpl_data.get_label(stmnt.label_name)
        if lnk.src is not None:
            raise ValueError("Duplicate label '%s'" % stmnt.label_name)
        lnk.src = len(cmpl_obj.memory)
    else:
        raise ValueError("Unrecognized Statement Type")
    _record_statement_debug_line(cmpl_obj, stmnt, debug_start_offset)
    return 0


from .BaseCmplObj import BaseCmplObj
from .CompileObject import CompileObject
from .Linkage import Linkage
from .LocalCompileData import BreakableScope, LocalCompileData
from .LocalRef import LocalRef
from .compile_curly import compile_curly
from .compile_expr import compile_expr
from .constants import CURRENT_CMPL_CONDITIONS
from .branch_emit import emit_rel_jump, emit_rel_jumpif
from .memory_access import emit_tracked_abs_s8_load
from .stackvm_binutils.assemble import assemble
from ..PrettyRepr import format_pretty
from .stackvm_binutils.emit_load_i_const import emit_load_i_const
from ..StackVM.PyStackVM import (
    BC128_CMP128U,
    BCR_TOS,
    BC_CMP1,
    BC_CMP2,
    BC_CMP4,
    BC_CMP8,
    BC_EQ0,
    BC_INT128,
    BC_JMP,
    BC_LOAD,
    BC_RET,
    BC_RST_SP1,
)
from ..parser.stmnt.AsmStmnt import AsmStmnt
from ..parser.stmnt.BaseStmnt import BaseStmnt, StmntType
from ..parser.stmnt.CurlyStmnt import CurlyStmnt
from ..parser.stmnt.ForLoop import ForLoop
from ..parser.stmnt.GotoStmnt import GotoStmnt
from ..parser.stmnt.IfElse import IfElse
from ..parser.stmnt.LabelStmnt import LabelStmnt
from ..parser.stmnt.NamespaceStmnt import NamespaceStmnt
from ..parser.stmnt.ReturnStmnt import ReturnStmnt
from ..parser.stmnt.SemiColonStmnt import SemiColonStmnt
from ..parser.stmnt.StaticAssertStmnt import StaticAssertStmnt
from ..parser.stmnt.SwitchStmnt import SwitchStmnt
from ..parser.stmnt.WhileLoop import WhileLoop
from ..parser.type.BaseType import BaseType
from ..parser.type.ContextVariable import ContextVariable
from ..parser.stmnt.DeclStmnt import DeclStmnt
from ..parser.type.CompileContext import CompileContext
from ..parser.type.qual_atomic_type_util import (
    get_tgt_ref_type,
    get_value_type,
    is_atomic_storage_type,
    is_volatile_storage_type,
)
from ..parser.type.align_size_of import size_of
from ..parser.type.PrimitiveType import void_t
from ..parser.stmnt.helpers.SingleVarDecl import SingleVarDecl
from ..parser.type.helpers.VarRef import VarRefLnkPrealloc, VarRefTosNamed

_DEBUG_STMNT_TYPES = {
    StmntType.ASM,
    StmntType.IF,
    StmntType.WHILE,
    StmntType.FOR,
    StmntType.RTN,
    StmntType.BRK,
    StmntType.CONTINUE,
    StmntType.DECL,
    StmntType.SEMI_COLON,
    StmntType.GOTO,
    StmntType.SWITCH,
}
