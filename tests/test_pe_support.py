"""Tests for the PE32+/COFF (UEFI ``.efi``) toolchain (workstream D1b.1).

The StackVM toolchain emits UEFI images as PE32+/COFF rather than ELF.  These
tests cover the PE writer/reader round-trip, the ``.reloc`` base-relocation
emit/load path (which reuses the ``R_STACKVM_RELATIVE`` base-fixup machinery),
the structural inspector, the host ``readelf``/``objdump`` PE views, and the
``-o foo.efi`` driver wiring through both the native ``link`` subcommand and the
gcc-compatible front end.
"""

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

from IsaacCompiler.code_gen.stackvm_binutils import host_cli
from IsaacCompiler.code_gen.stackvm_binutils.executable_file import StackVMExecutable
from IsaacCompiler.code_gen.stackvm_binutils.linker import link_files
from IsaacCompiler.code_gen.stackvm_binutils.object_file import (
    ObjectRelocation,
    ObjectSection,
    ObjectSegment,
    ObjectSymbol,
    RelocationType,
    SectionFlags,
    StackVMObject,
    SymbolBinding,
    SymbolType,
    write_sbo,
)
from IsaacCompiler.code_gen.stackvm_binutils.pe_file import (
    DEFAULT_IMAGE_BASE,
    DOS_MAGIC,
    IMAGE_FILE_DLL,
    IMAGE_FILE_MACHINE_STACKVM,
    IMAGE_REL_BASED_DIR64,
    IMAGE_SCN_MEM_EXECUTE,
    IMAGE_SCN_MEM_WRITE,
    IMAGE_SUBSYSTEM_EFI_APPLICATION,
    IMAGE_SUBSYSTEM_EFI_BOOT_SERVICE_DRIVER,
    IMAGE_SUBSYSTEM_EFI_RUNTIME_DRIVER,
    PE32PLUS_MAGIC,
    PE_SIGNATURE,
    SECTION_ALIGNMENT,
    build_reloc_section,
    dumps_pe_executable,
    is_pe_bytes,
    loads_pe_executable,
    parse_reloc_section,
    read_pe_image,
    subsystem_from_name,
)


def _ptr(value):
    return (value & ((1 << 64) - 1)).to_bytes(8, "little")


def _make_executable():
    """Build a small executable: 16 bytes of code, a page-aligned data segment
    holding two absolute pointers (base-relocation sites), and a BSS tail."""
    mem = bytearray(0x1040)
    mem[0:0x10] = bytes(range(0x10))
    mem[0x1000:0x1008] = _ptr(0x8)  # -> code address 0x8
    mem[0x1008:0x1010] = _ptr(0x1000)  # -> own address
    return StackVMExecutable(
        bytes(mem),
        code_segment_end=0x10,
        data_segment_start=0x1000,
        file_size=0x1010,
        base_relocations=(0x1000, 0x1008),
        debug_info=b"DBG-payload",
    )


