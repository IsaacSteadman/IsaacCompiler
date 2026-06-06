"""Tests for the standalone StackVM assembler (``svm-as`` / the ``as`` subcommand).

Coverage:
  * :class:`ObjectAssemblerUnitTests` -- symbol bindings, undefined-symbol
    relocations and the same-section local-label optimisation.
  * :class:`AssemblerDirectiveTests` -- section/data/alignment directives.
  * :class:`AssemblerLinkRunTests` -- link the produced objects and run them on
    the StackVM, proving ABS8/PCREL8 + local/external relocations execute.
  * :class:`SvmAsCliTests` -- the ``python -m IsaacCompiler as`` front end,
    including ``.S`` preprocessing and ``.s`` (no preprocessing).
  * :class:`GccDriverAsmTests` -- the gcc driver routing ``.S`` / ``.s`` inputs.
"""

import os
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.PyStackVM import VM
from IsaacCompiler.StackVM.runner import load_sbc
from IsaacCompiler.code_gen.stackvm_binutils.linker import link_objects
from IsaacCompiler.code_gen.stackvm_binutils.object_file import (
    ObjectSegment,
    RelocationType,
    SectionFlags,
    SymbolBinding,
    SymbolFlags,
    SymbolType,
    dumps_sbo,
    load_sbo,
    loads_sbo,
    validate_object,
)
from IsaacCompiler.code_gen.stackvm_binutils.svm_as import (
    AssemblerError,
    ObjectAssembler,
    assemble_object,
)


def _sym(obj, name):
    return next(s for s in obj.symbols if s.name == name)


def _section(obj, name):
    return next(s for s in obj.sections if s.name == name)


def _run_image(result):
    vm = VM(65536)
    vm.load_program(bytearray(result.memory), 0)
    vm.execute()
    return vm


# ---------------------------------------------------------------------------
# Unit tests: symbols and relocations
# ---------------------------------------------------------------------------
class ObjectAssemblerUnitTests(unittest.TestCase):
    def test_global_function_symbol(self):
        obj = assemble_object(".text\n.globl f\n:f\nRET\n")
        validate_object(obj)
        sym = _sym(obj, "f")
        self.assertEqual(sym.binding, SymbolBinding.GLOBAL)
        self.assertEqual(sym.typ, SymbolType.FUNCTION)
        self.assertEqual(sym.segment, ObjectSegment.CODE)
        self.assertEqual(sym.flags, SymbolFlags.NONE)
        self.assertIsNotNone(sym.section_index)
        # Survives serialization.
        reloaded = loads_sbo(dumps_sbo(obj))
        self.assertIn("f", {s.name for s in reloaded.symbols})

    def test_label_default_binding_is_local(self):
        obj = assemble_object(".text\n:helper\nRET\n")
        self.assertEqual(_sym(obj, "helper").binding, SymbolBinding.LOCAL)

    def test_weak_binding(self):
        obj = assemble_object(".text\n.weak w\n:w\nRET\n")
        self.assertEqual(_sym(obj, "w").binding, SymbolBinding.WEAK)

    def test_backward_local_label_is_resolved_in_place(self):
        # Backward branch to a same-section label: no relocation is emitted.
        obj = assemble_object(
            ".text\n:start\n8d0\n:loop\n8d1\nlRr[1]*:loop\nRJMP\nHLT\n"
        )
        self.assertEqual(obj.relocations, [])

    def test_forward_local_label_emits_relocation(self):
        obj = assemble_object(
            ".text\n:start\nlRr[1]*:done\nRJMP\n8d5\n:done\nHLT\n"
        )
        self.assertEqual(len(obj.relocations), 1)
        reloc = obj.relocations[0]
        self.assertEqual(reloc.typ, RelocationType.PCREL8)
        self.assertEqual(obj.symbols[reloc.symbol_index].name, "done")
        # 'done' is a defined LOCAL symbol the linker resolves.
        self.assertEqual(obj.symbols[reloc.symbol_index].binding, SymbolBinding.LOCAL)
        self.assertEqual(obj.symbols[reloc.symbol_index].flags, SymbolFlags.NONE)

    def test_undefined_external_reference(self):
        obj = assemble_object(".text\n:f\ngRa*ext_fn\nRET\n")
        validate_object(obj)
        sym = _sym(obj, "ext_fn")
        self.assertEqual(sym.flags, SymbolFlags.UNDEFINED)
        self.assertEqual(sym.value, 0)
        self.assertEqual(sym.size, 0)
        self.assertIsNone(sym.section_index)
        self.assertEqual(sym.binding, SymbolBinding.GLOBAL)
        self.assertEqual(len(obj.relocations), 1)
        reloc = obj.relocations[0]
        self.assertEqual(reloc.typ, RelocationType.PCREL8)
        self.assertEqual(reloc.segment, ObjectSegment.CODE)
        # The addend (0) was written into the 8-byte patch field.
        self.assertEqual(obj.code[reloc.offset : reloc.offset + 8], bytes(8))

    def test_quad_symbol_in_data_emits_abs8_relocation(self):
        obj = assemble_object(".data\n.globl ptr\n:ptr\n.quad target\n")
        validate_object(obj)
        self.assertEqual(_sym(obj, "target").flags, SymbolFlags.UNDEFINED)
        self.assertEqual(len(obj.relocations), 1)
        reloc = obj.relocations[0]
        self.assertEqual(reloc.typ, RelocationType.ABS8)
        self.assertEqual(reloc.segment, ObjectSegment.DATA)
        self.assertEqual(obj.symbols[reloc.symbol_index].name, "target")

    def test_duplicate_definition_rejected(self):
        with self.assertRaises(AssemblerError):
            assemble_object(".text\n:f\nRET\n:f\nRET\n")

    def test_unsupported_section_rejected(self):
        with self.assertRaises(AssemblerError):
            assemble_object(".section .totally_unknown\nRET\n")


