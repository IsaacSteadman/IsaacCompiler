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
from IsaacCompiler.code_gen.stackvm_binutils.lib_util_asm_impl.lib_utils import lib_utils_abi
from IsaacCompiler.lexer.lexer import get_list_tokens
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


class BuiltinOffsetofTests(unittest.TestCase):
    def test_builtin_offsetof_is_available_to_static_assert(self):
        _compile_source(
            "struct packet { unsigned int len; unsigned int data; }; "
            '_Static_assert(__builtin_offsetof(struct packet, data) == 4, "offset"); '
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )

    def test_offsetof_macro_serializes_global_initializer_without_runtime_init(self):
        global_ctx, cmpl_obj = _compile_source(
            "#define offsetof(TYPE, MEMBER) __builtin_offsetof(TYPE, MEMBER)\n"
            "struct sk_buff { unsigned int len; unsigned int data; }; "
            "unsigned int off = offsetof(struct sk_buff, data); "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )

        off_addr = _get_global_addr(global_ctx, cmpl_obj, "off")
        self.assertEqual(
            cmpl_obj.memory[off_addr : off_addr + 4],
            (4).to_bytes(4, "little"),
        )
        self.assertNotIn(INIT_GLOBALS_LINK_NAME, cmpl_obj.objects)

    def test_builtin_offsetof_can_be_used_in_runtime_expressions(self):
        global_ctx, cmpl_obj = _compile_source(
            "struct packet { unsigned int len; unsigned int data; }; "
            "int result = 0; "
            "int main(int argc, char **argv) { "
            "    result = __builtin_offsetof(struct packet, data); "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )

        vm = _run_program(cmpl_obj)
        result_addr = _get_global_addr(global_ctx, cmpl_obj, "result")
        self.assertEqual(
            int.from_bytes(vm.memory[result_addr : result_addr + 4], "little", signed=True),
            4,
        )

    def test_builtin_offsetof_uses_anonymous_member_byte_offset(self):
        global_ctx, cmpl_obj = _compile_source(
            "struct Outer { "
            "    unsigned char tag; "
            "    union { "
            "        struct { unsigned int lo; unsigned int hi; }; "
            "        unsigned long full; "
            "    }; "
            "}; "
            "unsigned int hi_off = __builtin_offsetof(struct Outer, hi); "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )

        hi_off_addr = _get_global_addr(global_ctx, cmpl_obj, "hi_off")
        self.assertEqual(
            cmpl_obj.memory[hi_off_addr : hi_off_addr + 4],
            (5).to_bytes(4, "little"),
        )
        self.assertNotIn(INIT_GLOBALS_LINK_NAME, cmpl_obj.objects)


if __name__ == "__main__":
    unittest.main()
