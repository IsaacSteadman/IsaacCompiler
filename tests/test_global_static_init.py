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


def _compile_source(source, remove_unused_deps=True, default_alignment=None):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, default_alignment)
    va_base = PrimitiveType.from_str_name(["unsigned", "char"])
    va_type = QualType(QualType.QUAL_PTR, va_base)
    global_ctx.new_type("va_list", TypeDefCtxMember("va_list", global_ctx, va_type))

    link_opts = LinkerOptions(
        remove_unused_deps,
        4096,
        lib_utils_abi.objects,
        LNK_RUN_STANDALONE,
        default_alignment,
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

    main_fn = cmpl_obj.get_link("?FiPPczmain")
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


class GlobalStaticInitTests(unittest.TestCase):
    def test_constant_scalar_global_is_serialized(self):
        global_ctx, cmpl_obj = _compile_source(
            "int x = 3 + 4 * 5; int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )
        addr = _get_global_addr(global_ctx, cmpl_obj, "x")
        self.assertEqual(cmpl_obj.memory[addr : addr + 4], bytes([23, 0, 0, 0]))

    def test_string_initializers_are_serialized(self):
        global_ctx, cmpl_obj = _compile_source(
            'static const char msg[] = "hi"; const char *ptr = "hi"; '
            'int main(int argc, char **argv) { return 0; }\n',
            remove_unused_deps=False,
        )
        msg_addr = _get_global_addr(global_ctx, cmpl_obj, "msg")
        self.assertEqual(cmpl_obj.memory[msg_addr : msg_addr + 3], b"hi\0")

        ptr_addr = _get_global_addr(global_ctx, cmpl_obj, "ptr")
        ptr_target = int.from_bytes(cmpl_obj.memory[ptr_addr : ptr_addr + 8], "little")
        self.assertEqual(cmpl_obj.memory[ptr_target : ptr_target + 3], b"hi\0")
        self.assertNotIn(INIT_GLOBALS_LINK_NAME, cmpl_obj.objects)

    def test_struct_globals_are_serialized_recursively(self):
        global_ctx, cmpl_obj = _compile_source(
            "struct Pair { int a; int b; }; "
            "struct Pair p = { 1, 2 }; "
            "struct Node { struct Node *next; struct Node *prev; }; "
            "static struct Node head = { &head, &head }; "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )
        pair_addr = _get_global_addr(global_ctx, cmpl_obj, "p")
        self.assertEqual(
            cmpl_obj.memory[pair_addr : pair_addr + 8],
            bytes([1, 0, 0, 0, 2, 0, 0, 0]),
        )

        head_addr = _get_global_addr(global_ctx, cmpl_obj, "head")
        next_ptr = int.from_bytes(cmpl_obj.memory[head_addr : head_addr + 8], "little")
        prev_ptr = int.from_bytes(
            cmpl_obj.memory[head_addr + 8 : head_addr + 16], "little"
        )
        self.assertEqual(next_ptr, head_addr)
        self.assertEqual(prev_ptr, head_addr)

    def test_packed_structs_skip_internal_and_tail_padding(self):
        global_ctx, cmpl_obj = _compile_source(
            "struct NaturalLayout { "
            "    unsigned char a; unsigned int b; "
            "}; "
            "_Static_assert(sizeof(struct NaturalLayout) == 8, \"natural padded size\"); "
            "struct __attribute__((packed)) KeywordPacked { "
            "    unsigned char a; unsigned int b; "
            "}; "
            "_Static_assert(sizeof(struct KeywordPacked) == 5, \"keyword packed size\"); "
            "__attribute__((packed)) struct LeadingPacked { "
            "    unsigned char a; unsigned int b; unsigned char c; "
            "} p = { 1, 0x11223344, 2 }; "
            "_Static_assert(sizeof(struct LeadingPacked) == 6, \"leading packed size\"); "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
            default_alignment=8,
        )
        addr = _get_global_addr(global_ctx, cmpl_obj, "p")
        self.assertEqual(
            cmpl_obj.memory[addr : addr + 6],
            bytes([1, 0x44, 0x33, 0x22, 0x11, 2]),
        )

    def test_no_default_alignment_keeps_regular_struct_fields_adjacent(self):
        global_ctx, cmpl_obj = _compile_source(
            "struct Flat { unsigned char a; unsigned int b; unsigned char c; }; "
            "_Static_assert(sizeof(struct Flat) == 6, \"no default padding\"); "
            "struct Flat g = { 1, 0x11223344, 2 }; "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )
        addr = _get_global_addr(global_ctx, cmpl_obj, "g")
        self.assertEqual(
            cmpl_obj.memory[addr : addr + 6],
            bytes([1, 0x44, 0x33, 0x22, 0x11, 2]),
        )

    def test_aligned_structs_affect_embedding_and_tail_padding(self):
        global_ctx, cmpl_obj = _compile_source(
            "struct Inner { unsigned char c; } __attribute__((aligned(8))); "
            "_Static_assert(sizeof(struct Inner) == 8, \"inner aligned size\"); "
            "struct Outer { unsigned char lead; struct Inner inner; unsigned char tail; }; "
            "_Static_assert(sizeof(struct Outer) == 24, \"outer aligned size\"); "
            "struct Outer g; "
            "int main(int argc, char **argv) { "
            "    g.lead = 0xAA; "
            "    g.inner.c = 0xBB; "
            "    g.tail = 0xCC; "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )
        vm = _run_program(cmpl_obj)
        addr = _get_global_addr(global_ctx, cmpl_obj, "g")
        self.assertEqual(
            vm.memory[addr : addr + 24],
            bytes([0xAA])
            + bytes(7)
            + bytes([0xBB])
            + bytes(7)
            + bytes([0xCC])
            + bytes(7),
        )

    def test_aligned_global_is_placed_on_requested_boundary(self):
        global_ctx, cmpl_obj = _compile_source(
            "unsigned char before = 1; "
            "unsigned long __attribute__((aligned(8))) some_var = 0x01020304; "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )
        before_addr = _get_global_addr(global_ctx, cmpl_obj, "before")
        some_var_addr = _get_global_addr(global_ctx, cmpl_obj, "some_var")
        self.assertEqual(some_var_addr % 8, 0)
        self.assertGreaterEqual(some_var_addr - before_addr, 8)
        self.assertEqual(
            cmpl_obj.memory[some_var_addr : some_var_addr + 4],
            bytes([0x04, 0x03, 0x02, 0x01]),
        )

    def test_anonymous_struct_members_flatten_into_union_namespace(self):
        global_ctx, cmpl_obj = _compile_source(
            "typedef union { "
            "    struct { unsigned int lo; unsigned int hi; }; "
            "    unsigned long full; "
            "} u64_pair_t; "
            "_Static_assert(sizeof(u64_pair_t) == 8, \"union size\"); "
            "u64_pair_t x; "
            "int main(int argc, char **argv) { "
            "    x.full = 0; "
            "    x.lo = 1; "
            "    x.hi = 0x11223344; "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )
        vm = _run_program(cmpl_obj)
        addr = _get_global_addr(global_ctx, cmpl_obj, "x")
        self.assertEqual(
            vm.memory[addr : addr + 8],
            bytes([1, 0, 0, 0, 0x44, 0x33, 0x22, 0x11]),
        )

    def test_anonymous_members_include_enclosing_struct_offset(self):
        global_ctx, cmpl_obj = _compile_source(
            "struct Outer { "
            "    unsigned char tag; "
            "    union { "
            "        struct { unsigned int lo; unsigned int hi; }; "
            "        unsigned long full; "
            "    }; "
            "}; "
            "_Static_assert(sizeof(struct Outer) == 9, \"outer size\"); "
            "struct Outer x; "
            "int main(int argc, char **argv) { "
            "    x.tag = 0xAA; "
            "    x.hi = 0x55667788; "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )
        vm = _run_program(cmpl_obj)
        addr = _get_global_addr(global_ctx, cmpl_obj, "x")
        self.assertEqual(
            vm.memory[addr : addr + 9],
            bytes([0xAA, 0, 0, 0, 0, 0x88, 0x77, 0x66, 0x55]),
        )

    def test_dynamic_global_initializer_runs_before_main(self):
        global_ctx, cmpl_obj = _compile_source(
            "int seed() { return 7; } "
            "int x = seed(); "
            "int main(int argc, char **argv) { return 0; }\n"
        )
        self.assertIn(INIT_GLOBALS_LINK_NAME, cmpl_obj.objects)

        vm = _run_program(cmpl_obj)
        addr = _get_global_addr(global_ctx, cmpl_obj, "x")
        self.assertEqual(vm.memory[addr : addr + 4], bytes([7, 0, 0, 0]))

    def test_static_local_initializer_runs_once(self):
        global_ctx, cmpl_obj = _compile_source(
            "int calls = 0; "
            "int result = 0; "
            "int next() { calls = calls + 1; return calls * 10; } "
            "int f() { static int x = next(); return x; } "
            "int main(int argc, char **argv) { result = f() + f(); return 0; }\n"
        )
        self.assertTrue(
            any(key.endswith("$init_guard") for key in cmpl_obj.objects),
            "expected a static-local guard object",
        )

        vm = _run_program(cmpl_obj)
        calls_addr = _get_global_addr(global_ctx, cmpl_obj, "calls")
        result_addr = _get_global_addr(global_ctx, cmpl_obj, "result")
        self.assertEqual(
            int.from_bytes(vm.memory[calls_addr : calls_addr + 4], "little", signed=True),
            1,
        )
        self.assertEqual(
            int.from_bytes(vm.memory[result_addr : result_addr + 4], "little", signed=True),
            20,
        )


if __name__ == "__main__":
    unittest.main()
