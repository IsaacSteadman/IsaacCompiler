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
            pending.update(dep_dct[key])
        pending -= result
    return result


def _compile_source(source, remove_unused_deps=True):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None)
    va_base = PrimitiveType.from_str_name(["unsigned", "char"])
    va_type = QualType(QualType.QUAL_PTR, va_base)
    global_ctx.new_type("va_list", TypeDefCtxMember("va_list", global_ctx, va_type))

    link_opts = LinkerOptions(
        remove_unused_deps,
        4096,
        runtime_extern_deps,
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


class KernelLibcBuiltinTests(unittest.TestCase):
    def test_compile_time_builtins_and_has_builtin(self):
        global_ctx, cmpl_obj = _compile_source(
            "int x = 0; "
            "int const_flags = __builtin_constant_p(1 + 2) "
            "    + 2 * __builtin_constant_p(x); "
            "int chosen_a = __builtin_choose_expr(1, 41, missing_symbol); "
            "int chosen_b = __builtin_choose_expr(0, missing_symbol, 9); "
            "int expected = __builtin_expect_with_probability(7, 1, 0.75); "
            "unsigned long long obj = __builtin_object_size(&x, 0); "
            "unsigned long long dyn_obj = __builtin_dynamic_object_size(&x, 1); "
            "int builtin_flags = __has_builtin(__builtin_constant_p) "
            "    + 2 * __has_builtin(__builtin_choose_expr) "
            "    + 4 * __has_builtin(__builtin_object_size) "
            "    + 8 * __has_builtin(__builtin_dynamic_object_size) "
            "    + 16 * __has_builtin(__builtin_alloca) "
            "    + 32 * __has_builtin(__builtin_add_overflow) "
            "    + 64 * __has_builtin(__builtin_trap) "
            "    + 128 * __has_builtin(__builtin_prefetch) "
            "    + 256 * __has_builtin(__builtin_return_address); "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )

        mem = cmpl_obj.memory
        self.assertEqual(_read_mem(mem, global_ctx, cmpl_obj, "const_flags"), 1)
        self.assertEqual(_read_mem(mem, global_ctx, cmpl_obj, "chosen_a"), 41)
        self.assertEqual(_read_mem(mem, global_ctx, cmpl_obj, "chosen_b"), 9)
        self.assertEqual(_read_mem(mem, global_ctx, cmpl_obj, "expected"), 7)
        self.assertEqual(
            _read_mem(mem, global_ctx, cmpl_obj, "obj", 8, signed=False),
            (1 << 64) - 1,
        )
        self.assertEqual(
            _read_mem(mem, global_ctx, cmpl_obj, "dyn_obj", 8, signed=False),
            (1 << 64) - 1,
        )
        self.assertEqual(_read_mem(mem, global_ctx, cmpl_obj, "builtin_flags"), 511)

    def test_runtime_misc_builtins(self):
        global_ctx, cmpl_obj = _compile_source(
            "int result = 0; "
            "int clrsb_zero = 0; "
            "int clrsb_neg = 0; "
            "int clrsb_one = 0; "
            "int clrsb_ll_one = 0; "
            "int prefetch_count = 0; "
            "int frame_nonzero = 0; "
            "int ret_nonzero = 0; "
            "int use_alloca(int n) { "
            "    char *p = (char *)__builtin_alloca(n); "
            "    p[0] = 7; "
            "    p[n - 1] = 11; "
            "    int after = 5; "
            "    return p[0] + p[n - 1] + after; "
            "} "
            "void probe_frame(void) { "
            "    frame_nonzero = ((unsigned long long)__builtin_frame_address(0)) != 0; "
            "    ret_nonzero = ((unsigned long long)__builtin_return_address(0)) != 0; "
            "} "
            "int main(int argc, char **argv) { "
            "    int i = 0; "
            "    int arr[3]; "
            "    clrsb_zero = __builtin_clrsb(0); "
            "    clrsb_neg = __builtin_clrsb(-1); "
            "    clrsb_one = __builtin_clrsb(1); "
            "    clrsb_ll_one = __builtin_clrsbll(1LL); "
            "    __builtin_prefetch(&arr[i++], 0, 3); "
            "    prefetch_count = i; "
            "    probe_frame(); "
            "    result = use_alloca(13); "
            "    return 0; "
            "}\n"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "clrsb_zero"), 31)
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "clrsb_neg"), 31)
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "clrsb_one"), 30)
        self.assertEqual(
            _read_mem(vm.memory, global_ctx, cmpl_obj, "clrsb_ll_one"), 62
        )
        self.assertEqual(
            _read_mem(vm.memory, global_ctx, cmpl_obj, "prefetch_count"), 1
        )
        self.assertEqual(
            _read_mem(vm.memory, global_ctx, cmpl_obj, "frame_nonzero"), 1
        )
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "ret_nonzero"), 1)
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "result"), 23)

    def test_overflow_builtins_store_wrapped_result_and_report_overflow(self):
        global_ctx, cmpl_obj = _compile_source(
            "int flags = 0; "
            "int s_out = 0; "
            "unsigned int u_out = 0; "
            "signed char c_out = 0; "
            "int main(int argc, char **argv) { "
            "    flags = __builtin_add_overflow(2147483647, 1, &s_out); "
            "    flags += 2 * __builtin_add_overflow(10, 20, &s_out); "
            "    flags += 4 * __builtin_sub_overflow((unsigned int)0, (unsigned int)1, &u_out); "
            "    flags += 8 * __builtin_mul_overflow(100000, 100000, &s_out); "
            "    flags += 16 * __builtin_add_overflow(120, 10, &c_out); "
            "    return 0; "
            "}\n"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "flags"), 29)
        self.assertEqual(
            _read_mem(vm.memory, global_ctx, cmpl_obj, "u_out", 4, signed=False),
            (1 << 32) - 1,
        )
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "c_out", 1), -126)

    def test_trap_and_unreachable_halt_execution(self):
        global_ctx, cmpl_obj = _compile_source(
            "int result = 0; "
            "void unused_trap(void) { __builtin_trap(); } "
            "int main(int argc, char **argv) { "
            "    result = 7; "
            "    __builtin_unreachable(); "
            "    result = 9; "
            "    return 0; "
            "}\n"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_mem(vm.memory, global_ctx, cmpl_obj, "result"), 7)


if __name__ == "__main__":
    unittest.main()
