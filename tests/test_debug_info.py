import os
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.code_gen.stackvm_binutils.addr2line import resolve_addresses
from IsaacCompiler.code_gen.stackvm_binutils.debug_info import (
    DEBUG_SECTION_NAME,
    DebugFunctionRecord,
    DebugLineRecord,
    StackVMDebugInfo,
    dumps_debug,
    format_addr2line,
    loads_debug,
    resolve_function,
    resolve_line,
    unwind_stack,
)
from IsaacCompiler.code_gen.stackvm_binutils.executable_file import (
    SBC_DEBUG_MAGIC,
    loads_sbc,
)
from IsaacCompiler.code_gen.stackvm_binutils.linker import link_objects
from IsaacCompiler.code_gen.stackvm_binutils.object_file import (
    ObjectSection,
    ObjectSegment,
    ObjectSymbol,
    SectionFlags,
    StackVMObject,
    SymbolBinding,
    SymbolType,
    load_sbo,
)


def _put_u64(memory, offset, value):
    memory[offset : offset + 8] = value.to_bytes(8, "little")


class DebugInfoTests(unittest.TestCase):
    def test_debug_codec_addr_resolution_and_stack_unwinding(self):
        info = StackVMDebugInfo(
            [
                DebugLineRecord(0x10, "main.c", 3, 5),
                DebugLineRecord(0x20, "main.c", 4, 9),
                DebugLineRecord(0x30, "lib.c", 8, 2),
            ],
            [
                DebugFunctionRecord("caller", 0x10, 0x20, 16),
                DebugFunctionRecord("callee", 0x30, 0x10, 24),
            ],
        )
        loaded = loads_debug(dumps_debug(info))
        self.assertEqual(loaded, info)
        self.assertEqual(format_addr2line(resolve_line(loaded, 0x24)), "main.c:4:9")
        self.assertEqual(resolve_function(loaded, 0x34).name, "callee")
        self.assertEqual(resolve_addresses(loaded, [0x24]), ["main.c:4:9"])

        memory = bytearray(128)
        _put_u64(memory, 80, 0x21)
        _put_u64(memory, 88, 96)
        _put_u64(memory, 96, 0x11)
        _put_u64(memory, 104, 128)
        frames = unwind_stack(memory, 80, 0x34, loaded)
        self.assertEqual([frame.function for frame in frames], ["callee", "caller"])
        self.assertEqual([frame.line for frame in frames], [8, 4])

    def test_linker_merges_debug_sections_and_sbc_carries_payload(self):
        debug_payload = dumps_debug(
            StackVMDebugInfo(
                [
                    DebugLineRecord(0, "unit.c", 10, 1, ".text"),
                    DebugLineRecord(4, "unit.c", 11, 3, ".text"),
                ],
                [
                    DebugFunctionRecord("fn", 0, 8, 32, 0, 8, ".text"),
                ],
            )
        )
        obj = StackVMObject(
            b"ABCDEFGH",
            debug_payload,
            [
                ObjectSymbol(
                    "fn",
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

        result = link_objects([("unit.sbo", obj)], code_base=0x20)
        linked_debug = loads_debug(result.debug_info)
        self.assertEqual(result.global_symbols["fn"], 0x20)
        self.assertEqual(format_addr2line(resolve_line(linked_debug, 0x24)), "unit.c:11:3")
        self.assertEqual(resolve_function(linked_debug, 0x24).frame_size, 32)
        self.assertEqual(len(result.memory), result.data_segment_start)

        sbc = result.to_sbc()
        self.assertEqual(sbc[:8], SBC_DEBUG_MAGIC)
        executable = loads_sbc(sbc)
        self.assertEqual(executable.debug_info, result.debug_info)
        self.assertEqual(executable.memory, result.memory)

    def test_compiler_emits_debug_and_addr2line_cli_resolves_linked_address(self):
        source = (
            "int callee(void) {\n"
            "    int x = 7;\n"
            "    return x;\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "debug_source.c")
            object_path = os.path.join(tmpdir, "debug_source.sbo")
            binary_path = os.path.join(tmpdir, "debug_source.sbc")
            with open(source_path, "w") as fl:
                fl.write(source)

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "IsaacCompiler",
                    "compile",
                    "-g",
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
            debug_sections = [
                section for section in obj.sections if section.name == DEBUG_SECTION_NAME
            ]
            self.assertEqual(len(debug_sections), 1)
            object_debug = loads_debug(
                obj.data[
                    debug_sections[0].offset : debug_sections[0].offset
                    + debug_sections[0].size
                ]
            )
            self.assertIn("callee", {function.name for function in object_debug.functions})
            self.assertIn(os.path.abspath(source_path), {line.file for line in object_debug.lines})

            result = link_objects([("debug_source.sbo", obj)])
            linked_debug = loads_debug(result.debug_info)
            callee_addr = result.global_symbols["callee"]
            self.assertEqual(resolve_function(linked_debug, callee_addr).name, "callee")
            self.assertEqual(resolve_line(linked_debug, callee_addr).line, 2)

            with open(binary_path, "wb") as fl:
                fl.write(result.to_sbc())
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "IsaacCompiler",
                    "addr2line",
                    binary_path,
                    hex(callee_addr),
                ],
                cwd=REPO_PARENT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            self.assertTrue(
                proc.stdout.strip().startswith(os.path.abspath(source_path) + ":2:"),
                msg=proc.stdout,
            )


if __name__ == "__main__":
    unittest.main()
