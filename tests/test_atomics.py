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
from IsaacCompiler.code_gen.CompilerOptions import CompilerOptions
from IsaacCompiler.code_gen.LinkerOptions import LNK_RUN_STANDALONE, LinkerOptions
from IsaacCompiler.code_gen.compile_stmnt import compile_stmnt
from IsaacCompiler.code_gen.stackvm_binutils.disassembly_lst_lines import (
    disassembly_lst_lines,
)
from IsaacCompiler.code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from IsaacCompiler.code_gen.stackvm_binutils.lib_util_asm_impl.lib_utils import (
    lib_utils_abi,
)
from IsaacCompiler.lexer.lexer import get_list_tokens
from IsaacCompiler.parser.stmnt.get_stmnt import get_stmnt
from IsaacCompiler.parser.type.CompileContext import CompileContext


def _flatify_dep_desc(dep_dct, start_key):
    result = set()
    pending = {start_key}
    while pending:
        current = pending
        result |= current
        pending = set()
        for key in current:
            pending.update(dep_dct[key])
        pending -= result
    return result


def _compile_source(source, remove_unused_deps=True):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None)

    link_opts = LinkerOptions(
        remove_unused_deps,
        4096,
        lib_utils_abi.objects,
        LNK_RUN_STANDALONE,
        None,
    )
    cmpl_opts = CompilerOptions(link_opts, True, False)
    cmpl_obj = Compilation(cmpl_opts.keep_local_syms)

    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)

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
    vm = VM(65536)
    vm.load_program(cmpl_obj.memory, 0)
    vm.push(4, 0)
    add_cmd_argv_vm(vm, len(cmpl_obj.memory), ["prog"])
    vm.execute()
    return vm


def _get_global_addr(global_ctx, cmpl_obj, name):
    ctx_var = global_ctx.vars[name]
    return cmpl_obj.get_link(ctx_var.get_link_name()).src


def _read_global(vm, global_ctx, cmpl_obj, name, size, signed=False):
    addr = _get_global_addr(global_ctx, cmpl_obj, name)
    return int.from_bytes(vm.memory[addr : addr + size], "little", signed=signed)


def _disasm_lines(cmpl_obj):
    return [
        text for _addr, text in disassembly_lst_lines(cmpl_obj.memory, None, None, {})
    ]


class AtomicCodegenTests(unittest.TestCase):
    def test_atomic_qualified_objects_use_atomic_load_store_and_stay_aligned(self):
        global_ctx, cmpl_obj = _compile_source(
            "#include <stdatomic.h>\n"
            "struct Box { char pad; atomic_int value; };\n"
            '_Static_assert(sizeof(struct Box) == 8, "atomic member should be aligned");\n'
            "atomic_int global_counter = 0;\n"
            "unsigned long long local_addr_mod = 1;\n"
            "unsigned int observed = 0;\n"
            "int main(int argc, char **argv) {\n"
            "    atomic_int local_counter = 0;\n"
            "    local_addr_mod = ((unsigned long long)&local_counter) & 3ull;\n"
            "    global_counter = 7;\n"
            "    observed = global_counter;\n"
            "    return 0;\n"
            "}\n",
            remove_unused_deps=False,
        )

        self.assertEqual(
            _get_global_addr(global_ctx, cmpl_obj, "global_counter") % 4, 0
        )

        lines = _disasm_lines(cmpl_obj)
        self.assertTrue(any("STOR-ATOMIC_STORE|SZ_4|SEQ_CST" in line for line in lines))
        self.assertTrue(any("LOAD-ATOMIC_LOAD|SZ_4|SEQ_CST" in line for line in lines))

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "local_addr_mod", 8), 0)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "global_counter", 4), 7)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "observed", 4), 7)

    def test_stdatomic_header_lowers_atomic_operations_to_stackvm_intrinsics(self):
        global_ctx, cmpl_obj = _compile_source(
            "#include <stdatomic.h>\n"
            "atomic_int value = ATOMIC_VAR_INIT(3);\n"
            "int loaded = 0;\n"
            "int exchanged = 0;\n"
            "int fetched = 0;\n"
            "int cas_ok = 0;\n"
            "int cas_fail = 0;\n"
            "int expected_after_fail = 0;\n"
            "int main(int argc, char **argv) {\n"
            "    int expected_ok = 14;\n"
            "    int expected_fail = 99;\n"
            "    atomic_store_explicit(&value, 4, memory_order_release);\n"
            "    loaded = atomic_load_explicit(&value, memory_order_acquire);\n"
            "    exchanged = atomic_exchange_explicit(&value, 9, memory_order_seq_cst);\n"
            "    fetched = atomic_fetch_add_explicit(&value, 5, memory_order_relaxed);\n"
            "    cas_ok = atomic_compare_exchange_strong_explicit(&value, &expected_ok, 20, memory_order_seq_cst, memory_order_relaxed);\n"
            "    cas_fail = atomic_compare_exchange_strong_explicit(&value, &expected_fail, 30, memory_order_acquire, memory_order_relaxed);\n"
            "    expected_after_fail = expected_fail;\n"
            "    return 0;\n"
            "}\n",
            remove_unused_deps=False,
        )

        lines = _disasm_lines(cmpl_obj)
        self.assertTrue(any("STOR-ATOMIC_STORE|SZ_4|RELEASE" in line for line in lines))
        self.assertTrue(any("LOAD-ATOMIC_LOAD|SZ_4|ACQUIRE" in line for line in lines))
        self.assertTrue(any("LOAD-ATOMIC_XCHG|SZ_4|SEQ_CST" in line for line in lines))
        self.assertTrue(any("LOAD-ATOMIC_FADD|SZ_4|RELAXED" in line for line in lines))
        self.assertGreaterEqual(
            sum("LOAD-ATOMIC_CAS|SZ_4" in line for line in lines),
            2,
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "value", 4, signed=True), 20
        )
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "loaded", 4, signed=True), 4
        )
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "exchanged", 4, signed=True), 4
        )
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "fetched", 4, signed=True), 9
        )
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "cas_ok", 4, signed=True), 1
        )
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "cas_fail", 4, signed=True), 0
        )
        self.assertEqual(
            _read_global(
                vm, global_ctx, cmpl_obj, "expected_after_fail", 4, signed=True
            ),
            20,
        )


if __name__ == "__main__":
    unittest.main()
