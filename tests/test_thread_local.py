"""Tests for A4: thread-local storage (``_Thread_local`` / ``__thread``) and the
``restrict`` qualifier.

The TLS ABI is the static / local-exec model documented in
``StackVM/Documentation/ThreadLocalStorage.html``: thread-locals live in a
``.tdata`` template, the linker defines ``__tls_template_start`` / ``__tls_size``
/ ``__tls_align``, and a thread-local ``x`` is addressed at runtime as
``SVSR_TLS_BASE + (&x - __tls_template_start)``.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.Preprocessing import preprocess
from IsaacCompiler.StackVM.PyStackVM import (
    BCR_EA_R_IP,
    BCR_SYSREG,
    BCR_SZ_8,
    BC_CALL,
    BC_HLT,
    BC_LOAD,
    BC_RET,
    BC_STOR,
    SVSR_TLS_BASE,
    VM,
)
from IsaacCompiler.StackVM.runner import add_cmd_argv_vm
from IsaacCompiler.code_gen.Compilation import Compilation, INIT_GLOBALS_LINK_NAME
from IsaacCompiler.code_gen.LinkerOptions import LNK_RUN_STANDALONE, LinkerOptions
from IsaacCompiler.code_gen.compile_stmnt import compile_stmnt
from IsaacCompiler.code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const
from IsaacCompiler.code_gen.stackvm_binutils.linker import link_objects
from IsaacCompiler.code_gen.stackvm_binutils.object_file import (
    ObjectRelocation,
    ObjectSection,
    ObjectSegment,
    ObjectSymbol,
    RelocationType,
    SectionFlags,
    StackVMObject,
    SymbolBinding,
    SymbolFlags,
    SymbolType,
)
from IsaacCompiler.code_gen.tls import (
    TLS_ALIGN_SYMBOL,
    TLS_SECTION_NAME,
    TLS_SIZE_SYMBOL,
    TLS_TEMPLATE_END_SYMBOL,
    TLS_TEMPLATE_START_SYMBOL,
)
from IsaacCompiler.lexer.lexer import get_list_tokens
from IsaacCompiler.lib.runtime_support import runtime_extern_deps
from IsaacCompiler.parser.stmnt.get_stmnt import get_stmnt
from IsaacCompiler.parser.type.CompileContext import CompileContext


def _compile(source):
    """Compile + in-memory link a standalone program; return (ctx, compilation)."""
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None)
    link_opts = LinkerOptions(
        False, 4096, runtime_extern_deps, LNK_RUN_STANDALONE, None
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

    cmpl_obj.merge_all(link_opts, link_opts.extern_deps, None)
    assert cmpl_obj.link_all()
    return global_ctx, cmpl_obj


def _compile_object(source):
    """Compile a translation unit to a sectioned object for separate linking."""
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None)
    cmpl_obj = Compilation(False)

    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)

    return global_ctx, cmpl_obj.to_stackvm_object()


def _undefined_fn(name):
    return ObjectSymbol(
        name,
        0,
        0,
        ObjectSegment.CODE,
        SymbolBinding.GLOBAL,
        SymbolType.FUNCTION,
        SymbolFlags.UNDEFINED,
    )


def _startup_object():
    code = bytearray()
    emit_load_i_const(code, 1, True, 2)
    code.extend([BC_LOAD, BCR_EA_R_IP | BCR_SZ_8])
    relocation_offset = len(code)
    code.extend(b"\0" * 8)
    code.extend([BC_CALL, BC_HLT])
    return StackVMObject(
        bytes(code),
        b"",
        [_undefined_fn("main")],
        [
            ObjectRelocation(
                relocation_offset,
                0,
                ObjectSegment.CODE,
                RelocationType.PCREL8,
                section_index=0,
            )
        ],
        sections=[
            ObjectSection(
                ".text",
                0,
                len(code),
                1,
                ObjectSegment.CODE,
                SectionFlags.EXECUTABLE,
            )
        ],
    )


def _sym(cmpl_obj, name):
    return cmpl_obj.get_link(name).src


def _var_addr(global_ctx, cmpl_obj, name):
    return cmpl_obj.get_link(global_ctx.vars[name].get_link_name()).src


def _run(cmpl_obj, tls_base):
    vm = VM(65536)
    vm.load_program(cmpl_obj.memory, 0)
    vm.sys_regs[SVSR_TLS_BASE] = tls_base
    vm.push(4, 0)
    add_cmd_argv_vm(vm, len(cmpl_obj.memory), ["prog"])
    vm.execute()
    return vm


def _rd(vm, addr, size):
    return int.from_bytes(vm.memory[addr : addr + size], "little")


class ThreadLocalParsingTests(unittest.TestCase):
    def test_thread_local_marks_variable_and_section(self):
        global_ctx, _ = _compile(
            "_Thread_local int tls_var = 5;\n" "int main(void) { return 0; }\n"
        )
        var = global_ctx.vars["tls_var"]
        self.assertTrue(var.is_thread_local)
        self.assertEqual(var.section_name, TLS_SECTION_NAME)
        # Thread storage duration is never stack storage.
        self.assertFalse(var.uses_stack_storage())

    def test_gnu_thread_keyword_is_equivalent(self):
        global_ctx, _ = _compile(
            "__thread int gnu_tls;\n" "int main(void) { return 0; }\n"
        )
        self.assertTrue(global_ctx.vars["gnu_tls"].is_thread_local)
        self.assertEqual(global_ctx.vars["gnu_tls"].section_name, TLS_SECTION_NAME)

    def test_static_thread_local_combination(self):
        global_ctx, _ = _compile(
            "static _Thread_local int internal_tls = 3;\n"
            "int main(void) { return 0; }\n"
        )
        var = global_ctx.vars["internal_tls"]
        self.assertTrue(var.is_thread_local)
        # internal linkage (static) but still thread storage duration
        self.assertFalse(var.has_external_linkage())
        self.assertFalse(var.uses_stack_storage())

    def test_ordinary_global_is_not_thread_local(self):
        global_ctx, _ = _compile(
            "int ordinary = 1;\n" "int main(void) { return 0; }\n"
        )
        self.assertFalse(global_ctx.vars["ordinary"].is_thread_local)
        self.assertNotEqual(
            global_ctx.vars["ordinary"].section_name, TLS_SECTION_NAME
        )


class ThreadLocalLayoutTests(unittest.TestCase):
    def test_linker_defines_template_symbols(self):
        _ctx, cmpl_obj = _compile(
            "_Thread_local int a = 1;\n"
            "int main(void) { return 0; }\n"
        )
        start = _sym(cmpl_obj, TLS_TEMPLATE_START_SYMBOL)
        end = _sym(cmpl_obj, TLS_TEMPLATE_END_SYMBOL)
        size = _sym(cmpl_obj, TLS_SIZE_SYMBOL)
        align = _sym(cmpl_obj, TLS_ALIGN_SYMBOL)
        self.assertIsNotNone(start)
        self.assertEqual(end - start, size)
        self.assertEqual(size, 4)  # one int
        self.assertGreaterEqual(align, 1)

    def test_distinct_variables_get_distinct_nonoverlapping_offsets(self):
        global_ctx, cmpl_obj = _compile(
            "_Thread_local int a = 1;\n"
            "_Thread_local int b = 2;\n"
            "_Thread_local int c = 3;\n"
            "int main(void) { return 0; }\n"
        )
        start = _sym(cmpl_obj, TLS_TEMPLATE_START_SYMBOL)
        size = _sym(cmpl_obj, TLS_SIZE_SYMBOL)
        offsets = sorted(
            _var_addr(global_ctx, cmpl_obj, n) - start for n in ("a", "b", "c")
        )
        self.assertEqual(len(set(offsets)), 3)
        for off in offsets:
            self.assertGreaterEqual(off, 0)
            self.assertLess(off, size)
        # No two 4-byte ints overlap.
        self.assertGreaterEqual(offsets[1] - offsets[0], 4)
        self.assertGreaterEqual(offsets[2] - offsets[1], 4)

    def test_initializer_lands_in_template_image(self):
        global_ctx, cmpl_obj = _compile(
            "_Thread_local int seeded = 0x1234;\n"
            "int main(void) { return 0; }\n"
        )
        addr = _var_addr(global_ctx, cmpl_obj, "seeded")
        self.assertEqual(
            int.from_bytes(cmpl_obj.memory[addr : addr + 4], "little"), 0x1234
        )

    def test_codegen_emits_tls_base_register_read(self):
        _ctx, cmpl_obj = _compile(
            "_Thread_local int t = 7;\n"
            "int read_t(void) { return t; }\n"
            "int main(void) { return 0; }\n"
        )
        self.assertIn(
            bytes([BC_LOAD, BCR_SYSREG | BCR_SZ_8, SVSR_TLS_BASE]),
            bytes(cmpl_obj.memory),
        )

    def test_separate_linker_places_tdata_and_defines_tls_symbols(self):
        global_ctx, obj = _compile_object(
            "_Thread_local int tls_counter = 7;\n"
            "int observed = 0;\n"
            "int main(void) {\n"
            "    tls_counter = tls_counter + 5;\n"
            "    observed = tls_counter;\n"
            "    return 0;\n"
            "}\n"
        )
        tls_symbol = next(symbol for symbol in obj.symbols if symbol.name == "tls_counter")
        self.assertEqual(obj.sections[tls_symbol.section_index].name, TLS_SECTION_NAME)

        result = link_objects([("start.sbo", _startup_object()), ("unit.sbo", obj)])
        sections = {section.name: section for section in result.section_layouts}
        self.assertEqual(
            result.global_symbols[TLS_TEMPLATE_START_SYMBOL],
            sections[TLS_SECTION_NAME].address,
        )
        self.assertEqual(result.global_symbols[TLS_SIZE_SYMBOL], 4)
        self.assertGreaterEqual(result.global_symbols[TLS_ALIGN_SYMBOL], 1)
        self.assertEqual(
            result.global_symbols[TLS_TEMPLATE_END_SYMBOL]
            - result.global_symbols[TLS_TEMPLATE_START_SYMBOL],
            result.global_symbols[TLS_SIZE_SYMBOL],
        )

        vm = VM(65536)
        vm.load_program(result.memory, 0)
        vm.sys_regs[SVSR_TLS_BASE] = result.global_symbols[TLS_TEMPLATE_START_SYMBOL]
        vm.push(4, 0)
        add_cmd_argv_vm(vm, len(result.memory), ["prog"])
        vm.execute()

        observed_addr = result.global_symbols["observed"]
        tls_addr = result.global_symbols["tls_counter"]
        self.assertEqual(_rd(vm, observed_addr, 4), 12)
        self.assertEqual(_rd(vm, tls_addr, 4), 12)


class ThreadLocalRuntimeTests(unittest.TestCase):
    SRC = (
        "_Thread_local int tls_counter = 100;\n"
        "int observed = 0;\n"
        "int main(void) {\n"
        "    tls_counter = tls_counter + 5;\n"
        "    observed = tls_counter;\n"
        "    return 0;\n"
        "}\n"
    )

    def test_access_is_relative_to_thread_pointer(self):
        global_ctx, cmpl_obj = _compile(self.SRC)
        start = _sym(cmpl_obj, TLS_TEMPLATE_START_SYMBOL)
        var_addr = _var_addr(global_ctx, cmpl_obj, "tls_counter")

        # TLS_BASE = template start => operate directly on the template image.
        vm = _run(cmpl_obj, start)
        self.assertEqual(_rd(vm, _var_addr(global_ctx, cmpl_obj, "observed"), 4), 105)
        self.assertEqual(_rd(vm, var_addr, 4), 105)

    def test_threads_have_independent_storage(self):
        global_ctx, cmpl_obj = _compile(self.SRC)
        start = _sym(cmpl_obj, TLS_TEMPLATE_START_SYMBOL)
        size = _sym(cmpl_obj, TLS_SIZE_SYMBOL)
        var_addr = _var_addr(global_ctx, cmpl_obj, "tls_counter")
        offset = var_addr - start

        # A separate, zero-initialised scratch block stands in for a second
        # thread's TLS block.  0xF000 is clear of the small program image (near
        # 0) and the stack (near the top of memory).
        scratch = 0xF000
        vm = _run(cmpl_obj, scratch)

        # The counter started from the scratch block's (zero) contents, not the
        # template's 100, proving storage is genuinely TLS_BASE-relative...
        self.assertEqual(_rd(vm, _var_addr(global_ctx, cmpl_obj, "observed"), 4), 5)
        self.assertEqual(_rd(vm, scratch + offset, 4), 5)
        # ...and the template (the init image) is left untouched.
        self.assertEqual(_rd(vm, var_addr, 4), 100)
        self.assertEqual(size, 4)

    def test_struct_members_and_array_elements(self):
        global_ctx, cmpl_obj = _compile(
            "struct Pt { int x; int y; };\n"
            "_Thread_local struct Pt pt = {7, 8};\n"
            "_Thread_local int arr[4];\n"
            "int out_x = 0, out_y = 0, out_arr = 0;\n"
            "int main(void) {\n"
            "    pt.x = pt.x + 1;\n"
            "    pt.y = pt.y + 10;\n"
            "    arr[2] = 9;\n"
            "    out_x = pt.x; out_y = pt.y; out_arr = arr[2];\n"
            "    return 0;\n"
            "}\n"
        )
        start = _sym(cmpl_obj, TLS_TEMPLATE_START_SYMBOL)
        vm = _run(cmpl_obj, start)
        self.assertEqual(_rd(vm, _var_addr(global_ctx, cmpl_obj, "out_x"), 4), 8)
        self.assertEqual(_rd(vm, _var_addr(global_ctx, cmpl_obj, "out_y"), 4), 18)
        self.assertEqual(_rd(vm, _var_addr(global_ctx, cmpl_obj, "out_arr"), 4), 9)

    def test_tls_and_ordinary_globals_coexist(self):
        global_ctx, cmpl_obj = _compile(
            "int plain = 1000;\n"
            "_Thread_local int tls = 1;\n"
            "int out_plain = 0, out_tls = 0;\n"
            "int main(void) {\n"
            "    plain = plain + 1;\n"
            "    tls = tls + 1;\n"
            "    out_plain = plain; out_tls = tls;\n"
            "    return 0;\n"
            "}\n"
        )
        start = _sym(cmpl_obj, TLS_TEMPLATE_START_SYMBOL)
        vm = _run(cmpl_obj, start)
        self.assertEqual(_rd(vm, _var_addr(global_ctx, cmpl_obj, "out_plain"), 4), 1001)
        self.assertEqual(_rd(vm, _var_addr(global_ctx, cmpl_obj, "out_tls"), 4), 2)
        # The ordinary global is NOT placed in the TLS template.
        plain_addr = _var_addr(global_ctx, cmpl_obj, "plain")
        end = _sym(cmpl_obj, TLS_TEMPLATE_END_SYMBOL)
        self.assertFalse(start <= plain_addr < end)


class TlsBaseRegisterTests(unittest.TestCase):
    def test_tls_base_register_round_trips(self):
        program = bytearray()
        emit_load_i_const(program, 0xCAFE, False, 3)
        program.extend([BC_STOR, BCR_SYSREG | BCR_SZ_8, SVSR_TLS_BASE])
        program.extend([BC_LOAD, BCR_SYSREG | BCR_SZ_8, SVSR_TLS_BASE, BC_HLT])
        vm = VM(1024)
        vm.load_program(program, 0)
        vm.execute()
        self.assertEqual(vm.pop(8), 0xCAFE)


class RestrictQualifierTests(unittest.TestCase):
    def test_restrict_spellings_parse_and_run(self):
        global_ctx, cmpl_obj = _compile(
            "int dst = 0;\n"
            "int copy(int * restrict to, const int * __restrict from) {\n"
            "    *to = *from; return *to;\n"
            "}\n"
            "int out = 0;\n"
            "int main(void) {\n"
            "    int src = 77;\n"
            "    int * __restrict__ p = &dst;\n"
            "    out = copy(p, &src);\n"
            "    return 0;\n"
            "}\n"
        )
        vm = _run(cmpl_obj, 0)
        self.assertEqual(_rd(vm, _var_addr(global_ctx, cmpl_obj, "dst"), 4), 77)
        self.assertEqual(_rd(vm, _var_addr(global_ctx, cmpl_obj, "out"), 4), 77)

    def test_restrict_does_not_change_pointed_to_type(self):
        # restrict is a no-op qualifier: a restrict-qualified pointer is still a
        # plain pointer for assignment/dereference purposes.
        global_ctx, cmpl_obj = _compile(
            "int store = 0;\n"
            "int main(void) {\n"
            "    int v = 42;\n"
            "    int * restrict rp = &v;\n"
            "    store = *rp;\n"
            "    return 0;\n"
            "}\n"
        )
        vm = _run(cmpl_obj, 0)
        self.assertEqual(_rd(vm, _var_addr(global_ctx, cmpl_obj, "store"), 4), 42)


if __name__ == "__main__":
    unittest.main()
