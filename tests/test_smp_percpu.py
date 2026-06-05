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
    BC_STOR,
    SVSR_CORE_ID,
    SVSR_IPI,
    VM,
)
from IsaacCompiler.code_gen.Compilation import Compilation
from IsaacCompiler.code_gen.compile_stmnt import compile_stmnt
from IsaacCompiler.code_gen.percpu import (
    PERCPU_PRIMARY_SIZE_SYMBOL,
    PERCPU_PRIMARY_START_SYMBOL,
    PERCPU_SECTION_NAME,
)
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
from IsaacCompiler.lexer.lexer import get_list_tokens
from IsaacCompiler.parser.stmnt.get_stmnt import get_stmnt
from IsaacCompiler.parser.type.types import CompileContext


def _undefined(name):
    return ObjectSymbol(
        name,
        0,
        0,
        ObjectSegment.CODE,
        SymbolBinding.GLOBAL,
        SymbolType.FUNCTION,
        SymbolFlags.UNDEFINED,
    )


def _compile_object(source):
    source = preprocess(source, [os.path.join(REPO_ROOT, "StackVM", "include")])
    tokens = get_list_tokens(source)
    global_ctx = CompileContext("", None, None)
    cmpl_obj = Compilation(False)

    cursor = 0
    while cursor < len(tokens):
        stmnt, cursor = get_stmnt(tokens, cursor, len(tokens), global_ctx)
        compile_stmnt(cmpl_obj, stmnt, global_ctx, None)

    return global_ctx, cmpl_obj.to_stackvm_object()


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
        [_undefined("main")],
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


class SMPPerCpuTests(unittest.TestCase):
    def test_linker_places_and_repeats_percpu_section(self):
        obj = StackVMObject(
            b"",
            b"DATAPCPURODA",
            sections=[
                ObjectSection(".data", 0, 4, 1, ObjectSegment.DATA),
                ObjectSection(PERCPU_SECTION_NAME, 4, 4, 1, ObjectSegment.DATA),
                ObjectSection(
                    ".rodata",
                    8,
                    4,
                    1,
                    ObjectSegment.DATA,
                    SectionFlags.READ_ONLY,
                ),
            ],
        )

        result = link_objects([obj], percpu_copies=2)
        sections = {section.name: section for section in result.section_layouts}

        self.assertEqual(sections[PERCPU_SECTION_NAME].address, 0x1004)
        self.assertEqual(sections[PERCPU_SECTION_NAME].size, 8)
        self.assertEqual(sections[PERCPU_SECTION_NAME].file_size, 8)
        self.assertEqual(result.global_symbols[PERCPU_PRIMARY_START_SYMBOL], 0x1004)
        self.assertEqual(result.global_symbols[PERCPU_PRIMARY_SIZE_SYMBOL], 4)
        self.assertEqual(result.global_symbols["__percpu_end"], 0x1008)
        self.assertEqual(result.memory[0x1000:0x1010], b"DATAPCPUPCPURODA")

    def test_compiler_emits_percpu_section_and_core_id_address_math(self):
        _ctx, obj = _compile_object(
            "#include <linux/percpu.h>\n"
            "DEFINE_PER_CPU(int, counter) = 7;\n"
            "int read_counter(void) { return get_cpu_var(counter); }\n"
        )
        symbols = {symbol.name: symbol for symbol in obj.symbols}
        counter = symbols["counter"]

        self.assertEqual(obj.sections[counter.section_index].name, PERCPU_SECTION_NAME)
        self.assertIn(
            bytes([BC_LOAD, BCR_SYSREG | BCR_SZ_8, SVSR_CORE_ID]),
            obj.code,
        )
        relocation_targets = {
            obj.symbols[relocation.symbol_index].name
            for relocation in obj.relocations
            if relocation.segment == ObjectSegment.CODE
        }
        self.assertIn(PERCPU_PRIMARY_START_SYMBOL, relocation_targets)
        self.assertIn(PERCPU_PRIMARY_SIZE_SYMBOL, relocation_targets)

    def test_get_cpu_var_uses_current_core_copy_at_runtime(self):
        _ctx, obj = _compile_object(
            "#include <linux/percpu.h>\n"
            "DEFINE_PER_CPU(int, counter) = 7;\n"
            "int main(void) {\n"
            "    get_cpu_var(counter) = 41;\n"
            "    put_cpu_var(counter);\n"
            "    return counter + get_cpu_var(counter);\n"
            "}\n"
        )
        result = link_objects(
            [("start.sbo", _startup_object()), ("unit.sbo", obj)],
            percpu_copies=2,
        )

        vm = VM(65536)
        vm.load_program(result.memory, 0)
        vm.set_core_id(1)
        vm.execute()

        counter_addr = result.global_symbols["counter"]
        percpu_size = result.global_symbols[PERCPU_PRIMARY_SIZE_SYMBOL]
        self.assertEqual(vm.get(4, vm.sp), 48)
        self.assertEqual(vm.get(4, counter_addr), 7)
        self.assertEqual(vm.get(4, counter_addr + percpu_size), 41)

    def test_stackvm_core_id_and_ipi_sysregs(self):
        vm = VM(1024)
        vm.set_core_id(3)
        vm.load_program(
            bytes([BC_LOAD, BCR_SYSREG | BCR_SZ_8, SVSR_CORE_ID, BC_HLT]),
            0,
        )
        vm.execute()
        self.assertEqual(vm.pop(8), 3)

        ipi_value = (0x31 << 8) | 2
        program = bytearray()
        emit_load_i_const(program, ipi_value, False, 3)
        program.extend([BC_STOR, BCR_SYSREG | BCR_SZ_8, SVSR_IPI, BC_HLT])
        vm = VM(1024)
        vm.load_program(program, 0)
        vm.execute()
        self.assertEqual(vm.ipi_log, [(2, 0x31, ipi_value)])


if __name__ == "__main__":
    unittest.main()