# ---------------------------------------------------------------------------
# Unit tests: directives
# ---------------------------------------------------------------------------
class AssemblerDirectiveTests(unittest.TestCase):
    def test_fixed_width_data(self):
        obj = assemble_object(
            ".data\n.byte 1, 2\n.short 0x0304\n.long 0x05060708\n"
            ".quad 0x0102030405060708\n"
        )
        expected = (
            bytes([1, 2])
            + (0x0304).to_bytes(2, "little")
            + (0x05060708).to_bytes(4, "little")
            + (0x0102030405060708).to_bytes(8, "little")
        )
        self.assertEqual(obj.data, expected)

    def test_string_directives(self):
        obj = assemble_object('.data\n.ascii "ab"\n.asciz "cd"\n')
        self.assertEqual(obj.data, b"abcd\x00")

    def test_rodata_is_read_only(self):
        obj = assemble_object(".rodata\n.globl s\n:s\n.asciz \"x\"\n")
        section = _section(obj, ".rodata")
        self.assertTrue(section.flags & SectionFlags.READ_ONLY)
        self.assertEqual(section.segment, ObjectSegment.DATA)

    def test_bss_is_nobits_and_contributes_no_file_bytes(self):
        obj = assemble_object(".bss\n.globl buf\n:buf\n.skip 16\n")
        section = _section(obj, ".bss")
        self.assertTrue(section.flags & SectionFlags.NOBITS)
        self.assertEqual(section.size, 16)
        # NOBITS contributes size but no bytes to the DATA blob.
        self.assertEqual(obj.data, b"")

    def test_bss_rejects_initialized_data(self):
        with self.assertRaises(AssemblerError):
            assemble_object(".bss\n.byte 1\n")

    def test_align_pads_and_records_alignment(self):
        obj = assemble_object(".data\n.byte 1\n.align 8\n.byte 2\n")
        # 0x01, seven pad bytes, 0x02.
        self.assertEqual(obj.data, bytes([1]) + bytes(7) + bytes([2]))
        self.assertEqual(_section(obj, ".data").alignment, 8)

    def test_p2align(self):
        obj = assemble_object(".data\n.byte 1\n.p2align 3\n.byte 2\n")
        self.assertEqual(obj.data, bytes([1]) + bytes(7) + bytes([2]))

    def test_comm_reserves_bss_object(self):
        obj = assemble_object(".comm shared, 32, 8\n")
        sym = _sym(obj, "shared")
        self.assertEqual(sym.binding, SymbolBinding.GLOBAL)
        self.assertEqual(sym.typ, SymbolType.OBJECT)
        self.assertEqual(sym.size, 32)
        bss = _section(obj, ".bss")
        self.assertTrue(bss.flags & SectionFlags.NOBITS)
        self.assertEqual(bss.alignment, 8)
        self.assertGreaterEqual(bss.size, 32)

    def test_set_constant_used_in_data(self):
        obj = assemble_object(".set K, 5\n.data\n.quad K\n")
        self.assertEqual(obj.data, (5).to_bytes(8, "little"))


