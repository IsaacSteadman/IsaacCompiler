import os
import struct
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.code_gen.stackvm_binutils.object_file import (
    ObjectRelocation,
    ObjectSection,
    ObjectSegment,
    ObjectSymbol,
    RelocationType,
    SBO_HEADER_SIZE,
    SBO_MAGIC,
    SBO_RELOCATION_ENTRY_SIZE,
    SBO_SECTION_ENTRY_SIZE,
    SBO_SYMBOL_ENTRY_SIZE,
    SBO_VERSION,
    SectionFlags,
    StackVMObject,
    SymbolBinding,
    SymbolFlags,
    SymbolType,
    dumps_sbo,
    load_sbo,
    loads_sbo,
    write_sbo,
)


def _signed_bytes(value):
    return (value & ((1 << 64) - 1)).to_bytes(8, "little")


def _sample_object():
    code = bytearray(16)
    data = bytearray(8)
    code[4:12] = _signed_bytes(-7)
    data[0:8] = _signed_bytes(11)
    return StackVMObject(
        bytes(code),
        bytes(data),
        [
            ObjectSymbol(
                "func",
                0,
                16,
                ObjectSegment.CODE,
                SymbolBinding.GLOBAL,
                SymbolType.FUNCTION,
            ),
            ObjectSymbol(
                "data",
                0,
                8,
                ObjectSegment.DATA,
                SymbolBinding.LOCAL,
                SymbolType.OBJECT,
            ),
            ObjectSymbol(
                "external",
                0,
                0,
                ObjectSegment.CODE,
                SymbolBinding.GLOBAL,
                SymbolType.FUNCTION,
                SymbolFlags.UNDEFINED,
            ),
        ],
        [
            ObjectRelocation(4, 2, ObjectSegment.CODE, RelocationType.PCREL8),
            ObjectRelocation(0, 1, ObjectSegment.DATA, RelocationType.ABS8),
        ],
        default_alignment=8,
        data_alignment=16,
    )


