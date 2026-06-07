import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.Preprocessing import preprocess
from IsaacCompiler.StackVM.PyStackVM import BC_CALL, BC_HLT, BC_RET, VM
from IsaacCompiler.StackVM.runner import add_cmd_argv_vm
from IsaacCompiler.code_gen.Compilation import Compilation, INIT_GLOBALS_LINK_NAME
from IsaacCompiler.code_gen.LinkerOptions import LNK_RUN_STANDALONE, LinkerOptions
from IsaacCompiler.code_gen.compile_stmnt import compile_stmnt
from IsaacCompiler.code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from IsaacCompiler.lexer.lexer import get_list_tokens
from IsaacCompiler.lib.runtime_support import runtime_extern_deps
from IsaacCompiler.parser.stmnt.get_stmnt import get_stmnt
from IsaacCompiler.parser.type.CompileContext import CompileContext
from IsaacCompiler.parser.type.PrimitiveType import PrimitiveType
from IsaacCompiler.parser.type.QualType import QualType
from IsaacCompiler.parser.type.TypeDefCtxMember import TypeDefCtxMember


def _flatify_dep_desc(dep_dct, start_key):
    result = set()
    pending = {start_key}
    while pending:
        current = pending
        result |= current
        pending = set()
        for key in current:
            pending.update(dep_dct.get(key, ()))
        pending -= result
    return result


def _new_global_ctx():
    global_ctx = CompileContext("", None, None)
    va_base = PrimitiveType.from_str_name(["unsigned", "char"])
    va_type = QualType(QualType.QUAL_PTR, va_base)
    global_ctx.new_type("va_list", TypeDefCtxMember("va_list", global_ctx, va_type))
    return global_ctx


def _compile_to_objects(source):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = _new_global_ctx()
    cmpl_obj = Compilation(True)

    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)

    return global_ctx, cmpl_obj


def _compile_source(source, remove_unused_deps=True):
    global_ctx, cmpl_obj = _compile_to_objects(source)
    link_opts = LinkerOptions(
        remove_unused_deps,
        4096,
        runtime_extern_deps,
        LNK_RUN_STANDALONE,
        None,
    )

    init_obj = cmpl_obj.objects.get(INIT_GLOBALS_LINK_NAME)
    if init_obj is not None:
        init_obj.memory.append(BC_RET)
        cmpl_obj.get_link(INIT_GLOBALS_LINK_NAME).emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_CALL])

    main_fn = cmpl_obj.get_link(global_ctx.vars["main"].get_link_name())
    emit_load_i_const(cmpl_obj.memory, 1, True, 2)
    main_fn.emit_lea(cmpl_obj.memory)
    cmpl_obj.memory.extend([BC_CALL, BC_HLT])

    dep_tree = [("", sorted(cmpl_obj.linkages))]
    for key, obj in cmpl_obj.objects.items():
        dep_tree.append((key, sorted(obj.linkages)))
    if link_opts.extern_deps is not None:
        for key, obj in link_opts.extern_deps.items():
            dep_tree.append((key, sorted(obj.linkages)))
    dep_dct = dict(dep_tree)
    used_deps = _flatify_dep_desc(dep_dct, "")
    defined_deps = {key for key, _deps in dep_tree if key}
    unused_deps = defined_deps - used_deps
    excl = unused_deps if link_opts.remove_unused_deps else None

    cmpl_obj.merge_all(link_opts, link_opts.extern_deps, excl)
    assert cmpl_obj.link_all()
    return global_ctx, cmpl_obj


def _run_program(cmpl_obj):
    vm = VM(131072)
    vm.load_program(cmpl_obj.memory, 0)
    vm.push(4, 0)
    add_cmd_argv_vm(vm, len(cmpl_obj.memory), ["prog"])
    vm.execute()
    return vm


def _get_global_addr(global_ctx, cmpl_obj, name):
    ctx_var = global_ctx.vars[name]
    return cmpl_obj.get_link(ctx_var.get_link_name()).src


def _read_mem(memory, global_ctx, cmpl_obj, name, size=4, signed=True):
    addr = _get_global_addr(global_ctx, cmpl_obj, name)
    return int.from_bytes(memory[addr : addr + size], "little", signed=signed)


class B1ConstBranchTests(unittest.TestCase):
    def test_constant_folder_feeds_static_contexts(self):
        global_ctx, cmpl_obj = _compile_source(
            "int folded_arr[__builtin_constant_p(40 + 2) ? 3 : -1]; "
            "int result = 0; "
            "_Static_assert(__builtin_constant_p(1 ? 2 : missing_name), "
            '    "constant_p should short-circuit ternary"); '
            "_Static_assert(__builtin_choose_expr(1, 1, missing_name), "
            '    "choose_expr should evaluate selected arm"); '
            "int main(int argc, char **argv) { "
            "    switch (3) { "
            "        case __builtin_constant_p(4 + 5): result = 11; break; "
            "        case __builtin_choose_expr(1, 3, missing_name): "
            "            result = 23; break; "
            "    } "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "result"), 23)
        self.assertEqual(global_ctx.vars["folded_arr"].typ.ext_inf, 3)

    def test_const_false_branches_do_not_link_or_diagnose_dead_references(self):
        global_ctx, cmpl_obj = _compile_source(
            "int unresolved(void) { return 100; } "
            'void forbidden(void) __attribute__((error("forbidden call"))); '
            "void forbidden(void) {} "
            "int result = 0; "
            "int main(int argc, char **argv) { "
            "    if (0) { result = unresolved(); forbidden(); } "
            "    if (__builtin_constant_p(result)) { forbidden(); } "
            "    else { result += 3; } "
            "    if (__builtin_constant_p(1 + 2) && 0) { forbidden(); } "
            "    if (__builtin_choose_expr(1, 0, missing_name)) { forbidden(); } "
            "    else { result += 4; } "
            "    while (0) { result = unresolved(); forbidden(); } "
            "    for (result = result; 0; ) { result = unresolved(); forbidden(); } "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "result"), 7)

    def test_dead_unresolved_extern_calls_have_no_link_targets(self):
        _global_ctx, cmpl_obj = _compile_to_objects(
            "extern int unresolved(void); "
            "int main(int argc, char **argv) { "
            "    if (0) { return unresolved(); } "
            "    __builtin_unreachable(); "
            "    return unresolved(); "
            "}\n"
        )

        unresolved_link = cmpl_obj.linkages["unresolved"]
        self.assertEqual(unresolved_link.lst_tgt, [])
        self.assertNotIn("unresolved", cmpl_obj.objects["main"].linkages)

    def test_builtin_unreachable_prunes_following_statements(self):
        global_ctx, cmpl_obj = _compile_source(
            "int unresolved(void) { return 100; } "
            'void forbidden(void) __attribute__((error("after unreachable"))); '
            "void forbidden(void) {} "
            "int result = 0; "
            "int main(int argc, char **argv) { "
            "    result = 5; "
            "    __builtin_unreachable(); "
            "    result = unresolved(); "
            "    forbidden(); "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "result"), 5)


if __name__ == "__main__":
    unittest.main()
