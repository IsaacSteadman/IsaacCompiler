import os
import sys
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
    BCR_SYSREG,
    BCR_SZ_1,
    BCR_SZ_8,
    FLAGS_INT_ENABLE,
    INT_TLB_SHOOTDOWN,
    INT_TLB_SHOOTDOWN_DONE,
    INVTLB_ACK,
    INVTLB_F_ASYNC,
    INVTLB_F_REMOTE_INT,
    INVTLB_LOCAL,
    MultiCoreMachine,
    SVSR_FLAGS,
    SVSR_INT_ARG0,
    SVSR_INT_ARG1,
    SVSR_INT_ARG2,
    SVSR_INT_ARG3,
    SVSR_ISR,
    SVSR_CORE_ID,
    SVSR_IPI,
    SVSR_KERNEL_TLPTR,
    SVSR_USER_TLPTR,
    TLBP_R,
)
from IsaacCompiler.code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const


IRET_BYTE = 0x80 | BCRE_IS_INT


def _store_u64(mem, addr, value):
    mem[addr : addr + 8] = (value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")


def _write(mem, addr, data):
    mem[addr : addr + len(data)] = bytes(data)


def _set_kernel_flags(vm, *, enable_interrupts=False):
    flags = 0xFF | (FLAGS_INT_ENABLE if enable_interrupts else 0)
    vm.set_flags(flags)
    return flags


def _install_isr(machine, vec, handler, run_flags=0x10):
    base = 0x4000 + vec * 16
    _store_u64(machine.memory, base, run_flags)
    _store_u64(machine.memory, base + 8, handler)


class TestPythonMultiCoreMachine(unittest.TestCase):
    def test_round_robin_shares_memory_and_keeps_per_core_state(self):
        machine = MultiCoreMachine(2, 0x10000, stack_size=0x1000)
        c0, c1 = machine.cores
        self.assertIs(c0.memory, c1.memory)
        self.assertIs(c0.memory, machine.memory)
        self.assertNotEqual(c0.sp, c1.sp)

        c0.sys_regs[SVSR_KERNEL_TLPTR] = 0x1000
        c1.sys_regs[SVSR_KERNEL_TLPTR] = 0x2000

        data = 0x3000
        result_data = 0x3008
        result_core = 0x3010
        p0 = bytearray()
        emit_load_i_const(p0, 0x5A, sz_cls=0)
        p0 += bytes([BC_STOR, BCR_ABS_A8 | BCR_SZ_1]) + data.to_bytes(8, "little")
        p0 += bytes([BC_HLT])

        p1 = bytearray([BC_NOP])
        p1 += bytes([BC_LOAD, BCR_SYSREG | BCR_SZ_8, SVSR_CORE_ID])
        p1 += bytes([BC_STOR, BCR_ABS_A8 | BCR_SZ_8]) + result_core.to_bytes(
            8, "little"
        )
        p1 += bytes([BC_LOAD, BCR_ABS_A8 | BCR_SZ_1]) + data.to_bytes(8, "little")
        p1 += bytes([BC_STOR, BCR_ABS_A8 | BCR_SZ_1]) + result_data.to_bytes(
            8, "little"
        )
        p1 += bytes([BC_HLT])

        _write(machine.memory, 0x0000, p0)
        _write(machine.memory, 0x0100, p1)
        c0.ip = 0x0000
        c1.ip = 0x0100
        machine.run_round_robin(max_rounds=16)

        self.assertEqual(machine.memory[data], 0x5A)
        self.assertEqual(machine.memory[result_data], 0x5A)
        self.assertEqual(
            int.from_bytes(machine.memory[result_core : result_core + 8], "little"),
            1,
        )
        self.assertEqual(c0.sys_regs[SVSR_KERNEL_TLPTR], 0x1000)
        self.assertEqual(c1.sys_regs[SVSR_KERNEL_TLPTR], 0x2000)

    def test_round_robin_delivers_ipi_to_target_core(self):
        machine = MultiCoreMachine(2, 0x10000, stack_size=0x1000)
        c0, c1 = machine.cores
        _set_kernel_flags(c0)
        _set_kernel_flags(c1, enable_interrupts=True)
        c1.sys_regs[SVSR_ISR] = 0x4000

        irq = 0x31
        marker = 0x3000
        handler = 0x6000
        _install_isr(machine, irq, handler)
        h = bytearray()
        emit_load_i_const(h, 1, sz_cls=0)
        h += bytes([BC_STOR, BCR_ABS_A8 | BCR_SZ_1]) + marker.to_bytes(8, "little")
        h += bytes([BC_RET_E, IRET_BYTE])
        _write(machine.memory, handler, h)

        ipi_value = (irq << 8) | 1
        p0 = bytearray()
        emit_load_i_const(p0, ipi_value, sz_cls=3)
        p0 += bytes([BC_STOR, BCR_SYSREG | BCR_SZ_8, SVSR_IPI, BC_HLT])
        p1 = bytearray([BC_NOP] * 12 + [BC_HLT])
        _write(machine.memory, 0x0000, p0)
        _write(machine.memory, 0x0100, p1)
        c0.ip = 0x0000
        c1.ip = 0x0100

        machine.run_round_robin(max_rounds=32)

        self.assertEqual(machine.memory[marker], 1)
        self.assertFalse(c1.apic.pending())

    def test_remote_int_tlb_shootdown_is_serviced_and_acked_by_core(self):
        machine = MultiCoreMachine(2, 0x10000, stack_size=0x1000)
        c0, c1 = machine.cores
        _set_kernel_flags(c0)
        _set_kernel_flags(c1, enable_interrupts=True)
        c1.sys_regs[SVSR_ISR] = 0x4000

        T = 0x7000
        c0.sys_regs[SVSR_USER_TLPTR] = T
        c1.sys_regs[SVSR_USER_TLPTR] = T
        c1.tlb[(T, 0x2000)] = [0x9000, TLBP_R]

        handler = 0x6100
        _install_isr(machine, INT_TLB_SHOOTDOWN, handler)
        h = bytearray()
        h += bytes([BC_LOAD, BCR_SYSREG | BCR_SZ_8, SVSR_INT_ARG0])
        h += bytes([BC_LOAD, BCR_SYSREG | BCR_SZ_8, SVSR_INT_ARG1])
        h += bytes([BC_LOAD, BCR_SYSREG | BCR_SZ_8, SVSR_INT_ARG2])
        h += bytes([BC_INVTLB, INVTLB_LOCAL])
        h += bytes([BC_LOAD, BCR_SYSREG | BCR_SZ_8, SVSR_INT_ARG3])
        h += bytes([BC_INVTLB, INVTLB_ACK])
        h += bytes([BC_RET_E, IRET_BYTE])
        _write(machine.memory, handler, h)
        _write(machine.memory, 0x0100, bytes([BC_NOP] * 12 + [BC_HLT]))
        c1.ip = 0x0100

        c0.tlb_shootdown(
            [(T, 0x2000, 1)], INVTLB_F_ASYNC | INVTLB_F_REMOTE_INT, done_core=0
        )
        self.assertIn((T, 0x2000), c1.tlb)
        machine.run_round_robin(max_rounds=32)

        self.assertNotIn((T, 0x2000), c1.tlb)
        self.assertTrue(c0.apic.pending())
        self.assertEqual(c0.apic.which_int, INT_TLB_SHOOTDOWN_DONE)


if __name__ == "__main__":
    unittest.main()