class ObjectFileFormatTests(unittest.TestCase):
    def test_binary_layout_and_round_trip(self):
        obj = _sample_object()
        blob = dumps_sbo(obj)
        header = struct.unpack("<8s9Q", blob[:SBO_HEADER_SIZE])
        (
            magic,
            version,
            default_alignment,
            data_alignment,
            code_size,
            data_size,
            symbol_offset,
            symbol_count,
            relocation_offset,
            relocation_count,
        ) = header

        self.assertEqual(magic, SBO_MAGIC)
        self.assertEqual(version, 1)
        self.assertEqual(default_alignment, 8)
        self.assertEqual(data_alignment, 16)
        self.assertEqual(code_size, len(obj.code))
        self.assertEqual(data_size, len(obj.data))
        self.assertEqual(symbol_offset, SBO_HEADER_SIZE + code_size + data_size)
        self.assertEqual(symbol_count, len(obj.symbols))
        self.assertEqual(
            relocation_offset,
            symbol_offset + symbol_count * SBO_SYMBOL_ENTRY_SIZE,
        )
        self.assertEqual(relocation_count, len(obj.relocations))

        for index in range(symbol_count):
            start = symbol_offset + index * SBO_SYMBOL_ENTRY_SIZE
            self.assertEqual(blob[start + 28 : start + 40], b"\0" * 12)
        undefined_start = symbol_offset + 2 * SBO_SYMBOL_ENTRY_SIZE
        self.assertEqual(blob[undefined_start + 27], int(SymbolFlags.UNDEFINED))
        for index in range(relocation_count):
            start = relocation_offset + index * SBO_RELOCATION_ENTRY_SIZE
            self.assertEqual(blob[start + 18 : start + 24], b"\0" * 6)

        string_offset = (
            relocation_offset + relocation_count * SBO_RELOCATION_ENTRY_SIZE
        )
        string_table = blob[string_offset:]
        names = []
        for index in range(symbol_count):
            start = symbol_offset + index * SBO_SYMBOL_ENTRY_SIZE
            name_offset = struct.unpack_from("<Q", blob, start)[0]
            end = string_table.index(b"\0", name_offset)
            names.append(string_table[name_offset:end].decode("utf-8"))
        self.assertEqual(names, ["func", "data", "external"])

        loaded = loads_sbo(blob)
        self.assertEqual(loaded, obj)
        self.assertEqual(int.from_bytes(loaded.code[4:12], "little", signed=True), -7)
        self.assertEqual(int.from_bytes(loaded.data[0:8], "little", signed=True), 11)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sample.sbo")
            write_sbo(obj, path)
            self.assertEqual(load_sbo(path), obj)

    def test_weak_symbol_binding_round_trip(self):
        obj = StackVMObject(
            b"W",
            b"",
            [
                ObjectSymbol(
                    "default_hook",
                    0,
                    1,
                    ObjectSegment.CODE,
                    SymbolBinding.WEAK,
                    SymbolType.FUNCTION,
                )
            ],
        )

        blob = dumps_sbo(obj)
        symbol_offset = struct.unpack_from("<Q", blob, 48)[0]
        self.assertEqual(blob[symbol_offset + 25], int(SymbolBinding.WEAK))
        self.assertEqual(loads_sbo(blob).symbols[0].binding, SymbolBinding.WEAK)

    def test_writer_rejects_invalid_metadata_and_patch_bounds(self):
        obj = _sample_object()
        obj.default_alignment = 3
        with self.assertRaisesRegex(ValueError, "default alignment"):
            dumps_sbo(obj)

        obj = _sample_object()
        obj.relocations[0].offset = len(obj.code) - 7
        with self.assertRaisesRegex(ValueError, "outside"):
            dumps_sbo(obj)

        obj = _sample_object()
        obj.symbols[2].size = 1
        with self.assertRaisesRegex(ValueError, "undefined symbols"):
            dumps_sbo(obj)

    def test_section_table_round_trip_and_nobits_storage(self):
        obj = StackVMObject(
            _signed_bytes(0),
            b"DATA",
            [
                ObjectSymbol(
                    "init",
                    0,
                    8,
                    ObjectSegment.CODE,
                    SymbolBinding.GLOBAL,
                    SymbolType.FUNCTION,
                    section_index=0,
                ),
                ObjectSymbol(
                    "zero",
                    8,
                    8,
                    ObjectSegment.DATA,
                    SymbolBinding.GLOBAL,
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
                    2,
                    ObjectSegment.CODE,
                    RelocationType.ABS8,
                    section_index=0,
                )
            ],
            sections=[
                ObjectSection(
                    ".init.text",
                    0,
                    8,
                    8,
                    ObjectSegment.CODE,
                    SectionFlags.EXECUTABLE,
                ),
                ObjectSection(".data", 0, 4, 4, ObjectSegment.DATA),
                ObjectSection(
                    ".bss",
                    4,
                    16,
                    8,
                    ObjectSegment.DATA,
                    SectionFlags.NOBITS,
                ),
            ],
        )

        blob = dumps_sbo(obj)
        header = struct.unpack("<8s9Q", blob[:SBO_HEADER_SIZE])
        self.assertEqual(header[1], SBO_VERSION)
        self.assertEqual(header[5], 4)
        section_count_offset = (
            header[8] + header[9] * SBO_RELOCATION_ENTRY_SIZE
        )
        self.assertEqual(struct.unpack_from("<Q", blob, section_count_offset)[0], 3)
        self.assertLessEqual(
            section_count_offset + 8 + 3 * SBO_SECTION_ENTRY_SIZE,
            len(blob),
        )
        self.assertEqual(loads_sbo(blob), obj)

        bad = _sample_object()
        bad.sections = [
            ObjectSection(
                ".bss",
                len(bad.data),
                8,
                8,
                ObjectSegment.DATA,
                SectionFlags.NOBITS,
            )
        ]
        with self.assertRaisesRegex(ValueError, "need a section"):
            dumps_sbo(bad)

    def test_reader_rejects_malformed_files(self):
        good = bytearray(dumps_sbo(_sample_object()))
        with self.assertRaisesRegex(ValueError, "too short"):
            loads_sbo(bytes(good[:20]))

        cases = []

        bad = bytearray(good)
        bad[0] ^= 0xFF
        cases.append((bad, "magic"))

        bad = bytearray(good)
        struct.pack_into("<Q", bad, 8, 99)
        cases.append((bad, "version"))

        bad = bytearray(good)
        struct.pack_into("<Q", bad, 48, SBO_HEADER_SIZE)
        cases.append((bad, "canonical"))

        symbol_offset = struct.unpack_from("<Q", good, 48)[0]
        relocation_offset = struct.unpack_from("<Q", good, 64)[0]

        bad = bytearray(good)
        bad[symbol_offset + 28] = 1
        cases.append((bad, "symbol reserved"))

        bad = bytearray(good)
        bad[relocation_offset + 18] = 1
        cases.append((bad, "relocation reserved"))

        bad = bytearray(good)
        struct.pack_into("<Q", bad, symbol_offset, 1 << 60)
        cases.append((bad, "name offset"))

        bad = bytearray(good)
        struct.pack_into("<Q", bad, relocation_offset, 15)
        cases.append((bad, "patch"))

        for blob, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    loads_sbo(bytes(blob))


if __name__ == "__main__":
    unittest.main()