# ---------------------------------------------------------------------------
# End-to-end: link the assembled objects and execute on the StackVM
# ---------------------------------------------------------------------------
class AssemblerLinkRunTests(unittest.TestCase):
    def test_single_object_store_executes(self):
        obj = assemble_object(
            ".text\n:entry\n8d42\ngRa*result\nSTOR-ABS_S8|SZ_8\nHLT\n"
            ".data\n.globl result\n:result\n.quad 0\n"
        )
        result = link_objects([("a.sbo", obj)])
        vm = _run_image(result)
        self.assertEqual(vm.get(8, result.global_symbols["result"]), 42)

    def test_cross_object_external_symbol(self):
        a = assemble_object(
            ".text\n:entry\n"
            "gRa*answer\nLOAD-ABS_S8|SZ_8\n"  # value of external 'answer'
            "gRa*result\nSTOR-ABS_S8|SZ_8\n"
            "HLT\n"
            ".data\n.globl result\n:result\n.quad 0\n"
        )
        b = assemble_object(".data\n.globl answer\n:answer\n.quad 1234\n")
        result = link_objects([("a.sbo", a), ("b.sbo", b)])
        vm = _run_image(result)
        self.assertEqual(vm.get(8, result.global_symbols["result"]), 1234)

    def test_forward_branch_skips_dead_code(self):
        obj = assemble_object(
            ".text\n:entry\n"
            "lRr[1]*:skip\nRJMP\n"
            "8d999\ngRa*result\nSTOR-ABS_S8|SZ_8\n"  # skipped poison
            ":skip\n8d7\ngRa*result\nSTOR-ABS_S8|SZ_8\nHLT\n"
            ".data\n.globl result\n:result\n.quad 0\n"
        )
        result = link_objects([("a.sbo", obj)])
        vm = _run_image(result)
        self.assertEqual(vm.get(8, result.global_symbols["result"]), 7)

    def test_backward_loop_executes(self):
        # r += 1 while n-- != 0, starting n = 3 -> r ends at 3.
        obj = assemble_object(
            ".text\n:entry\n:loop\n"
            "gRa*r\nLOAD-ABS_S8|SZ_8\n8d1\nADD8\ngRa*r\nSTOR-ABS_S8|SZ_8\n"
            "gRa*n\nLOAD-ABS_S8|SZ_8\n8d1\nSUB8\ngRa*n\nSTOR-ABS_S8|SZ_8\n"
            "gRa*n\nLOAD-ABS_S8|SZ_8\nNE0\nlRr[1]*:loop\nRJMPIF\nHLT\n"
            ".data\n.globl r\n:r\n.quad 0\n.globl n\n:n\n.quad 3\n"
        )
        result = link_objects([("a.sbo", obj)])
        vm = _run_image(result)
        self.assertEqual(vm.get(8, result.global_symbols["r"]), 3)
        self.assertEqual(vm.get(8, result.global_symbols["n"]), 0)


# ---------------------------------------------------------------------------
# CLI: the ``as`` subcommand
# ---------------------------------------------------------------------------
def _run_cli(args, cwd=None):
    proc = subprocess.run(
        [sys.executable, "-m", "IsaacCompiler"] + list(args),
        cwd=REPO_PARENT if cwd is None else cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": REPO_PARENT},
    )
    return proc


def _msg(proc):
    return "stdout:\n%s\nstderr:\n%s" % (proc.stdout, proc.stderr)


