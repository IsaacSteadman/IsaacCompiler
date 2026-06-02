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
from IsaacCompiler.parser.type.types import CompileContext


MAIN_LINK_NAME = "?FiPPczmain"


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

    main_fn = cmpl_obj.get_link(MAIN_LINK_NAME)
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


def _read_global(vm, global_ctx, cmpl_obj, name, size):
    addr = _get_global_addr(global_ctx, cmpl_obj, name)
    return int.from_bytes(vm.memory[addr : addr + size], "little")


def _volatile_access_pattern(cmpl_obj):
    main_obj = cmpl_obj.objects[MAIN_LINK_NAME]
    return [
        (access.kind, access.size, access.lowered_as_copy)
        for access in main_obj.memory_accesses
        if access.is_volatile
    ]


class VolatileCodegenTests(unittest.TestCase):
    def test_named_volatile_accesses_are_tracked_and_not_elided(self):
        global_ctx, cmpl_obj = _compile_source(
            "volatile unsigned int reg_value = 0; "
            "unsigned int first = 0; "
            "unsigned int second = 0; "
            "int main(int argc, char **argv) { "
            "    reg_value = 1u; "
            "    first = reg_value; "
            "    second = reg_value; "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )

        self.assertEqual(
            _volatile_access_pattern(cmpl_obj),
            [("stor", 4, False), ("load", 4, False), ("load", 4, False)],
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "reg_value", 4), 1)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "first", 4), 1)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "second", 4), 1)

    def test_volatile_pointer_dereferences_are_tracked_and_not_elided(self):
        global_ctx, cmpl_obj = _compile_source(
            "unsigned int gpio_storage = 0; "
            "volatile unsigned int *gpio = &gpio_storage; "
            "unsigned int first = 0; "
            "unsigned int second = 0; "
            "int main(int argc, char **argv) { "
            "    *gpio = 7u; "
            "    first = *gpio; "
            "    second = *gpio; "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )

        self.assertEqual(
            _volatile_access_pattern(cmpl_obj),
            [("stor", 4, False), ("load", 4, False), ("load", 4, False)],
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "gpio_storage", 4), 7)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "first", 4), 7)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "second", 4), 7)


if __name__ == "__main__":
    unittest.main()
