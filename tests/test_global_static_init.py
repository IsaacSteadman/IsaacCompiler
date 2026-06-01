import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.Preprocessing import preprocess
from IsaacCompiler.StackVM.PyStackVM import BC_CALL, BC_HLT, BC_INT128, BC_RET, VM
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
    StructType,
    TypeDefCtxMember,
    size_of,
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

    def test__bool_globals_use_one_byte_and_normalize_non_zero_values(self):
        global_ctx, cmpl_obj = _compile_source(
            '_Static_assert(sizeof(_Bool) == 1, "_Bool size"); '
            "_Bool zero = 0; "
            "_Bool two = 2; "
            "_Bool neg = -7; "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )
        zero_addr = _get_global_addr(global_ctx, cmpl_obj, "zero")
        two_addr = _get_global_addr(global_ctx, cmpl_obj, "two")
        neg_addr = _get_global_addr(global_ctx, cmpl_obj, "neg")
        self.assertEqual(cmpl_obj.memory[zero_addr : zero_addr + 1], bytes([0]))
        self.assertEqual(cmpl_obj.memory[two_addr : two_addr + 1], bytes([1]))
        self.assertEqual(cmpl_obj.memory[neg_addr : neg_addr + 1], bytes([1]))

    def test_stdbool_header_macros_and_pointer_to_bool_conversion_work(self):
        global_ctx, cmpl_obj = _compile_source(
            "#include <stdbool.h>\n"
            '_Static_assert(sizeof(bool) == 1, "bool size"); '
            "bool g_true = true; "
            "bool g_false = false; "
            "int result = 0; "
            "int main(int argc, char **argv) { "
            "    bool from_int = 2; "
            "    bool from_zero = false; "
            "    bool from_ptr = &result; "
            "    result = g_true + g_false + from_int + from_zero + from_ptr; "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )
        true_addr = _get_global_addr(global_ctx, cmpl_obj, "g_true")
        false_addr = _get_global_addr(global_ctx, cmpl_obj, "g_false")
        self.assertEqual(cmpl_obj.memory[true_addr : true_addr + 1], bytes([1]))
        self.assertEqual(cmpl_obj.memory[false_addr : false_addr + 1], bytes([0]))

        vm = _run_program(cmpl_obj)
        result_addr = _get_global_addr(global_ctx, cmpl_obj, "result")
        self.assertEqual(
            int.from_bytes(vm.memory[result_addr : result_addr + 4], "little", signed=True),
            3,
        )

    def test_int128_globals_have_16_byte_storage_and_expected_bytes(self):
        global_ctx, cmpl_obj = _compile_source(
            '_Static_assert(sizeof(__int128) == 16, "__int128 size"); '
            '_Static_assert(sizeof(unsigned __int128) == 16, "uint128 size"); '
            "unsigned __int128 low = (unsigned __int128)0x1122334455667788ULL; "
            "__int128 neg = -1; "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
        )
        low_addr = _get_global_addr(global_ctx, cmpl_obj, "low")
        neg_addr = _get_global_addr(global_ctx, cmpl_obj, "neg")
        self.assertEqual(
            cmpl_obj.memory[low_addr : low_addr + 16],
            bytes.fromhex("8877665544332211") + bytes(8),
        )
        self.assertEqual(cmpl_obj.memory[neg_addr : neg_addr + 16], bytes([0xFF]) * 16)

    def test_local_uint128_shift_and_add_round_trip_through_stack_storage(self):
        global_ctx, cmpl_obj = _compile_source(
            "unsigned __int128 g = 0; "
            "int main(int argc, char **argv) { "
            "    unsigned __int128 x = (unsigned __int128)1; "
            "    x = x << 64; "
            "    x = x + (unsigned __int128)3; "
            "    g = x; "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
        )
        self.assertIn(BC_INT128, cmpl_obj.memory)

        vm = _run_program(cmpl_obj)
        addr = _get_global_addr(global_ctx, cmpl_obj, "g")
        self.assertEqual(
            vm.memory[addr : addr + 16],
            (3).to_bytes(8, "little") + (1).to_bytes(8, "little"),
        )

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

    def test_flexible_array_member_uses_tail_offset_and_zero_size(self):
        global_ctx, _cmpl_obj = _compile_source(
            "struct packet { unsigned int length; unsigned char data[]; }; "
            "_Static_assert(sizeof(struct packet) == 4, \"packet size\"); "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
            default_alignment=8,
        )
        packet_type = global_ctx.type_name("packet")
        self.assertIsInstance(packet_type, StructType)
        assert isinstance(packet_type, StructType)
        self.assertEqual(size_of(packet_type), 4)
        self.assertEqual(packet_type.offset_of("data"), 4)
        self.assertEqual(packet_type.offset_of("data"), size_of(packet_type))

    def test_flexible_array_member_honors_padding_before_tail(self):
        global_ctx, _cmpl_obj = _compile_source(
            "struct padded_tail { unsigned char tag; unsigned int data[]; }; "
            "_Static_assert(sizeof(struct padded_tail) == 4, \"padded size\"); "
            "int main(int argc, char **argv) { return 0; }\n",
            remove_unused_deps=False,
            default_alignment=8,
        )
        padded_type = global_ctx.type_name("padded_tail")
        self.assertIsInstance(padded_type, StructType)
        assert isinstance(padded_type, StructType)
        self.assertEqual(size_of(padded_type), 4)
        self.assertEqual(padded_type.offset_of("data"), 4)

    def test_flexible_array_member_access_behaves_like_normal_array_member(self):
        global_ctx, cmpl_obj = _compile_source(
            "struct packet { unsigned int length; unsigned char data[]; }; "
            "struct packet_box { struct packet packet; unsigned char extra[3]; }; "
            "struct packet_box g; "
            "int main(int argc, char **argv) { "
            "    struct packet *p = &g.packet; "
            "    unsigned char *d = p->data; "
            "    p->length = 3; "
            "    p->data[0] = 0x11; "
            "    d[1] = 0x22; "
            "    p->data[2] = 0x33; "
            "    return 0; "
            "}\n",
            remove_unused_deps=False,
            default_alignment=8,
        )
        vm = _run_program(cmpl_obj)
        addr = _get_global_addr(global_ctx, cmpl_obj, "g")
        self.assertEqual(
            vm.memory[addr : addr + 7],
            bytes([3, 0, 0, 0, 0x11, 0x22, 0x33]),
        )

    def test_flexible_array_member_must_be_last_struct_member(self):
        with self.assertRaisesRegex(
            ValueError, "Flexible array member must be the last member of the struct"
        ):
            _compile_source(
                "struct broken { unsigned char data[]; unsigned int tail; }; "
                "int main(int argc, char **argv) { return 0; }\n",
                remove_unused_deps=False,
                default_alignment=8,
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
