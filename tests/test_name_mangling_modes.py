import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.Preprocessing import preprocess
from IsaacCompiler.StackVM.PyStackVM import BC_CALL, BC_HLT, VM
from IsaacCompiler.StackVM.runner import add_cmd_argv_vm
from IsaacCompiler.code_gen.Compilation import Compilation, INIT_GLOBALS_LINK_NAME
from IsaacCompiler.code_gen.CompilerOptions import CompilerOptions
from IsaacCompiler.code_gen.LinkerOptions import LNK_RUN_STANDALONE, LinkerOptions
from IsaacCompiler.code_gen.NameMangling import NameManglingMode
from IsaacCompiler.code_gen.compile_stmnt import compile_stmnt
from IsaacCompiler.code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from IsaacCompiler.code_gen.stackvm_binutils.lib_util_asm_impl.lib_utils import (
    get_lib_utils_abi,
)
from IsaacCompiler.lexer.lexer import get_list_tokens
from IsaacCompiler.lib.runtime_support import get_runtime_extern_deps
from IsaacCompiler.parser.stmnt.get_stmnt import get_stmnt
from IsaacCompiler.parser.type.types import CompileContext


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


def _compile_source(source, mode):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None, name_mangling_mode=mode)
    runtime_deps = get_runtime_extern_deps(mode)
    link_opts = LinkerOptions(
        True,
        4096,
        runtime_deps,
        LNK_RUN_STANDALONE,
        None,
        mode,
    )
    cmpl_opts = CompilerOptions(link_opts, True, False, mode)
    cmpl_obj = Compilation(False, mode)

    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)

    init_obj = cmpl_obj.finalize_global_initializer()
    if init_obj is not None:
        cmpl_obj.get_link(INIT_GLOBALS_LINK_NAME).emit_lea(cmpl_obj.memory)
        cmpl_obj.memory.extend([BC_CALL])

    main_link_name = global_ctx.vars["main"].get_link_name()
    emit_load_i_const(cmpl_obj.memory, 1, True, 2)
    cmpl_obj.get_link(main_link_name).emit_lea(cmpl_obj.memory)
    cmpl_obj.memory.extend([BC_CALL, BC_HLT])

    dep_tree = [("", sorted(cmpl_obj.linkages))]
    for key, obj in cmpl_obj.objects.items():
        dep_tree.append((key, sorted(obj.linkages)))
    for key, obj in runtime_deps.items():
        dep_tree.append((key, sorted(obj.linkages)))
    dep_dct = dict(dep_tree)
    used_deps = _flatify_dep_desc(dep_dct, "")
    defined_deps = {key for key, _deps in dep_tree if key}
    cmpl_obj.merge_all(link_opts, runtime_deps, defined_deps - used_deps)
    assert cmpl_obj.link_all()
    return global_ctx, cmpl_obj


def _run_program(cmpl_obj):
    vm = VM(65536)
    vm.load_program(cmpl_obj.memory, 0)
    vm.push(4, 0)
    add_cmd_argv_vm(vm, len(cmpl_obj.memory), ["prog"])
    vm.execute()
    return vm


class NameManglingModeTests(unittest.TestCase):
    def test_mode_specific_lib_utils_exports_and_internal_references(self):
        raw = get_lib_utils_abi(NameManglingMode.NONE)
        mangled = get_lib_utils_abi(NameManglingMode.ISAAC)

        self.assertTrue(
            {"memcpy", "memmove", "memset", "print", "syscall", "pow"}
            <= set(raw.objects)
        )
        self.assertEqual(set(raw.objects["memcpy"].linkages), {"memmove"})
        self.assertEqual(set(raw.objects["print"].linkages), {"syscall"})

        self.assertTrue(
            {
                "?FPvPCvyzmemcpy",
                "?FPvPvyzmemmove",
                "?FPvcyzmemset",
                "?FPCczprint",
                "?Fyyyyyzsyscall",
                "?Fdizpow",
            }
            <= set(mangled.objects)
        )
        self.assertEqual(
            set(mangled.objects["?FPvPCvyzmemcpy"].linkages),
            {"?FPvPvyzmemmove"},
        )
        self.assertEqual(
            set(mangled.objects["?FPCczprint"].linkages),
            {"?Fyyyyyzsyscall"},
        )
        for name in ("@@ByteCopyFn", "@@ByteCopyFn1", "@@ByteCopyFn2"):
            self.assertIn(name, raw.objects)
            self.assertIn(name, mangled.objects)

    def test_runtime_functions_and_compiler_builtins_execute_in_both_modes(self):
        source = (
            "void *memset(void *ptr, unsigned char value, unsigned long long num); "
            "char filled[8]; "
            "char direct[8]; "
            "char copied[8]; "
            'char src[] = "abc"; '
            "unsigned long long copied_len = 0; "
            "int bit_count = 0; "
            "int main(int argc, char **argv) { "
            "    __builtin_memset(filled, 'x', 3); "
            "    filled[3] = 0; "
            "    memset(direct, 'y', 2); "
            "    direct[2] = 0; "
            "    __builtin_memcpy(copied, src, 4); "
            "    copied_len = __builtin_strlen(copied); "
            "    bit_count = __builtin_popcount((unsigned int)0xF1); "
            "    return 0; "
            "}\n"
        )
        for mode in (NameManglingMode.NONE, NameManglingMode.ISAAC):
            with self.subTest(mode=mode.value):
                global_ctx, cmpl_obj = _compile_source(source, mode)
                vm = _run_program(cmpl_obj)

                filled_addr = cmpl_obj.get_link(
                    global_ctx.vars["filled"].get_link_name()
                ).src
                copied_addr = cmpl_obj.get_link(
                    global_ctx.vars["copied"].get_link_name()
                ).src
                direct_addr = cmpl_obj.get_link(
                    global_ctx.vars["direct"].get_link_name()
                ).src
                copied_len_addr = cmpl_obj.get_link(
                    global_ctx.vars["copied_len"].get_link_name()
                ).src
                bit_count_addr = cmpl_obj.get_link(
                    global_ctx.vars["bit_count"].get_link_name()
                ).src

                self.assertEqual(bytes(vm.memory[filled_addr : filled_addr + 4]), b"xxx\0")
                self.assertEqual(bytes(vm.memory[direct_addr : direct_addr + 3]), b"yy\0")
                self.assertEqual(bytes(vm.memory[copied_addr : copied_addr + 4]), b"abc\0")
                self.assertEqual(
                    int.from_bytes(vm.memory[copied_len_addr : copied_len_addr + 8], "little"),
                    3,
                )
                self.assertEqual(
                    int.from_bytes(
                        vm.memory[bit_count_addr : bit_count_addr + 4],
                        "little",
                        signed=True,
                    ),
                    5,
                )


if __name__ == "__main__":
    unittest.main()
