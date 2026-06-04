import os
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.runner import load_sbc as load_runtime_sbc
from IsaacCompiler.code_gen.stackvm_binutils.archive_file import (
    ArchiveMember,
    StackVMArchive,
    dumps_sba,
    loads_sba,
    write_sba,
)
from IsaacCompiler.code_gen.stackvm_binutils.executable_file import (
    SBC_HEADER_SIZE,
    SBC_SPARSE_MAGIC,
    loads_sbc,
)
from IsaacCompiler.code_gen.stackvm_binutils.lib_util_asm_impl.names import (
    ISAAC_RUNTIME_LINK_NAMES,
)
from IsaacCompiler.code_gen.stackvm_binutils.linker import (
    DuplicateSymbolError,
    LINKER_DEFINED_SYMBOLS,
    UndefinedSymbolError,
    format_map,
    link,
    link_objects,
    parse_linker_script,
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
    load_sbo,
    write_sbo,
)


def _patch(value=0):
    return (value & ((1 << 64) - 1)).to_bytes(8, "little")


def _undefined(name, segment=ObjectSegment.CODE, typ=SymbolType.FUNCTION):
    return ObjectSymbol(
        name,
        0,
        0,
        segment,
        SymbolBinding.GLOBAL,
        typ,
        SymbolFlags.UNDEFINED,
    )


def _definition(
    name,
    size,
    segment=ObjectSegment.CODE,
    binding=SymbolBinding.GLOBAL,
    typ=SymbolType.FUNCTION,
):
    return ObjectSymbol(name, 0, size, segment, binding, typ)


def _referencing_object(name, relocation_type=RelocationType.PCREL8, addend=0):
    return StackVMObject(
        _patch(addend),
        b"",
        [_undefined(name)],
        [ObjectRelocation(0, 0, ObjectSegment.CODE, relocation_type)],
    )


