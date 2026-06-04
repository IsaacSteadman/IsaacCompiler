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
from IsaacCompiler.parser.type.types import (
    CompileContext,
    PrimitiveType,
    QualType,
    TypeDefCtxMember,
)


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


class BuiltinBitOpsTests(unittest.TestCase):
    def test_bit_builtins_produce_expected_results(self):
        global_ctx, cmpl_obj = _compile_source(
            "int clz_zero = -1; "
            "int clz_one = -1; "
            "int clzl_one = -1; "
            "int ctz_zero = -1; "
            "int ctz_val = -1; "
            "int popcnt_val = -1; "
            "unsigned short bswap16_v = 0; "
            "unsigned int bswap32_v = 0; "
            "unsigned long long bswap64_v = 0; "
            "int ffs_zero = -1; "
            "int ffs_val = -1; "
            "int clzll_one = -1; "
            "int popcntll_val = -1; "
            "int ffsl_val = -1; "
            "int main(int argc, char **argv) { "
            "    clz_zero = __builtin_clz((unsigned int)0); "
            "    clz_one = __builtin_clz((unsigned int)1); "
            "    clzl_one = __builtin_clzl((unsigned long long)1); "
            "    ctz_zero = __builtin_ctz((unsigned int)0); "
            "    ctz_val = __builtin_ctz((unsigned int)0x40); "
            "    popcnt_val = __builtin_popcount((unsigned int)0xF0F1); "
            "    bswap16_v = __builtin_bswap16((unsigned short)0x1234); "
            "    bswap32_v = __builtin_bswap32((unsigned int)0x12345678); "
            "    bswap64_v = __builtin_bswap64((((unsigned long long)0x01020304) << 32) | 0x05060708); "
            "    ffs_zero = __builtin_ffs((unsigned int)0); "
            "    ffs_val = __builtin_ffs((unsigned int)0x48); "
            "    clzll_one = __builtin_clzll((unsigned long long)1); "
            "    popcntll_val = __builtin_popcountll((((unsigned long long)0xF) << 60) | 0xF); "
            "    ffsl_val = __builtin_ffsl((unsigned long long)0x1000); "
            "    return 0; "
            "}\n"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "clz_zero", 4, True), 32)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "clz_one", 4, True), 31)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "clzl_one", 4, True), 63)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "ctz_zero", 4, True), 32)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "ctz_val", 4, True), 6)
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "popcnt_val", 4, True), 9
        )
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "bswap16_v", 2), 0x3412)
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "bswap32_v", 4), 0x78563412
        )
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "bswap64_v", 8),
            0x0807060504030201,
        )
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "ffs_zero", 4, True), 0)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "ffs_val", 4, True), 4)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "clzll_one", 4, True), 63)
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "popcntll_val", 4, True), 8
        )
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "ffsl_val", 4, True), 13)

    def test_helper_library_symbols_are_linked_by_default(self):
        global_ctx, cmpl_obj = _compile_source(
            "unsigned int __svm_bswap4(unsigned int); "
            "unsigned int result = 0; "
            "int main(int argc, char **argv) { "
            "    result = __svm_bswap4((unsigned int)0x01020304); "
            "    return 0; "
            "}\n"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(
            _read_global(vm, global_ctx, cmpl_obj, "result", 4), 0x04030201
        )

    def test_has_builtin_reports_supported_bitops(self):
        global_ctx, cmpl_obj = _compile_source(
            "int flags = __has_builtin(__builtin_clz) "
            "    + 2 * __has_builtin(__builtin_bswap32) "
            "    + 4 * __has_builtin(__builtin_ffsll) "
            "    + 8 * __has_builtin(__builtin_not_real); "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )

        flags_addr = _get_global_addr(global_ctx, cmpl_obj, "flags")
        self.assertEqual(
            int.from_bytes(cmpl_obj.memory[flags_addr : flags_addr + 4], "little", signed=True),
            7,
        )


if __name__ == "__main__":
    unittest.main()
