import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.PyStackVM import (
    BC_HLT,
    BC_INVTLB,
    BC_LOAD,
    BC_NOP,
    BC_RET_E,
    BC_STOR,
    BCRE_IS_INT,
    BCR_ABS_A8,
    BCR_ATOMIC_CAS,
    BCR_ATOMIC_FADD,
    BCR_SYSREG,
    BCR_SZ_1,
    BCR_SZ_4,
    BCR_SZ_8,
    FLAGS_INT_ENABLE,
    INVTLB_SINGLE,
    SVSR_CORE_ID,
    SVSR_CYCLE_COUNT,
    SVSR_FLAGS,
    SVSR_IPI,
    SVSR_ISR,
    SVSR_SDP,
    SVSR_USER_TLPTR,
    TLBP_R,
)
from IsaacCompiler.StackVM.boot import boot_kernel, read_startup_data
from IsaacCompiler.code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const


IRET_BYTE = 0x80 | BCRE_IS_INT
_CPP_TMPDIRS = []


def _compile_cpp_backend_or_skip():
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        raise unittest.SkipTest("C++ compiler not available")
    tmp = tempfile.TemporaryDirectory()
    _CPP_TMPDIRS.append(tmp)
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    out = os.path.join(tmp.name, "stack_vm_test" + suffix)
    subprocess.check_call(
        [
            compiler,
            "-std=c++17",
            "-shared",
            "-fPIC",
            os.path.join(REPO_ROOT, "StackVM", "cpp", "stack_vm.cpp"),
            "-o",
            out,
        ]
    )
    return out


def _load_cpp_backend():
    os.environ["STACKVM_CPP_LIB"] = _compile_cpp_backend_or_skip()
    sys.modules.pop("IsaacCompiler.StackVM.CppStackVM", None)
    return importlib.import_module("IsaacCompiler.StackVM.CppStackVM")


def _write(mem, addr, data):
    for i, b in enumerate(data):
        mem[addr + i] = b