class PeRoundTripTests(unittest.TestCase):
    def test_dumps_is_structurally_valid_pe32plus(self):
        blob = dumps_pe_executable(_make_executable())
        self.assertEqual(blob[:2], DOS_MAGIC)
        e_lfanew = struct.unpack_from("<I", blob, 0x3C)[0]
        self.assertEqual(blob[e_lfanew : e_lfanew + 4], PE_SIGNATURE)
        pe = read_pe_image(blob)
        self.assertEqual(pe.machine, IMAGE_FILE_MACHINE_STACKVM)
        # The optional-header magic is parsed by read_pe_image; confirm via the
        # raw bytes too so a regression in the struct layout is caught.
        opt_magic = struct.unpack_from("<H", blob, e_lfanew + 4 + 20)[0]
        self.assertEqual(opt_magic, PE32PLUS_MAGIC)
        self.assertEqual(pe.image_base, DEFAULT_IMAGE_BASE)
        self.assertEqual(pe.section_alignment, SECTION_ALIGNMENT)
        # Every section RVA / SizeOfImage is section-aligned.
        for section in pe.sections:
            self.assertEqual(section.virtual_address % SECTION_ALIGNMENT, 0)
        self.assertEqual(pe.size_of_image % SECTION_ALIGNMENT, 0)

    def test_round_trip_preserves_executable(self):
        exe = _make_executable()
        back = loads_pe_executable(dumps_pe_executable(exe))
        self.assertEqual(back.memory, exe.memory)
        self.assertEqual(back.code_segment_end, exe.code_segment_end)
        self.assertEqual(back.data_segment_start, exe.data_segment_start)
        self.assertEqual(back.file_size, exe.file_size)
        self.assertEqual(tuple(back.base_relocations), tuple(sorted(exe.base_relocations)))
        self.assertEqual(back.debug_info, exe.debug_info)

    def test_split_sections_named_text_and_data(self):
        pe = read_pe_image(dumps_pe_executable(_make_executable()))
        names = [s.name for s in pe.sections]
        self.assertIn(".text", names)
        self.assertIn(".data", names)
        self.assertIn(".reloc", names)
        self.assertIn(".svmmeta", names)
        text = pe.section_by_name(".text")
        data = pe.section_by_name(".data")
        self.assertTrue(text.characteristics & IMAGE_SCN_MEM_EXECUTE)
        self.assertFalse(text.characteristics & IMAGE_SCN_MEM_WRITE)
        self.assertTrue(data.characteristics & IMAGE_SCN_MEM_WRITE)
        # .data carries the initialised bytes; its VirtualSize spans the BSS tail.
        self.assertEqual(data.virtual_size, len(_make_executable().memory) - 0x1000)

    def test_single_image_fallback_for_unaligned_data(self):
        # A non-page-aligned data segment (and a nonzero inter-segment gap) must
        # fall back to a single .image section, and must still round-trip.
        mem = bytearray(0x40)
        mem[0:8] = bytes(range(8))
        mem[0x20:0x28] = _ptr(0x4)
        exe = StackVMExecutable(
            bytes(mem),
            code_segment_end=0x10,
            data_segment_start=0x20,
            file_size=0x28,
            base_relocations=(0x20,),
        )
        blob = dumps_pe_executable(exe)
        pe = read_pe_image(blob)
        self.assertIn(".image", [s.name for s in pe.sections])
        self.assertNotIn(".text", [s.name for s in pe.sections])
        back = loads_pe_executable(blob)
        self.assertEqual(back.memory, exe.memory)
        self.assertEqual(tuple(back.base_relocations), (0x20,))

    def test_no_base_relocations_omits_reloc_section(self):
        mem = bytearray(0x2000)
        mem[0:0x10] = bytes(range(0x10))
        exe = StackVMExecutable(bytes(mem), 0x10, 0x1000, 0x1000, base_relocations=())
        pe = read_pe_image(dumps_pe_executable(exe))
        self.assertIsNone(pe.section_by_name(".reloc"))
        self.assertEqual(pe.base_relocations, [])


class PeBaseRelocationTests(unittest.TestCase):
    def test_reloc_blocks_group_by_page_and_round_trip(self):
        # Offsets spanning two 4 KiB pages, biased by a section base.
        section_base = 0x1000
        offsets = [0x000, 0x008, 0x010, 0x1000, 0x1FF8]
        blob = build_reloc_section(offsets, section_base)
        decoded = parse_reloc_section(blob)
        rvas = [rva for rva, typ in decoded if typ == IMAGE_REL_BASED_DIR64]
        self.assertEqual(sorted(rvas), [section_base + o for o in offsets])
        # Two distinct destination pages -> two IMAGE_BASE_RELOCATION blocks.
        page_rvas = {(section_base + o) & ~0xFFF for o in offsets}
        self.assertEqual(len(page_rvas), 2)
        # Each block is 4-byte aligned (odd entry counts padded with ABSOLUTE).
        self.assertEqual(len(blob) % 4, 0)

    def test_stored_pointers_are_biased_to_image_base(self):
        exe = _make_executable()
        blob = dumps_pe_executable(exe, image_base=DEFAULT_IMAGE_BASE)
        pe = read_pe_image(blob)
        data = pe.section_by_name(".data")
        section_base = data.virtual_address - exe.data_segment_start
        # The first pointer originally held StackVM address 0x8; in the PE image
        # it must hold ImageBase + section_base + 0x8 and have a DIR64 entry.
        stored = int.from_bytes(data.data[0:8], "little")
        self.assertEqual(stored, DEFAULT_IMAGE_BASE + section_base + 0x8)
        reloc_rvas = {rva for rva, typ in pe.base_relocations}
        self.assertIn(data.virtual_address + 0, reloc_rvas)
        self.assertIn(data.virtual_address + 8, reloc_rvas)

    def test_relocating_image_base_changes_only_stored_pointers(self):
        exe = _make_executable()
        a = read_pe_image(dumps_pe_executable(exe, image_base=0x140000000))
        b = read_pe_image(dumps_pe_executable(exe, image_base=0x80000000))
        da, db = a.section_by_name(".data"), b.section_by_name(".data")
        # Same RVAs, different absolute stored values (the .reloc fixups differ).
        self.assertEqual(da.virtual_address, db.virtual_address)
        self.assertNotEqual(da.data[0:8], db.data[0:8])
        # But both decode back to the same StackVM executable.
        self.assertEqual(
            loads_pe_executable(dumps_pe_executable(exe, image_base=0x80000000)).memory,
            exe.memory,
        )


