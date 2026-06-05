import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.Preprocessing import preprocess
from IsaacCompiler.StackVM.PyStackVM import VM
from IsaacCompiler.StackVM.runner import add_cmd_argv_vm
from IsaacCompiler.code_gen.Compilation import Compilation
from IsaacCompiler.code_gen.LinkerOptions import LNK_RUN_STANDALONE, LinkerOptions
from IsaacCompiler.code_gen.compile_stmnt import compile_stmnt
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


def _compile_source(source):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("")
    link_opts = LinkerOptions(
        True,
        4096,
        lib_utils_abi.objects,
        LNK_RUN_STANDALONE,
    )
    cmpl_obj = Compilation(False)

    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)

    cmpl_obj.emit_standalone_startup(global_ctx.vars["main"].get_link_name())
    dep_tree = [("", sorted(cmpl_obj.linkages))]
    dep_tree.extend(
        (name, sorted(obj.linkages)) for name, obj in cmpl_obj.objects.items()
    )
    dep_tree.extend(
        (name, sorted(obj.linkages)) for name, obj in link_opts.extern_deps.items()
    )
    dep_dct = dict(dep_tree)
    used_deps = _flatify_dep_desc(dep_dct, "")
    defined_deps = {name for name, _deps in dep_tree if name}
    cmpl_obj.merge_all(
        link_opts,
        link_opts.extern_deps,
        defined_deps - used_deps,
    )
    assert cmpl_obj.link_all()
    return global_ctx, cmpl_obj


def _run_program(cmpl_obj):
    vm = VM(65536)
    vm.load_program(cmpl_obj.memory, 0)
    vm.push(4, 0)
    add_cmd_argv_vm(vm, len(cmpl_obj.memory), ["prog"])
    vm.execute()
    return vm


class ConstructorDestructorTests(unittest.TestCase):
    def test_lifecycle_functions_run_around_main_in_priority_order(self):
        global_ctx, cmpl_obj = _compile_source(
            "int trace = 0; "
            "static void add(int digit) { trace = trace * 10 + digit; } "
            "static void __attribute__((constructor(200))) ctor_late(void) "
            "{ add(2); } "
            "static void __attribute__((constructor(101))) ctor_early(void) "
            "{ add(1); } "
            "static void __attribute__((destructor(101))) dtor_last(void) "
            "{ add(5); } "
            "static void __attribute__((destructor(200))) dtor_first(void) "
            "{ add(4); } "
            "int main(int argc, char **argv) { add(3); return 0; }\n"
        )

        self.assertEqual(len(cmpl_obj.lifecycle_functions), 4)
        vm = _run_program(cmpl_obj)
        trace_addr = cmpl_obj.get_link(global_ctx.vars["trace"].get_link_name()).src
        self.assertEqual(
            int.from_bytes(
                vm.memory[trace_addr : trace_addr + 4],
                "little",
                signed=True,
            ),
            12345,
        )

    def test_lifecycle_functions_require_void_no_argument_signatures(self):
        with self.assertRaisesRegex(TypeError, "must return void"):
            _compile_source(
                "int __attribute__((constructor)) bad(void) { return 0; } "
                "int main(int argc, char **argv) { return 0; }\n"
            )
        with self.assertRaisesRegex(TypeError, "cannot accept arguments"):
            _compile_source(
                "void __attribute__((destructor)) bad(int value) {} "
                "int main(int argc, char **argv) { return 0; }\n"
            )


if __name__ == "__main__":
    unittest.main()
