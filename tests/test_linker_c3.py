"""Tests for workstream C3: kernel/dynamic-userspace linker features.

Covers --gc-sections, --whole-archive, symbol-version scripts, --build-id,
--emit-relocs, ELF linker-script ENTRY/KEEP, and the -shared/-pie dynamic ABI
(ET_DYN with .dynsym/.dynstr/.hash/.dynamic and the DT_* contract).
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

from IsaacCompiler.code_gen.stackvm_binutils.archive_file import (
    ArchiveMember,
    StackVMArchive,
)
from IsaacCompiler.code_gen.stackvm_binutils.elf_file import (
    DF_1_PIE,
    DT_FLAGS_1,
    DT_HASH,
    DT_NEEDED,
    DT_SONAME,
    DT_STRTAB,
    DT_SYMTAB,
    ET_DYN,
    NT_GNU_BUILD_ID,
    PT_DYNAMIC,
    R_STACKVM_64,
    R_STACKVM_PC64,
    SHT_DYNAMIC,
    SHT_DYNSYM,
    SHT_HASH,
    parse_build_id_note,
    read_elf_image,
)
from IsaacCompiler.code_gen.stackvm_binutils.linker import (
    ArchiveInput,
    ObjectInput,
    UndefinedSymbolError,
    link,
    link_objects,
    parse_linker_script,
    parse_version_script,
)
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


def _patch(value=0):
    return (value & ((1 << 64) - 1)).to_bytes(8, "little")


def _func(name, section_index):
    return ObjectSymbol(
        name,
        0,
        0,
        ObjectSegment.CODE,
        SymbolBinding.GLOBAL,
        SymbolType.FUNCTION,
        section_index=section_index,
    )


def _gc_object():
    """An object with three text sections: entry -> helper, plus an unreferenced
    `dead` section whose only relocation targets an undefined symbol."""

    code = _patch(0) + b"H" * 8 + _patch(0)  # entry[0:8], helper[8:16], dead[16:24]
    return StackVMObject(
        code,
        b"",
        [
            ObjectSymbol(
                "entry", 0, 8, ObjectSegment.CODE, SymbolBinding.GLOBAL,
                SymbolType.FUNCTION, section_index=0,
            ),
            ObjectSymbol(
                "helper", 8, 8, ObjectSegment.CODE, SymbolBinding.GLOBAL,
                SymbolType.FUNCTION, section_index=1,
            ),
            ObjectSymbol(
                "dead", 16, 8, ObjectSegment.CODE, SymbolBinding.GLOBAL,
                SymbolType.FUNCTION, section_index=2,
            ),
            ObjectSymbol(
                "missing", 0, 0, ObjectSegment.CODE, SymbolBinding.GLOBAL,
                SymbolType.FUNCTION, SymbolFlags.UNDEFINED,
            ),
        ],
        [
            ObjectRelocation(0, 1, ObjectSegment.CODE, RelocationType.PCREL8, 0),
            ObjectRelocation(16, 3, ObjectSegment.CODE, RelocationType.PCREL8, 2),
        ],
        sections=[
            ObjectSection(".text.entry", 0, 8, 1, ObjectSegment.CODE, SectionFlags.EXECUTABLE),
            ObjectSection(".text.helper", 8, 8, 1, ObjectSegment.CODE, SectionFlags.EXECUTABLE),
            ObjectSection(".text.dead", 16, 8, 1, ObjectSegment.CODE, SectionFlags.EXECUTABLE),
        ],
    )


def _exporting_object():
    """A sectioned object exporting a function and a data pointer (with an
    absolute self-relocation), plus a would-be-hidden helper."""

    obj = StackVMObject(
        b"F" * 8 + b"G" * 8,  # exported_fn[0:8], local_hidden[8:16]
        _patch(0),  # ptr -> exported_fn
        [
            _func("exported_fn", 0),
            ObjectSymbol(
                "local_hidden", 8, 8, ObjectSegment.CODE, SymbolBinding.GLOBAL,
                SymbolType.FUNCTION, section_index=0,
            ),
            ObjectSymbol(
                "ptr", 0, 8, ObjectSegment.DATA, SymbolBinding.GLOBAL,
                SymbolType.OBJECT, section_index=1,
            ),
        ],
        [ObjectRelocation(0, 0, ObjectSegment.DATA, RelocationType.ABS8, 1)],
        sections=[
            ObjectSection(".text", 0, 16, 1, ObjectSegment.CODE, SectionFlags.EXECUTABLE),
            ObjectSection(".data", 0, 8, 1, ObjectSegment.DATA),
        ],
    )
    return obj


class GcSectionsTests(unittest.TestCase):
    def test_unreachable_section_is_collected(self):
        result = link_objects(
            [("a.sbo", _gc_object())],
            gc_sections=True,
            entry_symbol="entry",
            allow_undefined=False,
        )
        self.assertEqual(result.removed_sections, ["a.sbo:.text.dead"])
        self.assertIn("entry", result.global_symbols)
        self.assertIn("helper", result.global_symbols)
        self.assertNotIn("dead", result.global_symbols)
        # The dead section's reference to `missing` is collected with it, so the
        # link no longer fails on the undefined symbol.
        self.assertEqual(result.unresolved_symbols, [])

    def test_without_gc_unreferenced_section_and_undefined_remain(self):
        with self.assertRaisesRegex(UndefinedSymbolError, "missing"):
            link_objects([("a.sbo", _gc_object())])
        result = link_objects([("a.sbo", _gc_object())], allow_undefined=True)
        self.assertEqual(result.removed_sections, [])
        self.assertIn("dead", result.global_symbols)

    def test_keep_sections_and_legacy_objects_are_roots(self):
        obj = _gc_object()
        obj.sections.append(
            ObjectSection(".init_array", 0, 8, 8, ObjectSegment.DATA)
        )
        obj.data = _patch(0)
        # A legacy (section-less) object is never collectable.
        legacy = StackVMObject(b"L" * 8, b"")
        result = link_objects(
            [("a.sbo", obj), ("legacy.sbo", legacy)],
            gc_sections=True,
            entry_symbol="entry",
            allow_undefined=True,
        )
        removed = set(result.removed_sections)
        self.assertNotIn("a.sbo:.init_array", removed)
        self.assertNotIn("legacy.sbo:.text", removed)
        self.assertIn("a.sbo:.text.dead", removed)

    def test_keep_pattern_from_linker_script(self):
        obj = _gc_object()
        # Rename the dead section so the script can KEEP it explicitly.
        obj.sections[2] = ObjectSection(
            ".text.keepme", 16, 8, 1, ObjectSegment.CODE, SectionFlags.EXECUTABLE
        )
        script = parse_linker_script(
            "ENTRY(entry) SECTIONS { .text : { *(.text) KEEP(*(.text.keepme)) } "
            ".init.text : { *(.init.text) } .init_array : { *(.init_array) } "
            ".fini_array : { *(.fini_array) } .data : { *(.data) } "
            ".rodata : { *(.rodata) } .bss : { *(.bss) } }"
        )
        self.assertEqual(script.entry, "entry")
        self.assertIn(".text.keepme", script.keep)
        result = link_objects(
            [("a.sbo", obj)], gc_sections=True, linker_script=script,
            allow_undefined=True,
        )
        self.assertNotIn("a.sbo:.text.keepme", result.removed_sections)


class WholeArchiveTests(unittest.TestCase):
    def _archive(self):
        needed = StackVMObject(b"N" * 8, b"", [_func("needed_fn", None)])
        unused = StackVMObject(b"U" * 8, b"", [_func("unused_fn", None)])
        return StackVMArchive(
            [
                ArchiveMember("needed.sbo", needed),
                ArchiveMember("unused.sbo", unused),
            ]
        )

    def _root(self):
        return StackVMObject(
            _patch(0),
            b"",
            [
                ObjectSymbol(
                    "needed_fn", 0, 0, ObjectSegment.CODE, SymbolBinding.GLOBAL,
                    SymbolType.FUNCTION, SymbolFlags.UNDEFINED,
                )
            ],
            [ObjectRelocation(0, 0, ObjectSegment.CODE, RelocationType.PCREL8)],
        )

    def test_default_only_extracts_needed_member(self):
        result = link(
            [ObjectInput("root.sbo", self._root()), ArchiveInput("lib.sba", self._archive())]
        )
        self.assertIn("needed_fn", result.global_symbols)
        self.assertNotIn("unused_fn", result.global_symbols)

    def test_whole_archive_includes_all_members(self):
        result = link(
            [
                ObjectInput("root.sbo", self._root()),
                ArchiveInput("lib.sba", self._archive(), whole_archive=True),
            ]
        )
        self.assertIn("needed_fn", result.global_symbols)
        self.assertIn("unused_fn", result.global_symbols)


class VersionScriptTests(unittest.TestCase):
    def test_parse_nodes_globals_locals_and_parent(self):
        script = parse_version_script(
            "VERS_1.0 { global: api_*; init_module; local: *; }; "
            "VERS_1.1 { global: new_api; } VERS_1.0;"
        )
        self.assertEqual(len(script.nodes), 2)
        self.assertEqual(script.nodes[0].name, "VERS_1.0")
        self.assertIn("api_*", script.nodes[0].globals)
        self.assertIn("init_module", script.nodes[0].globals)
        self.assertEqual(script.nodes[0].locals, ("*",))
        self.assertEqual(script.nodes[1].parent, "VERS_1.0")
        self.assertTrue(script.is_local("private_thing"))
        self.assertFalse(script.is_local("api_v2"))
        self.assertFalse(script.is_local("init_module"))
        self.assertEqual(script.version_for("api_v2"), "VERS_1.0")
        self.assertEqual(script.version_for("new_api"), "VERS_1.1")

    def test_localization_hides_matched_symbols(self):
        script = parse_version_script("{ global: exported_fn; ptr; local: *; };")
        result = link_objects([("libfoo.sbo", _exporting_object())], version_script=script)
        self.assertIn("local_hidden", result.localized_symbols)
        self.assertNotIn("exported_fn", result.localized_symbols)
        self.assertNotIn("local_hidden", result.global_symbols)
        self.assertIn("exported_fn", result.global_symbols)
        hidden = next(s for s in result.symbols if s.name == "local_hidden")
        self.assertEqual(hidden.binding, SymbolBinding.LOCAL)


class BuildIdTests(unittest.TestCase):
    def test_sha1_is_reproducible_and_emitted_as_note(self):
        a = link_objects([("a.sbo", _exporting_object())], build_id="sha1")
        b = link_objects([("a.sbo", _exporting_object())], build_id="sha1")
        self.assertEqual(len(a.build_id), 20)
        self.assertEqual(a.build_id, b.build_id)
        image = read_elf_image(a.to_elf())
        self.assertEqual(image.build_id, a.build_id)
        note = image.section_by_name(".note.gnu.build-id")
        self.assertIsNotNone(note)
        self.assertEqual(parse_build_id_note(note.data), a.build_id)
        gnu_note = next(n for n in image.notes if n.typ == NT_GNU_BUILD_ID)
        self.assertEqual(gnu_note.name, "GNU")

    def test_md5_and_explicit_hex_styles(self):
        md5 = link_objects([("a.sbo", _exporting_object())], build_id="md5")
        self.assertEqual(len(md5.build_id), 16)
        explicit = link_objects(
            [("a.sbo", _exporting_object())], build_id="0xdeadbeef"
        )
        self.assertEqual(explicit.build_id, bytes.fromhex("deadbeef"))
        none = link_objects([("a.sbo", _exporting_object())], build_id="none")
        self.assertEqual(none.build_id, b"")


class EmitRelocsTests(unittest.TestCase):
    def test_symbolic_relocations_are_retained_in_elf(self):
        result = link_objects([("a.sbo", _gc_object())], emit_relocs=True, allow_undefined=True)
        self.assertTrue(result.emitted_relocations)
        names = {reloc.symbol_name for reloc in result.emitted_relocations}
        self.assertIn("helper", names)
        image = read_elf_image(result.to_elf())
        rela_text = image.section_by_name(".rela.text")
        self.assertIsNotNone(rela_text)
        elf_names = {reloc.symbol_name for reloc in image.relocations}
        self.assertIn("helper", elf_names)
        types = {reloc.typ for reloc in image.relocations}
        self.assertIn(R_STACKVM_PC64, types)

    def test_data_relocations_land_in_rela_data(self):
        result = link_objects([("a.sbo", _exporting_object())], emit_relocs=True)
        image = read_elf_image(result.to_elf())
        rela_data = image.section_by_name(".rela.data")
        self.assertIsNotNone(rela_data)
        # read_elf_image tags each relocation with the section it patches (.data),
        # taken from the .rela.data sh_info link.
        data_relocs = [r for r in image.relocations if r.section_name == ".data"]
        self.assertTrue(data_relocs)
        self.assertIn(R_STACKVM_64, {r.typ for r in data_relocs})


class SharedObjectTests(unittest.TestCase):
    def test_shared_object_has_dynamic_abi(self):
        result = link_objects(
            [("libfoo.sbo", _exporting_object())],
            shared=True,
            soname="libfoo.so.1",
            needed=["libc.so.6"],
        )
        self.assertTrue(result.is_shared)
        self.assertIn("exported_fn", result.dynamic_symbols)
        image = read_elf_image(result.to_elf())
        self.assertEqual(image.e_type, ET_DYN)
        self.assertIsNotNone(image.section_by_name(".dynsym"))
        self.assertIsNotNone(image.section_by_name(".dynstr"))
        self.assertIsNotNone(image.section_by_name(".hash"))
        self.assertIsNotNone(image.section_by_name(".dynamic"))
        self.assertEqual(image.section_by_name(".dynsym").typ, SHT_DYNSYM)
        self.assertEqual(image.section_by_name(".hash").typ, SHT_HASH)
        self.assertEqual(image.section_by_name(".dynamic").typ, SHT_DYNAMIC)
        tags = {entry.tag for entry in image.dynamic}
        for tag in (DT_NEEDED, DT_SONAME, DT_HASH, DT_SYMTAB, DT_STRTAB):
            self.assertIn(tag, tags)
        self.assertTrue(any(p.typ == PT_DYNAMIC for p in image.program_headers))
        # DT_NEEDED / DT_SONAME reference live offsets inside .dynstr.
        dynstr = image.section_by_name(".dynstr").data
        needed_off = next(e.value for e in image.dynamic if e.tag == DT_NEEDED)
        soname_off = next(e.value for e in image.dynamic if e.tag == DT_SONAME)
        self.assertIn(b"libc.so.6", dynstr)
        self.assertEqual(
            dynstr[needed_off : dynstr.index(b"\0", needed_off)], b"libc.so.6"
        )
        self.assertEqual(
            dynstr[soname_off : dynstr.index(b"\0", soname_off)], b"libfoo.so.1"
        )

    def test_pie_sets_df_1_pie_flag(self):
        result = link_objects([("a.sbo", _exporting_object())], pie=True)
        self.assertTrue(result.is_pie)
        image = read_elf_image(result.to_elf())
        self.assertEqual(image.e_type, ET_DYN)
        flags1 = next((e.value for e in image.dynamic if e.tag == DT_FLAGS_1), 0)
        self.assertTrue(flags1 & DF_1_PIE)


class CliIntegrationTests(unittest.TestCase):
    def _compile(self, tmpdir, name, source):
        src = os.path.join(tmpdir, name + ".c")
        obj = os.path.join(tmpdir, name + ".sbo")
        with open(src, "w") as fl:
            fl.write(source)
        proc = subprocess.run(
            [sys.executable, "-m", "IsaacCompiler", "compile", "-c", "-o", obj, src],
            cwd=REPO_PARENT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        return obj

    def _run(self, *argv):
        proc = subprocess.run(
            [sys.executable, "-m", "IsaacCompiler", *argv],
            cwd=REPO_PARENT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        return proc.stdout

    def test_link_shared_with_build_id_and_readelf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            obj = self._compile(tmpdir, "lib", "int add(int a, int b){return a+b;}\n")
            out = os.path.join(tmpdir, "libadd.elf")
            summary = self._run(
                "link", "--shared", "-soname", "libadd.so.1",
                "--needed", "libc.so.6", "--build-id=sha1", "-o", out, obj,
            )
            self.assertIn("build-id", summary)
            dyn = self._run("readelf", "-d", out)
            self.assertIn("SONAME", dyn)
            self.assertIn("NEEDED", dyn)
            notes = self._run("readelf", "-n", out)
            self.assertIn("NT_GNU_BUILD_ID", notes)
            header = self._run("readelf", "-h", out)
            self.assertIn("DYN", header)

    def test_link_gc_sections_via_cli(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            obj = self._compile(
                tmpdir, "k", "int kept(int x){return x;}\n"
            )
            out = os.path.join(tmpdir, "k.sbc")
            summary = self._run("link", "--gc-sections", "-e", "kept", "-o", out, obj)
            self.assertIn("Linked", summary)

    def test_gcc_driver_wl_build_id_and_shared(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "f.c")
            with open(src, "w") as fl:
                fl.write("int twice(int x){return x*2;}\n")
            out = os.path.join(tmpdir, "libf.so")
            proc = subprocess.run(
                [
                    sys.executable, "-m", "IsaacCompiler", "gcc", "-shared",
                    "-Wl,--build-id,-soname,libf.so.1", "-o", out, src,
                ],
                cwd=REPO_PARENT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            with open(out, "rb") as fl:
                image = read_elf_image(fl.read())
            self.assertEqual(image.e_type, ET_DYN)
            self.assertIsNotNone(image.build_id)


if __name__ == "__main__":
    unittest.main()
