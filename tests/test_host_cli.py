"""Tests for the C2 host binutils CLIs (nm/objdump/readelf/size/strip/objcopy,
plus ranlib and kallsyms)."""

import os
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.code_gen.stackvm_binutils import host_cli
from IsaacCompiler.code_gen.stackvm_binutils.archive_file import (
    ArchiveMember,
    StackVMArchive,
    load_sba,
    write_sba,
)
from IsaacCompiler.code_gen.stackvm_binutils.debug_info import (
    DEBUG_SECTION_NAME,
    DebugFunctionRecord,
    DebugLineRecord,
    StackVMDebugInfo,
    dumps_debug,
)
from IsaacCompiler.code_gen.stackvm_binutils.elf_file import (
    loads_elf_executable,
    loads_elf_object,
    write_elf_object,
)
from IsaacCompiler.code_gen.stackvm_binutils.linker import link_files
from IsaacCompiler.code_gen.stackvm_binutils.object_file import (
    ObjectSection,
    ObjectSegment,
    ObjectSymbol,
    SectionFlags,
    StackVMObject,
    SymbolBinding,
    SymbolType,
    write_sbo,
)
from IsaacCompiler.code_gen.stackvm_binutils.svm_as import ObjectAssembler


# A single source covering every symbol kind nm has to classify.
_MIXED_SOURCE = """
.text
.globl gfunc
:gfunc
RET
:lfunc
RET
.data
.globl gdata
:gdata
.quad 1
:ldata
.quad 2
.section .rodata
.globl grodata
:grodata
.quad 3
.weak wfunc
:wfunc
RET
.comm gbss, 8
.lcomm lbss, 8
.data
:pext
.quad extern_undef
"""


def _assemble(source):
    asm = ObjectAssembler()
    asm.assemble_text(source)
    return asm.to_object()


def _write_object(tmpdir, name, source):
    path = os.path.join(tmpdir, name)
    write_elf_object(_assemble(source), path)
    return path


def _read_bytes(path):
    with open(path, "rb") as fl:
        return fl.read()


def _read_text(path):
    with open(path) as fl:
        return fl.read()


def _run_cli(*argv):
    env = {**os.environ, "PYTHONPATH": REPO_PARENT}
    return subprocess.run(
        [sys.executable, "-m", "IsaacCompiler", *argv],
        cwd=REPO_PARENT,
        capture_output=True,
        text=True,
        env=env,
    )


class NmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.obj = _write_object(self.tmp.name, "mixed.o", _MIXED_SOURCE)
        self.image = host_cli.load_image(self.obj)

    def _letters(self):
        return {
            sym.name: host_cli.nm_symbol_letter(sym, self.image)
            for sym in self.image.symbols
        }

    def test_type_letters_for_every_symbol_kind(self):
        letters = self._letters()
        self.assertEqual(letters["gfunc"], "T")
        self.assertEqual(letters["lfunc"], "t")
        self.assertEqual(letters["gdata"], "D")
        self.assertEqual(letters["ldata"], "d")
        self.assertEqual(letters["grodata"], "R")
        self.assertEqual(letters["wfunc"], "W")
        self.assertEqual(letters["gbss"], "B")
        self.assertEqual(letters["lbss"], "b")
        self.assertEqual(letters["extern_undef"], "U")

    def test_numeric_sort_orders_by_value_with_undefined_last(self):
        lines = host_cli.format_nm(self.image, numeric_sort=True)
        names = [line.split()[-1] for line in lines]
        defined = [n for n in names if n != "extern_undef"]
        values = [
            next(s.value for s in self.image.symbols if s.name == n) for n in defined
        ]
        self.assertEqual(values, sorted(values))
        # Undefined symbols carry no address and sort last.
        self.assertEqual(names[-1], "extern_undef")

    def test_undefined_lines_have_blank_value_field(self):
        line = next(
            line for line in host_cli.format_nm(self.image) if line.endswith("extern_undef")
        )
        self.assertTrue(line.startswith(" " * 16))
        self.assertEqual(line.split(), ["U", "extern_undef"])

    def test_defined_and_extern_only_filters(self):
        defined = [
            line.split()[-1] for line in host_cli.format_nm(self.image, defined_only=True)
        ]
        self.assertNotIn("extern_undef", defined)
        extern = {
            line.split()[-1] for line in host_cli.format_nm(self.image, extern_only=True)
        }
        self.assertIn("gfunc", extern)
        self.assertNotIn("lfunc", extern)
        self.assertNotIn("ldata", extern)

    def test_undefined_only_filter(self):
        names = {
            line.split()[-1]
            for line in host_cli.format_nm(self.image, undefined_only=True)
        }
        self.assertEqual(names, {"extern_undef"})

    def test_nm_reads_native_sbo(self):
        sbo_path = os.path.join(self.tmp.name, "native.sbo")
        write_sbo(_assemble(".text\n.globl onlyfn\n:onlyfn\nRET\n"), sbo_path)
        names = {
            line.split()[-1] for line in host_cli.format_nm(host_cli.load_image(sbo_path))
        }
        self.assertIn("onlyfn", names)

    def test_nm_lists_archive_members(self):
        archive = StackVMArchive(
            [
                ArchiveMember("a.o", _assemble(".text\n.globl alpha\n:alpha\nRET\n")),
                ArchiveMember("b.o", _assemble(".text\n.globl beta\n:beta\nRET\n")),
            ]
        )
        arc_path = os.path.join(self.tmp.name, "lib.sba")
        write_sba(archive, arc_path)
        members = dict(host_cli.load_archive_members(arc_path))
        self.assertEqual(set(members), {"a.o", "b.o"})
        self.assertIn("alpha", {l.split()[-1] for l in host_cli.format_nm(members["a.o"])})
        self.assertIn("beta", {l.split()[-1] for l in host_cli.format_nm(members["b.o"])})

    def test_nm_cli_numeric_sort(self):
        proc = _run_cli("nm", "-n", self.obj)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("gfunc", proc.stdout)
        self.assertIn("U extern_undef", proc.stdout)


class SizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_berkeley_totals(self):
        # 2 bytes text (two RETs), 8 bytes data (one .quad), 16 bytes bss (.comm).
        source = ".text\n:a\nRET\n:b\nRET\n.data\n:d\n.quad 1\n.comm bvar, 16\n"
        path = os.path.join(self.tmp.name, "x.o")
        write_elf_object(_assemble(source), path)
        image = host_cli.load_image(path)
        text, data, bss = host_cli.size_totals(image)
        self.assertEqual(text, 2)
        self.assertEqual(data, 8)
        self.assertEqual(bss, 16)
        lines = host_cli.format_size_berkeley([("x.o", image)])
        self.assertEqual(lines[0].split(), ["text", "data", "bss", "dec", "hex", "filename"])
        fields = lines[1].split()
        self.assertEqual(fields[:5], ["2", "8", "16", "26", "1a"])

    def test_size_reads_native_sbo(self):
        path = os.path.join(self.tmp.name, "native.sbo")
        write_sbo(_assemble(".text\n:a\nRET\n.data\n:d\n.quad 1\n"), path)
        text, data, bss = host_cli.size_totals(host_cli.load_image(path))
        self.assertEqual((text, data, bss), (1, 8, 0))

    def test_size_cli(self):
        obj = _write_object(self.tmp.name, "s.o", ".text\n:a\nRET\n.data\n:d\n.quad 1\n")
        proc = _run_cli("size", obj)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("text", proc.stdout)
        self.assertIn("dec", proc.stdout)


class ReadelfObjdumpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # An object with a relocation (a .quad referencing an undefined symbol).
        self.obj = _write_object(
            self.tmp.name,
            "r.o",
            ".text\n.globl kmain\n:kmain\nRET\n:helper\nRET\n"
            ".data\n.globl ptr\n:ptr\n.quad target\n",
        )
        self.obj_image = host_cli.load_image(self.obj)
        self.vmlinux = os.path.join(self.tmp.name, "vmlinux")
        link_files([_write_object(self.tmp.name, "k.o", ".text\n.globl kmain\n:kmain\nRET\n")], self.vmlinux)
        self.exe_image = host_cli.load_image(self.vmlinux)

    def test_readelf_file_and_section_headers(self):
        lines = host_cli.format_readelf(
            self.vmlinux,
            self.exe_image,
            file_header=True,
            section_headers=True,
            symbols=False,
            program_headers=True,
            relocs=False,
        )
        text = "\n".join(lines)
        self.assertIn("ELF Header:", text)
        self.assertIn("EXEC (Executable file)", text)
        self.assertIn("Machine:", text)
        self.assertIn(".text", text)
        self.assertIn("Program Headers:", text)
        self.assertIn("LOAD", text)

    def test_readelf_symbols(self):
        lines = host_cli.format_readelf(
            self.vmlinux,
            self.exe_image,
            file_header=False,
            section_headers=False,
            symbols=True,
            program_headers=False,
            relocs=False,
        )
        text = "\n".join(lines)
        self.assertIn("Symbol table", text)
        self.assertIn("kmain", text)

    def test_readelf_relocs(self):
        lines = host_cli.format_readelf(
            self.obj,
            self.obj_image,
            file_header=False,
            section_headers=False,
            symbols=False,
            program_headers=False,
            relocs=True,
        )
        text = "\n".join(lines)
        self.assertIn("R_STACKVM_64", text)
        self.assertIn("target", text)

    def test_objdump_disassembly_has_labels_and_mnemonics(self):
        lines = host_cli.format_objdump(
            self.vmlinux,
            self.exe_image,
            disassemble_code=True,
            section_headers=False,
            syms=False,
            relocs=False,
        )
        text = "\n".join(lines)
        self.assertIn("Disassembly of section .text:", text)
        self.assertIn("<kmain>:", text)
        self.assertIn("RET", text)

    def test_objdump_symbols_and_relocs(self):
        lines = host_cli.format_objdump(
            self.obj,
            self.obj_image,
            disassemble_code=False,
            section_headers=True,
            syms=True,
            relocs=True,
        )
        text = "\n".join(lines)
        self.assertIn("file format elf64-stackvm", text)
        self.assertIn("SYMBOL TABLE:", text)
        self.assertIn("kmain", text)
        self.assertIn("RELOCATION RECORDS:", text)
        self.assertIn("target", text)

    def test_readelf_cli(self):
        proc = _run_cli("readelf", "-h", "-S", self.vmlinux)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("ELF Header:", proc.stdout)
        self.assertIn(".text", proc.stdout)


class StripObjcopyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _object_with_debug(self):
        debug_payload = dumps_debug(
            StackVMDebugInfo(
                [DebugLineRecord(0, "k.c", 1, 1, ".text")],
                [DebugFunctionRecord("f", 0, 1, 1, 0, 1, ".text")],
            )
        )
        obj = StackVMObject(
            b"\x7e",  # RET
            debug_payload,
            [
                ObjectSymbol(
                    "f", 0, 1, ObjectSegment.CODE,
                    SymbolBinding.GLOBAL, SymbolType.FUNCTION, section_index=0,
                )
            ],
            sections=[
                ObjectSection(".text", 0, 1, 1, ObjectSegment.CODE, SectionFlags.EXECUTABLE),
                ObjectSection(
                    DEBUG_SECTION_NAME, 0, len(debug_payload), 1,
                    ObjectSegment.DATA, SectionFlags.READ_ONLY,
                ),
            ],
        )
        path = os.path.join(self.tmp.name, "dbg.o")
        write_elf_object(obj, path)
        return path

    def test_strip_debug_removes_debug_keeps_symbols_and_relinks(self):
        src = self._object_with_debug()
        out = os.path.join(self.tmp.name, "stripped.o")
        self.assertEqual(host_cli.run_strip(["--strip-debug", "-o", out, src]), 0)
        image = host_cli.load_image(out)
        self.assertNotIn(DEBUG_SECTION_NAME, [s.name for s in image.sections])
        self.assertIn("f", [s.name for s in image.symbols])
        # A stripped object must still be valid input to the linker.
        result = link_files([out], os.path.join(self.tmp.name, "vmlinux"))
        self.assertGreater(len(result.memory), 0)

    def test_strip_all_executable_removes_symbols(self):
        obj = _write_object(self.tmp.name, "u.o", ".text\n.globl kmain\n:kmain\nRET\n.data\n.globl g\n:g\n.quad 7\n")
        vmlinux = os.path.join(self.tmp.name, "vmlinux")
        link_files([obj], vmlinux)
        self.assertTrue(host_cli.load_image(vmlinux).symbols)
        out = os.path.join(self.tmp.name, "vmlinux.stripped")
        self.assertEqual(host_cli.run_strip(["-o", out, vmlinux]), 0)
        stripped = host_cli.load_image(out)
        self.assertEqual(stripped.symbols, [])
        # The stripped executable must still load and preserve the image bytes.
        before = loads_elf_executable(_read_bytes(vmlinux))
        after = loads_elf_executable(_read_bytes(out))
        self.assertEqual(after.memory, before.memory)

    def test_objcopy_output_binary_flat_image(self):
        obj = _write_object(self.tmp.name, "u.o", ".text\n:f\nRET\n.data\n:d\n.quad 0xAABBCCDD\n")
        vmlinux = os.path.join(self.tmp.name, "vmlinux")
        link_files([obj], vmlinux)
        binp = os.path.join(self.tmp.name, "image.bin")
        self.assertEqual(host_cli.run_objcopy(["-O", "binary", vmlinux, binp]), 0)
        payload = _read_bytes(binp)
        # Text begins the image; the .data .quad lands at its VMA (0x1000).
        self.assertEqual(payload[0], 0x7E)  # RET opcode
        self.assertEqual(payload[0x1000:0x1008], (0xAABBCCDD).to_bytes(8, "little"))

    def test_objcopy_output_binary_only_section(self):
        obj = _write_object(self.tmp.name, "u.o", ".text\n:f\nRET\n.data\n:d\n.quad 0x11\n")
        binp = os.path.join(self.tmp.name, "text.bin")
        self.assertEqual(
            host_cli.run_objcopy(["-O", "binary", "-j", ".text", obj, binp]), 0
        )
        self.assertEqual(_read_bytes(binp), b"\x7e")

    def test_objcopy_remove_section_round_trips_to_elf(self):
        src = self._object_with_debug()
        out = os.path.join(self.tmp.name, "nodbg.o")
        self.assertEqual(
            host_cli.run_objcopy(["-R", DEBUG_SECTION_NAME, src, out]), 0
        )
        image = host_cli.load_image(out)
        self.assertNotIn(DEBUG_SECTION_NAME, [s.name for s in image.sections])
        # Still a valid object.
        loads_elf_object(_read_bytes(out))


class RanlibTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_ranlib_round_trips_archive(self):
        archive = StackVMArchive(
            [
                ArchiveMember("a.o", _assemble(".text\n.globl a\n:a\nRET\n")),
                ArchiveMember("b.o", _assemble(".data\n.globl b\n:b\n.quad 9\n")),
            ]
        )
        path = os.path.join(self.tmp.name, "lib.sba")
        write_sba(archive, path)
        self.assertEqual(host_cli.run_ranlib([path]), 0)
        reread = load_sba(path)
        self.assertEqual([m.name for m in reread.members], ["a.o", "b.o"])
        self.assertIn("a", {s.name for s in reread.members[0].obj.symbols})
        self.assertIn("b", {s.name for s in reread.members[1].obj.symbols})

    def test_ranlib_rejects_non_archive(self):
        obj = _write_object(self.tmp.name, "u.o", ".text\n:f\nRET\n")
        self.assertEqual(host_cli.run_ranlib([obj]), 1)


class KallsymsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_generate_kallsyms_is_assemblable(self):
        entries = [(0x10, "T", "foo"), (0x20, "D", "bar")]
        asm_text = host_cli.generate_kallsyms(entries)
        obj = _assemble(asm_text)
        names = {s.name for s in obj.symbols}
        self.assertIn("kallsyms_num_syms", names)
        self.assertIn("kallsyms_addresses", names)
        self.assertIn("kallsyms_names", names)

    def test_kallsyms_from_elf_sorted_by_address(self):
        obj = _write_object(
            self.tmp.name,
            "u.o",
            ".text\n.globl high\n:high\nRET\nRET\n.globl low\n:low\nRET\n",
        )
        # 'high' is at address 0; 'low' follows it -> sorted by address.
        image = host_cli.load_image(obj)
        symbols = host_cli._kallsyms_symbols(image)
        values = [s.value for s in symbols]
        self.assertEqual(values, sorted(values))

    def test_kallsyms_consumes_nm_output(self):
        nm_text = "\n".join(
            [
                "0000000000000020 D bar",
                "0000000000000010 T foo",
                "                 U undefined_ignored",
            ]
        )
        entries = host_cli._kallsyms_from_nm(nm_text)
        self.assertEqual([(addr, name) for addr, _t, name in entries], [(0x10, "foo"), (0x20, "bar")])

    def test_kallsyms_cli_from_object(self):
        obj = _write_object(self.tmp.name, "u.o", ".text\n.globl kfn\n:kfn\nRET\n")
        out = os.path.join(self.tmp.name, "kallsyms.S")
        proc = _run_cli("kallsyms", obj, "-o", out)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        text = _read_text(out)
        self.assertIn("kallsyms_num_syms", text)
        self.assertIn("kfn", text)


if __name__ == "__main__":
    unittest.main()