class PeSubsystemTests(unittest.TestCase):
    def test_subsystem_selection_and_dll_flag(self):
        exe = _make_executable()
        app = read_pe_image(dumps_pe_executable(exe, subsystem="efi-application"))
        bsd = read_pe_image(
            dumps_pe_executable(exe, subsystem="efi-boot-service-driver")
        )
        rtd = read_pe_image(dumps_pe_executable(exe, subsystem="efi-runtime-driver"))
        self.assertEqual(app.subsystem, IMAGE_SUBSYSTEM_EFI_APPLICATION)
        self.assertEqual(bsd.subsystem, IMAGE_SUBSYSTEM_EFI_BOOT_SERVICE_DRIVER)
        self.assertEqual(rtd.subsystem, IMAGE_SUBSYSTEM_EFI_RUNTIME_DRIVER)
        # Applications are EXEs; drivers are DLLs.
        self.assertFalse(app.characteristics & IMAGE_FILE_DLL)
        self.assertTrue(bsd.characteristics & IMAGE_FILE_DLL)
        self.assertTrue(rtd.characteristics & IMAGE_FILE_DLL)

    def test_subsystem_from_name_rejects_unknown(self):
        self.assertEqual(
            subsystem_from_name(None), IMAGE_SUBSYSTEM_EFI_APPLICATION
        )
        self.assertEqual(subsystem_from_name(11), 11)
        with self.assertRaises(ValueError):
            subsystem_from_name("not-a-subsystem")

    def test_entry_point_resolved_from_symbol(self):
        exe = _make_executable()

        class _Sym:
            def __init__(self, name, address):
                self.name = name
                self.address = address

        symbols = [_Sym("helper", 0x0), _Sym("efi_main", 0x8)]
        pe = read_pe_image(dumps_pe_executable(exe, symbols=symbols))
        text = pe.section_by_name(".text")
        self.assertEqual(pe.entry_point, text.virtual_address + 0x8)


def _build_object_with_pointer():
    """An object whose data holds an absolute pointer to a global (the linker
    turns the ABS8 relocation into an image base relocation)."""
    code = b"\x00" * 16
    data = _ptr(0) + b"\x11" * 8
    return StackVMObject(
        code,
        data,
        [
            ObjectSymbol(
                "efi_main",
                0,
                16,
                ObjectSegment.CODE,
                SymbolBinding.GLOBAL,
                SymbolType.FUNCTION,
                section_index=0,
            ),
            ObjectSymbol(
                "g_table",
                0,
                16,
                ObjectSegment.DATA,
                SymbolBinding.GLOBAL,
                SymbolType.OBJECT,
                section_index=1,
            ),
        ],
        [ObjectRelocation(0, 1, ObjectSegment.DATA, RelocationType.ABS8, 1)],
        sections=[
            ObjectSection(
                ".text", 0, 16, 1, ObjectSegment.CODE, SectionFlags.EXECUTABLE
            ),
            ObjectSection(".data", 0, 16, 16, ObjectSegment.DATA, SectionFlags.NONE),
        ],
    )


