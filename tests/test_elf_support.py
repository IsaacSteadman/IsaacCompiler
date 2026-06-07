import os
import struct
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.code_gen.stackvm_binutils.debug_info import (
    DEBUG_SECTION_NAME,
    DebugFunctionRecord,
    DebugLineRecord,
    StackVMDebugInfo,
    dumps_debug,
)
from IsaacCompiler.code_gen.stackvm_binutils.elf_file import (
    ELF_MAGIC,
    EM_STACKVM,
    ET_EXEC,
    ET_REL,
    R_STACKVM_64,
    R_STACKVM_PC64,
    dumps_elf_object,
    load_elf_object,
    loads_elf_executable,
    loads_elf_object,
    write_elf_object,
)
from IsaacCompiler.code_gen.stackvm_binutils.linker import link_files, link_objects
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
from IsaacCompiler.code_gen.stackvm_binutils.svm_as import assemble_object


def _patch(value=0):
    return (value & ((1 << 64) - 1)).to_bytes(8, "little")


def _elf_type_machine(blob):
    _ident, e_type, e_machine = struct.unpack_from("<16sHH", blob, 0)
    return e_type, e_machine


def _sym(obj, name):
    return next(symbol for symbol in obj.symbols if symbol.name == name)


def _section(obj, name):
    return next(section for section in obj.sections if section.name == name)


