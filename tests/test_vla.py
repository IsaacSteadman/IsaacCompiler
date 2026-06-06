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
    cmpl_obj = Compilation(True)

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
    excl = defined_deps - used_deps if link_opts.remove_unused_deps else None

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


def _read_global(vm, global_ctx, cmpl_obj, name, size=4, signed=True):
    ctx_var = global_ctx.vars[name]
    addr = cmpl_obj.get_link(ctx_var.get_link_name()).src
    return int.from_bytes(vm.memory[addr : addr + size], "little", signed=signed)


class VariableLengthArrayTests(unittest.TestCase):
    def test_runtime_bound_array_indexes_and_locals_after_vla(self):
        global_ctx, cmpl_obj = _compile_source(
            "int result; "
            "int f(int n) { "
            "    int arr[n]; "
            "    arr[0] = 7; "
            "    arr[n - 1] = 11; "
            "    int after = 3; "
            "    return arr[0] + arr[n - 1] + after; "
            "} "
            "int main(int argc, char **argv) { result = f(5); return 0; }\n"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "result"), 21)

    def test_break_out_of_vla_scope_restores_stack_before_following_local(self):
        global_ctx, cmpl_obj = _compile_source(
            "int result; "
            "int f(int n) { "
            "    int total = 0; "
            "    while (1) { "
            "        int arr[n]; "
            "        arr[0] = 9; "
            "        total = arr[0]; "
            "        break; "
            "    } "
            "    int after = 4; "
            "    return total + after; "
            "} "
            "int main(int argc, char **argv) { result = f(6); return 0; }\n"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "result"), 13)

    def test_non_literal_constant_bound_remains_fixed_size_array(self):
        global_ctx, cmpl_obj = _compile_source(
            "int result; "
            "int main(int argc, char **argv) { "
            "    int arr[2 + 2]; "
            "    arr[3] = 17; "
            "    result = arr[3]; "
            "    return 0; "
            "}\n"
        )

        vm = _run_program(cmpl_obj)
        self.assertEqual(_read_global(vm, global_ctx, cmpl_obj, "result"), 17)

    def test_static_storage_vla_is_rejected(self):
        with self.assertRaisesRegex(
            TypeError, "Variable-length arrays require automatic local storage"
        ):
            _compile_source(
                "int n; int arr[n]; "
                "int main(int argc, char **argv) { return 0; }\n"
            )


if __name__ == "__main__":
    unittest.main()
