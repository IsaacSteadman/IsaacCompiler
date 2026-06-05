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
from IsaacCompiler.code_gen.stackvm_binutils.lib_util_asm_impl.lib_utils import (
    lib_utils_abi,
)
from IsaacCompiler.lexer.lexer import get_list_tokens
from IsaacCompiler.parser.stmnt.get_stmnt import get_stmnt
from IsaacCompiler.parser.type.CompileContext import CompileContext


def _compile_source(source):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None)
    link_opts = LinkerOptions(
        False,
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
    cmpl_obj.merge_all(link_opts, link_opts.extern_deps, None)
    assert cmpl_obj.link_all()
    return global_ctx, cmpl_obj


def _run_program(cmpl_obj):
    vm = VM(65536)
    vm.load_program(cmpl_obj.memory, 0)
    vm.push(4, 0)
    add_cmd_argv_vm(vm, len(cmpl_obj.memory), ["prog"])
    vm.execute()
    return vm


def _read_global(vm, global_ctx, cmpl_obj, name):
    addr = cmpl_obj.get_link(global_ctx.vars[name].get_link_name()).src
    return int.from_bytes(vm.memory[addr : addr + 4], "little", signed=True)


class AsmGotoTests(unittest.TestCase):
    def test_existing_stackvm_asm_block_still_works(self):
        global_ctx, cmpl_obj = _compile_source(
            "int result = 0;"
            "int main(int argc, char **argv) {"
            '    asm { "NOP" }'
            "    result = 2;"
            "    return 0;"
            "}"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "result"), 2)

    def test_parser_accepts_gnu_sections_and_label_list(self):
        tokens = get_list_tokens(
            'asm volatile goto("lRa*:%l[out]\\n" "JMP" '
            ': : [value] "r"(value) : "cc", "memory" : out, other);'
        )
        stmnt, cursor = get_stmnt(tokens, 0, len(tokens), CompileContext("", None))

        self.assertEqual(cursor, len(tokens))
        self.assertTrue(stmnt.is_goto)
        self.assertEqual(stmnt.qualifiers, {"volatile", "goto"})
        self.assertEqual(stmnt.inner_asm, ["lRa*:%l[out]\nJMP"])
        self.assertEqual(stmnt.goto_labels, ["out", "other"])
        self.assertEqual(stmnt.goto_label_operand_base, 1)

    def test_named_label_is_backpatched_and_jump_skips_fallthrough(self):
        global_ctx, cmpl_obj = _compile_source(
            "int result = 0;"
            "int main(int argc, char **argv) {"
            "    result = 1;"
            '    asm goto("lRa*:%l[taken]\\nJMP" : : : : taken);'
            "    result = 2;"
            "    goto done;"
            "taken:"
            "    result = 3;"
            "done:"
            "    return 0;"
            "}"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "result"), 3)

    def test_asm_goto_can_fall_through(self):
        global_ctx, cmpl_obj = _compile_source(
            "int result = 0;"
            "int main(int argc, char **argv) {"
            "    result = 1;"
            '    asm goto("NOP" : : : : unused_path);'
            "    result = 2;"
            "unused_path:"
            "    return 0;"
            "}"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "result"), 2)

    def test_positional_label_accounts_for_input_operands(self):
        global_ctx, cmpl_obj = _compile_source(
            "int result = 0;"
            "int main(int argc, char **argv) {"
            "    result = 1;"
            '    asm goto("LOAD %l1\\nJMP" : : "r"(argc) : : taken);'
            "    result = 2;"
            "    goto done;"
            "taken:"
            "    result = 3;"
            "done:"
            "    return 0;"
            "}"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "result"), 3)

    def test_template_label_must_appear_in_label_list(self):
        with self.assertRaisesRegex(ValueError, "not present in its label list"):
            _compile_source(
                "int main(int argc, char **argv) {"
                '    asm goto("%l[missing]\\nJMP" : : : : target);'
                "target:"
                "    return 0;"
                "}"
            )

    def test_referenced_c_label_must_be_defined(self):
        with self.assertRaisesRegex(NameError, "Undefined label 'target'"):
            _compile_source(
                "int main(int argc, char **argv) {"
                '    asm goto("%l[target]\\nJMP" : : : : target);'
                "    return 0;"
                "}"
            )

    def test_listed_c_label_must_be_defined_even_without_template_operand(self):
        with self.assertRaisesRegex(NameError, "Undefined label 'target'"):
            _compile_source(
                "int main(int argc, char **argv) {"
                '    asm goto("NOP" : : : : target);'
                "    return 0;"
                "}"
            )


if __name__ == "__main__":
    unittest.main()