class SvmAsCliTests(unittest.TestCase):
    def test_as_assembles_lowercase_s(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "ctx.s")
            obj = os.path.join(tmp, "ctx.sbo")
            with open(src, "w") as fl:
                fl.write("# a raw comment\n.text\n.globl ctx\n:ctx\nRET\n")
            proc = _run_cli(["as", "-o", obj, src])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertIn("ctx", {s.name for s in load_sbo(obj).symbols})

    def test_dot_S_is_preprocessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            header = os.path.join(tmp, "vals.h")
            with open(header, "w") as fl:
                fl.write("#define BASE 1000\n")
            src = os.path.join(tmp, "boot.S")
            obj = os.path.join(tmp, "boot.sbo")
            with open(src, "w") as fl:
                fl.write(
                    '#include "vals.h"\n'
                    "#define EXTRA 7\n"
                    ".data\n.globl table\n:table\n.quad BASE\n.quad EXTRA\n"
                )
            proc = _run_cli(["as", "-I", tmp, "-o", obj, src])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            data = load_sbo(obj).data
            self.assertEqual(data[0:8], (1000).to_bytes(8, "little"))
            self.assertEqual(data[8:16], (7).to_bytes(8, "little"))

    def test_assembler_macro_is_defined_for_dot_S(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "guard.S")
            obj = os.path.join(tmp, "guard.sbo")
            with open(src, "w") as fl:
                fl.write(
                    "#ifdef __ASSEMBLER__\n#define V 5\n#else\n#define V 9\n#endif\n"
                    ".data\n.globl v\n:v\n.quad V\n"
                )
            proc = _run_cli(["as", "-o", obj, src])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertEqual(load_sbo(obj).data[0:8], (5).to_bytes(8, "little"))

    def test_dot_s_is_not_preprocessed(self):
        # A '#define'-looking line in a .s file is an assembly comment, not a
        # preprocessor directive, so it must not change the output.
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "raw.s")
            obj = os.path.join(tmp, "raw.sbo")
            with open(src, "w") as fl:
                fl.write("#define V 5\n.data\n.globl v\n:v\n.quad 3\n")
            proc = _run_cli(["as", "-o", obj, src])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertEqual(load_sbo(obj).data[0:8], (3).to_bytes(8, "little"))

    def test_defsym_defines_assembler_constant(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "d.s")
            obj = os.path.join(tmp, "d.sbo")
            with open(src, "w") as fl:
                fl.write(".data\n.quad K\n")
            proc = _run_cli(["as", "--defsym", "K=9", "-o", obj, src])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertEqual(load_sbo(obj).data[0:8], (9).to_bytes(8, "little"))

    def test_multiple_inputs_concatenate_into_one_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.s")
            b = os.path.join(tmp, "b.s")
            obj = os.path.join(tmp, "out.sbo")
            with open(a, "w") as fl:
                fl.write(".text\n.globl fa\n:fa\nRET\n")
            with open(b, "w") as fl:
                fl.write(".text\n.globl fb\n:fb\nRET\n")
            proc = _run_cli(["as", "-o", obj, a, b])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            names = {s.name for s in load_sbo(obj).symbols}
            self.assertIn("fa", names)
            self.assertIn("fb", names)

    def test_no_input_files_is_an_error(self):
        proc = _run_cli(["as"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no input files", proc.stderr)


# ---------------------------------------------------------------------------
# gcc driver routing of .S / .s inputs
# ---------------------------------------------------------------------------
class GccDriverAsmTests(unittest.TestCase):
    def test_compile_only_dot_S(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.S")
            obj = os.path.join(tmp, "u.sbo")
            with open(src, "w") as fl:
                fl.write("#define N 42\n.data\n.globl val\n:val\n.quad N\n")
            proc = _run_cli(["-c", src, "-o", obj])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            loaded = load_sbo(obj)
            self.assertIn("val", {s.name for s in loaded.symbols})
            self.assertEqual(loaded.data[0:8], (42).to_bytes(8, "little"))

    def test_compile_only_dot_s_lowercase(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "u.s")
            obj = os.path.join(tmp, "u.sbo")
            with open(src, "w") as fl:
                fl.write(".text\n.globl f\n:f\nRET\n")
            proc = _run_cli(["-c", src, "-o", obj])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            self.assertIn("f", {s.name for s in load_sbo(obj).symbols})

    def test_mixed_assembly_link_runs_on_vm(self):
        # Two assembly translation units linked through the gcc driver; the
        # linked image is loaded and executed on the StackVM.
        with tempfile.TemporaryDirectory() as tmp:
            prog = os.path.join(tmp, "prog.S")
            data = os.path.join(tmp, "data.s")
            out = os.path.join(tmp, "prog.out")
            with open(prog, "w") as fl:
                # 'result' is the first .data byte -> address == data_segment_start.
                fl.write(
                    ".data\n.globl result\n:result\n.quad 0\n"
                    ".text\n:entry\n"
                    "gRa*answer\nLOAD-ABS_S8|SZ_8\n"
                    "gRa*result\nSTOR-ABS_S8|SZ_8\nHLT\n"
                )
            with open(data, "w") as fl:
                fl.write(".data\n.globl answer\n:answer\n.quad 1234\n")
            proc = _run_cli([prog, data, "-o", out])
            self.assertEqual(proc.returncode, 0, msg=_msg(proc))
            memory, _code_end, data_start = load_sbc(out)
            vm = VM(65536)
            vm.load_program(bytearray(memory), 0)
            vm.execute()
            self.assertEqual(vm.get(8, data_start), 1234)


if __name__ == "__main__":
    unittest.main()