class ElfSupportTests(unittest.TestCase):
    def test_relocatable_object_elf_round_trip(self):
        obj = StackVMObject(
            _patch(-5),
            _patch(11),
            [
                ObjectSymbol(
                    "func",
                    0,
                    8,
                    ObjectSegment.CODE,
                    SymbolBinding.GLOBAL,
                    SymbolType.FUNCTION,
                    section_index=0,
                ),
                ObjectSymbol(
                    "data",
                    0,
                    8,
                    ObjectSegment.DATA,
                    SymbolBinding.LOCAL,
                    SymbolType.OBJECT,
                    section_index=1,
                ),
                ObjectSymbol(
                    "zero",
                    8,
                    16,
                    ObjectSegment.DATA,
                    SymbolBinding.WEAK,
                    SymbolType.OBJECT,
                    section_index=2,
                ),
                ObjectSymbol(
                    "external",
                    0,
                    0,
                    ObjectSegment.DATA,
                    SymbolBinding.GLOBAL,
                    SymbolType.OBJECT,
                    SymbolFlags.UNDEFINED,
                ),
            ],
            [
                ObjectRelocation(
                    0,
                    3,
                    ObjectSegment.CODE,
                    RelocationType.PCREL8,
                    section_index=0,
                ),
                ObjectRelocation(
                    0,
                    0,
                    ObjectSegment.DATA,
                    RelocationType.ABS8,
                    section_index=1,
                ),
            ],
            default_alignment=8,
            data_alignment=16,
            sections=[
                ObjectSection(
                    ".text",
                    0,
                    8,
                    4,
                    ObjectSegment.CODE,
                    SectionFlags.EXECUTABLE,
                ),
                ObjectSection(".data", 0, 8, 8, ObjectSegment.DATA),
                ObjectSection(
                    ".bss",
                    8,
                    16,
                    16,
                    ObjectSegment.DATA,
                    SectionFlags.NOBITS,
                ),
            ],
        )

        blob = dumps_elf_object(obj)
        self.assertEqual(blob[:4], ELF_MAGIC)
        self.assertEqual(_elf_type_machine(blob), (ET_REL, EM_STACKVM))
        self.assertIn(R_STACKVM_PC64.to_bytes(1, "little"), blob)
        self.assertIn(R_STACKVM_64.to_bytes(1, "little"), blob)

        loaded = loads_elf_object(blob)
        self.assertEqual(loaded.default_alignment, 8)
        self.assertEqual(loaded.data_alignment, 16)
        self.assertTrue(_section(loaded, ".bss").flags & SectionFlags.NOBITS)
        self.assertEqual(_sym(loaded, "external").segment, ObjectSegment.DATA)
        self.assertTrue(_sym(loaded, "external").is_undefined)

        reloc_by_type = {rel.typ: rel for rel in loaded.relocations}
        self.assertEqual(
            int.from_bytes(loaded.code[0:8], "little", signed=True),
            -5,
        )
        self.assertEqual(
            loaded.symbols[reloc_by_type[RelocationType.PCREL8].symbol_index].name,
            "external",
        )
        self.assertEqual(int.from_bytes(loaded.data[0:8], "little"), 11)
        self.assertEqual(
            loaded.symbols[reloc_by_type[RelocationType.ABS8].symbol_index].name,
            "func",
        )

    def test_assembler_cli_emits_elf_for_dot_o(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "ctx.s")
            output_path = os.path.join(tmpdir, "ctx.o")
            with open(source_path, "w") as fl:
                fl.write(".text\n.globl ctx\n:ctx\nRET\n")

            proc = subprocess.run(
                [sys.executable, "-m", "IsaacCompiler", "as", "-o", output_path, source_path],
                cwd=REPO_PARENT,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": REPO_PARENT},
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            with open(output_path, "rb") as fl:
                blob = fl.read()
            self.assertEqual(blob[:4], ELF_MAGIC)
            self.assertIn("ctx", {symbol.name for symbol in loads_elf_object(blob).symbols})

    def test_gcc_driver_compile_only_emits_elf_for_dot_o(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "unit.c")
            output_path = os.path.join(tmpdir, "unit.o")
            with open(source_path, "w") as fl:
                fl.write("int exported(void) { return 7; }\n")

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "IsaacCompiler",
                    "-c",
                    "-o",
                    output_path,
                    source_path,
                ],
                cwd=REPO_PARENT,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": REPO_PARENT},
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            obj = load_elf_object(output_path)
            self.assertIn("exported", {symbol.name for symbol in obj.symbols})

    def test_linker_reads_elf_objects_and_writes_vmlinux_elf(self):
        caller = StackVMObject(
            _patch(2),
            _patch(3),
            [
                ObjectSymbol(
                    "target_fn",
                    0,
                    0,
                    ObjectSegment.CODE,
                    SymbolBinding.GLOBAL,
                    SymbolType.FUNCTION,
                    SymbolFlags.UNDEFINED,
                ),
                ObjectSymbol(
                    "target_data",
                    0,
                    0,
                    ObjectSegment.DATA,
                    SymbolBinding.GLOBAL,
                    SymbolType.OBJECT,
                    SymbolFlags.UNDEFINED,
                ),
            ],
            [
                ObjectRelocation(0, 0, ObjectSegment.CODE, RelocationType.PCREL8),
                ObjectRelocation(0, 1, ObjectSegment.DATA, RelocationType.ABS8),
            ],
            data_alignment=16,
        )
        definitions = StackVMObject(
            b"\xAA" * 4,
            b"\xBB" * 4,
            [
                ObjectSymbol(
                    "target_fn",
                    0,
                    4,
                    ObjectSegment.CODE,
                    SymbolBinding.GLOBAL,
                    SymbolType.FUNCTION,
                ),
                ObjectSymbol(
                    "target_data",
                    0,
                    4,
                    ObjectSegment.DATA,
                    SymbolBinding.GLOBAL,
                    SymbolType.OBJECT,
                ),
            ],
            data_alignment=16,
        )

        expected = link_objects([("caller.o", caller), ("defs.o", definitions)])
        with tempfile.TemporaryDirectory() as tmpdir:
            caller_path = os.path.join(tmpdir, "caller.o")
            defs_path = os.path.join(tmpdir, "defs.o")
            output_path = os.path.join(tmpdir, "vmlinux")
            write_elf_object(caller, caller_path)
            write_elf_object(definitions, defs_path)

            result = link_files([caller_path, defs_path], output_path)
            self.assertEqual(result.memory, expected.memory)
            self.assertEqual(result.base_relocations, expected.base_relocations)

            with open(output_path, "rb") as fl:
                blob = fl.read()
            self.assertEqual(blob[:4], ELF_MAGIC)
            self.assertEqual(_elf_type_machine(blob), (ET_EXEC, EM_STACKVM))
            executable = loads_elf_executable(blob)
            self.assertEqual(executable.memory, expected.memory)
            self.assertEqual(executable.code_segment_end, expected.code_segment_end)
            self.assertEqual(executable.data_segment_start, expected.data_segment_start)
            self.assertEqual(executable.base_relocations, tuple(expected.base_relocations))
            self.assertEqual(
                int.from_bytes(
                    executable.memory[
                        expected.data_segment_start : expected.data_segment_start + 8
                    ],
                    "little",
                ),
                expected.global_symbols["target_data"] + 3,
            )

            loaded_caller = load_elf_object(caller_path)
            self.assertEqual(
                {symbol.name for symbol in loaded_caller.symbols},
                {"target_fn", "target_data"},
            )

    def test_linked_elf_carries_stackvm_debug_payload(self):
        debug_payload = dumps_debug(
            StackVMDebugInfo(
                [DebugLineRecord(0, "kernel.c", 12, 4, ".text")],
                [DebugFunctionRecord("start_kernel", 0, 8, 16, 0, 8, ".text")],
            )
        )
        obj = StackVMObject(
            b"ABCDEFGH",
            debug_payload,
            [
                ObjectSymbol(
                    "start_kernel",
                    0,
                    8,
                    ObjectSegment.CODE,
                    SymbolBinding.GLOBAL,
                    SymbolType.FUNCTION,
                    section_index=0,
                )
            ],
            sections=[
                ObjectSection(
                    ".text",
                    0,
                    8,
                    1,
                    ObjectSegment.CODE,
                    SectionFlags.EXECUTABLE,
                ),
                ObjectSection(
                    DEBUG_SECTION_NAME,
                    0,
                    len(debug_payload),
                    1,
                    ObjectSegment.DATA,
                    SectionFlags.READ_ONLY,
                ),
            ],
        )

        result = link_objects([("debug.o", loads_elf_object(dumps_elf_object(obj)))])
        blob = result.to_elf()
        self.assertIn(b".debug_line", blob)
        self.assertIn(b".debug_info", blob)
        self.assertIn(b".debug_abbrev", blob)
        self.assertIn(b"start_kernel", blob)
        self.assertIn(b"kernel.c", blob)
        executable = loads_elf_executable(blob)
        self.assertEqual(executable.debug_info, result.debug_info)


if __name__ == "__main__":
    unittest.main()