def _store_u64(mem, addr, value):
    _write(mem, addr, (value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little"))


def _install_isr(mem, vec, handler, run_flags=0x10):
    base = 0x4000 + vec * 16
    _store_u64(mem, base, run_flags)
    _store_u64(mem, base + 8, handler)


class TestCppBackendParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cpp = _load_cpp_backend()

    def test_boot_kernel_cpp_matches_python_launch_contract(self):
        vm, image = boot_kernel(
            bytes([BC_HLT]),
            vm_size=1 << 20,
            kernel_base=0x1000,
            cmdline="boot",
            backend="cpp",
        )

        self.assertEqual(vm.priv_lvl, 0)
        self.assertEqual(vm.virt_mem_mode, 0)
        self.assertEqual(vm.ip, image.kernel_base)
        self.assertEqual(vm.sys_regs[SVSR_SDP], image.startup_data_addr)
        self.assertEqual(vm.sys_regs[SVSR_CORE_ID], image.boot_core_id)
        self.assertEqual(vm.sp, image.vm_size)
        self.assertTrue(read_startup_data(vm.memory, vm.sys_regs[SVSR_SDP]).is_valid)

        vm.execute()
        self.assertEqual(vm.running, 0)
        self.assertEqual(vm.sys_regs[SVSR_CYCLE_COUNT], 1)

    def test_multicore_shared_memory_and_ipi_delivery(self):
        machine = self.cpp.MultiCoreMachine(2, 0x10000)
        c0, c1 = machine.cores
        c0.set_flags(0xFF)
        c1.set_flags(0xFF | FLAGS_INT_ENABLE)
        c1.sys_regs[SVSR_ISR] = 0x4000

        irq = 0x31
        marker = 0x3000
        data = 0x3008
        handler = 0x6000
        _install_isr(machine.memory, irq, handler)
        h = bytearray()
        emit_load_i_const(h, 1, sz_cls=0)
        h += bytes([BC_STOR, BCR_ABS_A8 | BCR_SZ_1]) + marker.to_bytes(8, "little")
        h += bytes([BC_RET_E, IRET_BYTE])
        _write(machine.memory, handler, h)

        p0 = bytearray()
        emit_load_i_const(p0, 0xA5, sz_cls=0)
        p0 += bytes([BC_STOR, BCR_ABS_A8 | BCR_SZ_1]) + data.to_bytes(8, "little")
        emit_load_i_const(p0, (irq << 8) | 1, sz_cls=3)
        p0 += bytes([BC_STOR, BCR_SYSREG | BCR_SZ_8, SVSR_IPI, BC_HLT])
        p1 = bytes([BC_NOP] * 16 + [BC_HLT])
        machine.load_program(p0, 0x0000, core_ids=[0])
        machine.load_program(p1, 0x0100, core_ids=[1])

        for _ in range(40):
            machine.step_round()

        self.assertEqual(machine.memory[data], 0xA5)
        self.assertEqual(machine.memory[marker], 1)
        self.assertEqual(c1.sys_regs[SVSR_CORE_ID], 1)

    def test_multicore_invtlb_broadcast_invalidates_sibling_tlb(self):
        machine = self.cpp.MultiCoreMachine(2, 0x10000)
        c0, c1 = machine.cores
        c0.set_flags(0xFF)
        c1.set_flags(0xFF)
        T = 0x7000
        c0.sys_regs[SVSR_USER_TLPTR] = T
        c1.sys_regs[SVSR_USER_TLPTR] = T
        c1.tlb_insert(T, 0x2000, 0x9000, TLBP_R)
        self.assertTrue(c1.tlb_has_entry(T, 0x2000))

        p0 = bytearray()
        emit_load_i_const(p0, T, sz_cls=3)
        emit_load_i_const(p0, 0x2000, sz_cls=3)
        emit_load_i_const(p0, 1, sz_cls=3)
        p0 += bytes([BC_INVTLB, INVTLB_SINGLE, 0, BC_HLT])
        machine.load_program(p0, 0x0000, core_ids=[0])

        for _ in range(8):
            machine.step_round()

        self.assertFalse(c1.tlb_has_entry(T, 0x2000))

    def test_cpp_atomic_rmw_ops_match_python_serialized_model(self):
        vm = self.cpp.VirtualMachine(0x10000)
        vm.set_flags(0xFF)
        value = 0x3000
        old_add = 0x3008
        old_cas = 0x3010
        _store_u64(vm.memory, value, 10)

        prog = bytearray()
        emit_load_i_const(prog, 5, sz_cls=2)
        emit_load_i_const(prog, value, sz_cls=3)
        prog += bytes([BC_LOAD, BCR_ATOMIC_FADD | BCR_SZ_4, 0])
        prog += bytes([BC_STOR, BCR_ABS_A8 | BCR_SZ_4]) + old_add.to_bytes(8, "little")
        emit_load_i_const(prog, 21, sz_cls=2)  # desired
        emit_load_i_const(prog, 15, sz_cls=2)  # expected
        emit_load_i_const(prog, value, sz_cls=3)
        prog += bytes([BC_LOAD, BCR_ATOMIC_CAS | BCR_SZ_4, 3])
        prog += bytes([BC_STOR, BCR_ABS_A8 | BCR_SZ_4]) + old_cas.to_bytes(8, "little")
        prog += bytes([BC_HLT])
        vm.load_program(prog, 0)
        vm.execute()

        self.assertEqual(int.from_bytes(vm.memory[value : value + 4], "little"), 21)
        self.assertEqual(int.from_bytes(vm.memory[old_add : old_add + 4], "little"), 10)
        self.assertEqual(int.from_bytes(vm.memory[old_cas : old_cas + 4], "little"), 15)


if __name__ == "__main__":
    unittest.main()