class LinkerTests(unittest.TestCase):
    def test_layout_abs8_pcrel8_addends_map_and_sbc_output(self):
        caller_code = bytearray(16)
        caller_code[0:8] = _patch(2)
        caller_data = bytearray(_patch(3))
        caller = StackVMObject(
            bytes(caller_code),
            bytes(caller_data),
            [
                _undefined("target_fn"),
                _undefined("target_data", ObjectSegment.DATA, SymbolType.OBJECT),
            ],
            [
                ObjectRelocation(0, 0, ObjectSegment.CODE, RelocationType.PCREL8),
                ObjectRelocation(0, 1, ObjectSegment.DATA, RelocationType.ABS8),
            ],
        )
        definitions = StackVMObject(
            b"\xAA" * 4,
            b"\xBB" * 4,
            [
                _definition("target_fn", 4),
                _definition(
                    "target_data",
                    4,
                    ObjectSegment.DATA,
                    typ=SymbolType.OBJECT,
                ),
            ],
            data_alignment=16,
        )

        result = link_objects([("caller.sbo", caller), ("defs.sbo", definitions)])

        self.assertEqual(result.code_segment_end, 20)
        self.assertEqual(result.data_segment_start, 0x1000)
        self.assertEqual(result.global_symbols["target_fn"], 16)
        self.assertEqual(result.global_symbols["target_data"], 0x1010)
        self.assertEqual(
            int.from_bytes(result.memory[0:8], "little", signed=True),
            16 + 2 - 8,
        )
        self.assertEqual(
            int.from_bytes(result.memory[0x1000 : 0x1008], "little"),
            0x1010 + 3,
        )

        executable = loads_sbc(result.to_sbc())
        self.assertEqual(executable.memory, result.memory)
        self.assertEqual(executable.code_segment_end, result.code_segment_end)
        self.assertEqual(executable.data_segment_start, result.data_segment_start)

        map_text = format_map(result)
        self.assertIn("target_fn [defs.sbo]", map_text)
        self.assertIn("target_data [defs.sbo]", map_text)
        self.assertIn("DATA 0x0000000000001000", map_text)

    def test_strong_definitions_override_weak_and_duplicates_error(self):
        reference = _referencing_object("chosen")
        weak = StackVMObject(
            b"W" * 8,
            b"",
            [_definition("chosen", 8, binding=SymbolBinding.WEAK)],
        )
        second_weak = StackVMObject(
            b"V" * 8,
            b"",
            [_definition("chosen", 8, binding=SymbolBinding.WEAK)],
        )
        strong = StackVMObject(b"S" * 8, b"", [_definition("chosen", 8)])

        weak_result = link_objects([reference, weak, second_weak])
        self.assertEqual(weak_result.global_symbols["chosen"], 8)

        strong_result = link_objects([reference, weak, strong])
        self.assertEqual(strong_result.global_symbols["chosen"], 16)
        self.assertEqual(
            int.from_bytes(strong_result.memory[0:8], "little", signed=True),
            8,
        )
        weak_symbol = next(
            symbol
            for symbol in strong_result.symbols
            if symbol.binding == SymbolBinding.WEAK
        )
        self.assertFalse(weak_symbol.selected)

        with self.assertRaisesRegex(DuplicateSymbolError, "multiple strong"):
            link_objects([strong, StackVMObject(b"X" * 8, b"", [_definition("chosen", 8)])])

    def test_non_default_bases_and_local_symbol_relocations(self):
        obj = StackVMObject(
            b"C" * 8,
            _patch() + b"D" * 8,
            [
                _definition("entry", 8),
                ObjectSymbol(
                    ".local",
                    8,
                    8,
                    ObjectSegment.DATA,
                    SymbolBinding.LOCAL,
                    SymbolType.OBJECT,
                ),
            ],
            [ObjectRelocation(0, 1, ObjectSegment.DATA, RelocationType.ABS8)],
            data_alignment=16,
        )
        result = link_objects(
            [obj],
            code_base=0x20,
            data_base=0x10,
            data_alignment=0x10,
        )
        self.assertEqual(result.global_symbols["entry"], 0x20)
        self.assertEqual(result.code_segment_end, 0x28)
        self.assertEqual(result.data_segment_start, 0x30)
        self.assertEqual(
            int.from_bytes(result.memory[0x30:0x38], "little"),
            0x38,
        )

    def test_named_sections_bss_and_linker_defined_symbols(self):
        init = StackVMObject(
            b"I" * 4,
            b"",
            [
                ObjectSymbol(
                    "init",
                    0,
                    4,
                    ObjectSegment.CODE,
                    SymbolBinding.GLOBAL,
                    SymbolType.FUNCTION,
                    section_index=0,
                )
            ],
            sections=[
                ObjectSection(
                    ".init.text",
                    0,
                    4,
                    1,
                    ObjectSegment.CODE,
                    SectionFlags.EXECUTABLE,
                )
            ],
        )
        normal = StackVMObject(
            _patch() + b"T" * 8,
            b"DATA",
            [
                ObjectSymbol(
                    "normal",
                    8,
                    8,
                    ObjectSegment.CODE,
                    SymbolBinding.GLOBAL,
                    SymbolType.FUNCTION,
                    section_index=0,
                ),
                ObjectSymbol(
                    "zero",
                    4,
                    12,
                    ObjectSegment.DATA,
                    SymbolBinding.GLOBAL,
                    SymbolType.OBJECT,
                    section_index=2,
                ),
                _undefined("__bss_start", ObjectSegment.DATA, SymbolType.OBJECT),
            ],
            [
                ObjectRelocation(
                    0,
                    2,
                    ObjectSegment.CODE,
                    RelocationType.ABS8,
                    section_index=0,
                )
            ],
            sections=[
                ObjectSection(
                    ".text",
                    0,
                    16,
                    1,
                    ObjectSegment.CODE,
                    SectionFlags.EXECUTABLE,
                ),
                ObjectSection(
                    ".data.cacheline_aligned",
                    0,
                    4,
                    1,
                    ObjectSegment.DATA,
                ),
                ObjectSection(
                    ".bss",
                    4,
                    12,
                    4,
                    ObjectSegment.DATA,
                    SectionFlags.NOBITS,
                ),
            ],
        )

        result = link_objects([("init.sbo", init), ("normal.sbo", normal)])
        sections = {section.name: section for section in result.section_layouts}

        self.assertEqual(result.global_symbols["normal"], 8)
        self.assertEqual(result.global_symbols["__init_begin"], 16)
        self.assertEqual(result.global_symbols["__init_end"], 20)
        self.assertEqual(result.global_symbols["_start"], 0)
        self.assertEqual(result.global_symbols["__bss_start"], 0x1004)
        self.assertEqual(result.global_symbols["__bss_end"], 0x1010)
        self.assertEqual(result.global_symbols["_end"], 0x1010)
        self.assertEqual(
            int.from_bytes(result.memory[0:8], "little"),
            result.global_symbols["__bss_start"],
        )
        self.assertEqual(result.memory[0x1004:0x1010], b"\0" * 12)
        self.assertEqual(sections[".bss"].file_size, 0)
        self.assertLess(sections[".text"].address, sections[".init.text"].address)
        self.assertIn("__init_begin [<linker>]", format_map(result))
        sbc = result.to_sbc()
        self.assertEqual(sbc[:8], SBC_SPARSE_MAGIC)
        self.assertEqual(len(sbc), SBC_HEADER_SIZE + sections[".bss"].address)
        self.assertEqual(loads_sbc(sbc).memory, result.memory)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "bss.sbc")
            with open(path, "wb") as fl:
                fl.write(sbc)
            runtime_memory, _code_end, _data_start = load_runtime_sbc(path)
        self.assertEqual(runtime_memory, result.memory)

    def test_simple_linker_script_controls_data_section_order(self):
        obj = StackVMObject(
            b"",
            b"DATARODA",
            sections=[
                ObjectSection(".data", 0, 4, 1, ObjectSegment.DATA),
                ObjectSection(
                    ".rodata",
                    4,
                    4,
                    1,
                    ObjectSegment.DATA,
                    SectionFlags.READ_ONLY,
                ),
            ],
        )
        script = parse_linker_script(
            "SECTIONS { "
            ".text : { *(.text) } "
            ".init.text : { *(.init.text) } "
            ".rodata : { *(.rodata) } "
            ".data : { *(.data) } "
            ".bss : { *(.bss) } "
            "}"
        )

        result = link_objects([obj], linker_script=script)
        sections = {section.name: section for section in result.section_layouts}
        self.assertEqual(sections[".rodata"].address, 0x1000)
        self.assertEqual(sections[".data"].address, 0x1004)
        self.assertEqual(result.memory[0x1000:0x1008], b"RODADATA")

    def test_unresolved_symbols_error_or_remain_unmodified(self):
        obj = _referencing_object("missing", RelocationType.ABS8, addend=7)
        with self.assertRaisesRegex(UndefinedSymbolError, "missing"):
            link_objects([obj])

        result = link_objects([obj], allow_undefined=True)
        self.assertEqual(result.unresolved_symbols, ["missing"])
        self.assertEqual(int.from_bytes(result.memory[0:8], "little"), 7)
        self.assertIn("Unresolved symbols:", format_map(result))

    def test_archive_extracts_only_needed_members_and_follows_dependencies(self):
        root = _referencing_object("foo")
        foo = StackVMObject(
            _patch(),
            b"",
            [_definition("foo", 8), _undefined("bar")],
            [ObjectRelocation(0, 1, ObjectSegment.CODE, RelocationType.PCREL8)],
        )
        bar = StackVMObject(b"B" * 8, b"", [_definition("bar", 8)])
        unused = StackVMObject(b"U" * 64, b"", [_definition("unused", 64)])
        archive = StackVMArchive(
            [
                ArchiveMember("unused.sbo", unused),
                ArchiveMember("foo.sbo", foo),
                ArchiveMember("bar.sbo", bar),
            ]
        )

        result = link([("root.sbo", root), ("lib.sba", archive)])
        self.assertEqual(
            result.included_objects,
            ["root.sbo", "lib.sba(foo.sbo)", "lib.sba(bar.sbo)"],
        )
        self.assertEqual(result.code_segment_end, 24)
        self.assertNotIn("unused", result.global_symbols)
        self.assertEqual(result.global_symbols["foo"], 8)
        self.assertEqual(result.global_symbols["bar"], 16)

        with self.assertRaisesRegex(UndefinedSymbolError, "foo"):
            link([("lib.sba", archive), ("root.sbo", root)])

    def test_archive_format_round_trip_and_runtime_symbol_aliases(self):
        archive = StackVMArchive(
            [
                ArchiveMember(
                    raw_name + ".sbo",
                    StackVMObject(
                        b"M" * 8,
                        b"",
                        [_definition(ISAAC_RUNTIME_LINK_NAMES[raw_name], 8)],
                    ),
                )
                for raw_name in ("memset", "strlen")
            ]
        )
        self.assertEqual(loads_sba(dumps_sba(archive)), archive)
        with self.assertRaisesRegex(ValueError, "trailing"):
            loads_sba(dumps_sba(archive) + b"x")

        for raw_name in ("memset", "strlen"):
            with self.subTest(raw_name=raw_name):
                result = link([_referencing_object(raw_name), archive])
                self.assertEqual(result.global_symbols[raw_name], 8)
                self.assertEqual(
                    result.global_symbols[ISAAC_RUNTIME_LINK_NAMES[raw_name]],
                    8,
                )
                self.assertEqual(
                    result.included_objects[-1],
                    "<archive 1>(%s.sbo)" % raw_name,
                )

        with self.assertRaisesRegex(UndefinedSymbolError, "memset"):
            link_objects(
                [_referencing_object("memset")],
                [archive],
                runtime_aliases=False,
            )

    def test_cli_links_objects_and_archive_and_writes_map(self):
        root = _referencing_object("foo")
        definition = StackVMObject(b"F" * 8, b"", [_definition("foo", 8)])
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = os.path.join(tmpdir, "root.sbo")
            archive_path = os.path.join(tmpdir, "lib.sba")
            output_path = os.path.join(tmpdir, "out.sbc")
            map_path = os.path.join(tmpdir, "out.map")
            script_path = os.path.join(tmpdir, "layout.lds")
            write_sbo(root, root_path)
            write_sba(
                StackVMArchive([ArchiveMember("foo.sbo", definition)]),
                archive_path,
            )
            with open(script_path, "w") as fl:
                fl.write(
                    "SECTIONS { "
                    ".text : { *(.text) } "
                    ".init.text : { *(.init.text) } "
                    ".data : { *(.data) } "
                    ".rodata : { *(.rodata) } "
                    ".bss : { *(.bss) } "
                    "}"
                )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "IsaacCompiler",
                    "link",
                    "-T",
                    script_path,
                    "-o",
                    output_path,
                    "--map",
                    map_path,
                    root_path,
                    archive_path,
                ],
                cwd=REPO_PARENT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            memory, code_end, data_start = load_runtime_sbc(output_path)
            self.assertEqual(code_end, 16)
            self.assertEqual(data_start, 0x1000)
            self.assertEqual(
                int.from_bytes(memory[0:8], "little", signed=True),
                0,
            )
            with open(map_path, "r") as fl:
                map_text = fl.read()
            self.assertIn("foo", map_text)
            self.assertIn("lib.sba(foo.sbo)", map_text)
            self.assertIn(".init.text", map_text)

    def test_compiler_produced_objects_link_across_translation_units(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            caller_source = os.path.join(tmpdir, "caller.c")
            definition_source = os.path.join(tmpdir, "definition.c")
            caller_path = os.path.join(tmpdir, "caller.sbo")
            definition_path = os.path.join(tmpdir, "definition.sbo")
            with open(caller_source, "w") as fl:
                fl.write(
                    "extern int other(void); "
                    "int caller(void) { return other(); }\n"
                )
            with open(definition_source, "w") as fl:
                fl.write("int other(void) { return 7; }\n")
            for source_path, output_path in (
                (caller_source, caller_path),
                (definition_source, definition_path),
            ):
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "IsaacCompiler",
                        "compile",
                        "-c",
                        "-o",
                        output_path,
                        source_path,
                    ],
                    cwd=REPO_PARENT,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

            caller = load_sbo(caller_path)
            definition = load_sbo(definition_path)
            result = link_objects(
                [("caller.sbo", caller), ("definition.sbo", definition)]
            )
            relocation = next(
                relocation
                for relocation in caller.relocations
                if caller.symbols[relocation.symbol_index].name == "other"
            )
            addend = int.from_bytes(
                caller.code[relocation.offset : relocation.offset + 8],
                "little",
                signed=True,
            )
            expected = (
                result.global_symbols["other"]
                + addend
                - (relocation.offset + 8)
            )
            self.assertEqual(
                int.from_bytes(
                    result.memory[relocation.offset : relocation.offset + 8],
                    "little",
                    signed=True,
                ),
                expected,
            )

    def test_compiler_sections_and_linker_boundaries_end_to_end(self):
        source = (
            "extern char __init_begin[], __init_end[], "
            "__bss_start[], __bss_end[], _start[], _end[]; "
            'void __attribute__((section(".init.text"))) kernel_init(void) {} '
            "int zero; "
            "char *a = __init_begin; char *b = __init_end; "
            "char *c = __bss_start; char *d = __bss_end; "
            "char *e = _start; char *f = _end;\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "kernel.c")
            object_path = os.path.join(tmpdir, "kernel.sbo")
            with open(source_path, "w") as fl:
                fl.write(source)
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "IsaacCompiler",
                    "compile",
                    "-c",
                    "-o",
                    object_path,
                    source_path,
                ],
                cwd=REPO_PARENT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            obj = load_sbo(object_path)

        symbols = {symbol.name: symbol for symbol in obj.symbols}
        self.assertEqual(
            obj.sections[symbols["kernel_init"].section_index].name,
            ".init.text",
        )
        self.assertEqual(obj.sections[symbols["zero"].section_index].name, ".bss")
        targets = {
            obj.symbols[relocation.symbol_index].name
            for relocation in obj.relocations
        }
        self.assertTrue(LINKER_DEFINED_SYMBOLS <= targets)

        result = link_objects([obj])
        self.assertEqual(result.unresolved_symbols, [])
        self.assertEqual(result.global_symbols["_end"], len(result.memory))
        self.assertLessEqual(
            result.global_symbols["__init_begin"],
            result.global_symbols["__init_end"],
        )
        self.assertLess(
            result.global_symbols["__bss_start"],
            result.global_symbols["__bss_end"],
        )

    def test_compiler_emits_weak_bindings_for_weak_declarations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "weak.c")
            output_path = os.path.join(tmpdir, "weak.sbo")
            with open(source_path, "w") as fl:
                fl.write(
                    "extern int value; "
                    "int __attribute__((weak)) value = 3;\n"
                )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "IsaacCompiler",
                    "compile",
                    "-c",
                    "-o",
                    output_path,
                    source_path,
                ],
                cwd=REPO_PARENT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            symbol = next(
                symbol
                for symbol in load_sbo(output_path).symbols
                if symbol.name == "value"
            )
            self.assertEqual(symbol.binding, SymbolBinding.WEAK)


if __name__ == "__main__":
    unittest.main()