class PeLinkerOutputTests(unittest.TestCase):
    def test_link_files_writes_pe_for_dot_efi(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj_path = os.path.join(tmp, "app.sbo")
            efi_path = os.path.join(tmp, "app.efi")
            write_sbo(_build_object_with_pointer(), obj_path)
            link_files([obj_path], efi_path, subsystem="efi-boot-service-driver")
            with open(efi_path, "rb") as fl:
                blob = fl.read()
            self.assertTrue(is_pe_bytes(blob))
            pe = read_pe_image(blob)
            self.assertEqual(pe.machine, IMAGE_FILE_MACHINE_STACKVM)
            self.assertEqual(pe.subsystem, IMAGE_SUBSYSTEM_EFI_BOOT_SERVICE_DRIVER)
            # The resolved pointer to g_table produced a DIR64 base relocation.
            dir64 = [r for r in pe.base_relocations if r[1] == IMAGE_REL_BASED_DIR64]
            self.assertTrue(dir64)
            # Entry point lands on efi_main (code address 0 -> first text RVA).
            self.assertEqual(pe.entry_point, pe.section_by_name(".text").virtual_address)

    def test_link_files_pe_round_trips_to_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj_path = os.path.join(tmp, "app.sbo")
            efi_path = os.path.join(tmp, "app.efi")
            sbc_path = os.path.join(tmp, "app.sbc")
            write_sbo(_build_object_with_pointer(), obj_path)
            link_files([obj_path], efi_path)
            link_files([obj_path], sbc_path)
            from IsaacCompiler.code_gen.stackvm_binutils.executable_file import load_sbc

            with open(efi_path, "rb") as fl:
                pe_exe = loads_pe_executable(fl.read())
            sbc_exe = load_sbc(sbc_path)
            self.assertEqual(pe_exe.memory, sbc_exe.memory)
            self.assertEqual(pe_exe.code_segment_end, sbc_exe.code_segment_end)
            self.assertEqual(pe_exe.data_segment_start, sbc_exe.data_segment_start)
            self.assertEqual(
                tuple(pe_exe.base_relocations), tuple(sbc_exe.base_relocations)
            )


class PeInspectionTests(unittest.TestCase):
    def test_readelf_renders_pe_headers_sections_relocs(self):
        blob = dumps_pe_executable(_make_executable(), subsystem="efi-application")
        pe = read_pe_image(blob)
        lines = host_cli.format_pe_readelf(
            "app.efi", pe, file_header=True, section_headers=True, relocs=True
        )
        text = "\n".join(lines)
        self.assertIn("PE32+", text)
        self.assertIn("EFI Application", text)
        self.assertIn("BASE RELOCATION", text)
        self.assertIn(".reloc", text)
        self.assertIn("DIR64", text)

    def test_objdump_renders_pe_sections_and_disasm(self):
        blob = dumps_pe_executable(_make_executable())
        pe = read_pe_image(blob)
        lines = host_cli.format_pe_objdump(
            "app.efi", pe, disassemble_code=True, section_headers=True, relocs=True
        )
        text = "\n".join(lines)
        self.assertIn("pe32+-stackvm", text)
        self.assertIn("Disassembly of section .text", text)
        self.assertIn("BASE RELOCATION RECORDS", text)

    def test_image_from_bytes_rejects_pe_for_elf_tools(self):
        # nm/size go through the ELF image path and must not silently mis-read a
        # PE image as ELF.
        blob = dumps_pe_executable(_make_executable())
        self.assertTrue(is_pe_bytes(blob))
        with self.assertRaises(host_cli.HostToolError):
            host_cli.image_from_bytes(blob)


def _run_cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "IsaacCompiler"] + list(args),
        cwd=REPO_PARENT if cwd is None else cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": REPO_PARENT},
    )


class PeDriverCliTests(unittest.TestCase):
    def test_link_subcommand_emits_efi(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj_path = os.path.join(tmp, "app.sbo")
            efi_path = os.path.join(tmp, "app.efi")
            write_sbo(_build_object_with_pointer(), obj_path)
            proc = _run_cli(
                ["link", obj_path, "-o", efi_path, "--subsystem", "efi-runtime-driver"]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            with open(efi_path, "rb") as fl:
                blob = fl.read()
            self.assertTrue(is_pe_bytes(blob))
            self.assertEqual(
                read_pe_image(blob).subsystem, IMAGE_SUBSYSTEM_EFI_RUNTIME_DRIVER
            )

    def test_readelf_cli_inspects_efi(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj_path = os.path.join(tmp, "app.sbo")
            efi_path = os.path.join(tmp, "app.efi")
            write_sbo(_build_object_with_pointer(), obj_path)
            link_files([obj_path], efi_path)
            proc = _run_cli(["readelf", "-h", "-S", "-r", efi_path])
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertIn("PE32+", proc.stdout)
            self.assertIn("EFI Application", proc.stdout)
            self.assertIn("DIR64", proc.stdout)

    def test_gcc_driver_emits_efi(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "app.c")
            efi_path = os.path.join(tmp, "app.efi")
            with open(src, "w") as fl:
                fl.write(
                    "unsigned long efi_main(void *image, void *systab)"
                    " { return 0; }\n"
                )
            proc = _run_cli(
                ["gcc", src, "-o", efi_path, "--subsystem", "efi-application"]
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            with open(efi_path, "rb") as fl:
                blob = fl.read()
            self.assertTrue(is_pe_bytes(blob))
            self.assertEqual(
                read_pe_image(blob).subsystem, IMAGE_SUBSYSTEM_EFI_APPLICATION
            )


if __name__ == "__main__":
    unittest.main()
