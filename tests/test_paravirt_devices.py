"""Tests for D4 -- the phase-1 paravirt device layer.

The important ABI point is that guest kernels do not use CALL_E/SYSCALL for
host communication.  They ring a separate kernel-only software-interrupt
doorbell, CALL_E/IS_INT vector INT_PARAVIRT (0x12), with a small frame on the
guest stack.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.PyStackVM import (
    BC_CALL_E,
    BC_HLT,
    BCCE_IS_INT,
    BCCE_SYSCALL,
    BCCE_S_SYSN_SZ8,
    INT_PARAVIRT,
    VirtualMachine,
)
from IsaacCompiler.StackVM.paravirt import (
    PVH_BLOCK_READ,
    PVH_BLOCK_WRITE,
    PVH_CONSOLE_READ,
    PVH_CONSOLE_WRITE,
    PVH_ENTROPY,
    PVH_RTC_NOW_NS,
    PV_ARG_BYTES,
    PV_EINVAL,
    PV_ENODEV,
    PV_ENOSYS,
    MemoryBlockDevice,
    ParavirtDeviceSet,
)
from IsaacCompiler.StackVM.syscalls import SyscallDispatcher, build_dispatcher

BUF = 0x2000
DST = 0x2400


def _make_vm(devices, *, priv=0):
    vm = VirtualMachine(0x10000, 0)
    vm.memory[0:4] = bytes([BC_CALL_E, BCCE_IS_INT, INT_PARAVIRT, BC_HLT])
    vm.ip = 0
    vm.sp = vm.bp = len(vm.memory)
    vm.running = 1
    vm.set_flags(0xFF | (priv << 8))
    SyscallDispatcher([devices]).attach_to_py_vm(vm)
    return vm


def _push_hypercall(vm, number, a0=0, a1=0, a2=0, a3=0, arg_bytes=PV_ARG_BYTES):
    for val in (a3, a2, a1, a0, arg_bytes, number):
        vm.push(8, val)


def _result(vm):
    return vm.get(8, vm.sp + 40)


class ParavirtDoorbellTests(unittest.TestCase):
    def test_dispatcher_installs_paravirt_without_replacing_virt_syscall(self):
        vm = VirtualMachine(0x1000, 0)
        calls = []

        def sentinel(sys_n):
            calls.append(sys_n)

        vm.virt_syscall = sentinel
        build_dispatcher(["paravirt"]).attach_to_py_vm(vm)

        self.assertIs(vm.virt_syscall, sentinel)
        self.assertIsNotNone(vm.paravirt_hypercall)

    def test_console_write_uses_kernel_doorbell(self):
        output = bytearray()
        devices = ParavirtDeviceSet(console_output=output)
        vm = _make_vm(devices)
        data = b"early boot\n"
        vm.memory[BUF : BUF + len(data)] = data
        _push_hypercall(vm, PVH_CONSOLE_WRITE, BUF, len(data), 0, 0)

        vm.execute()

        self.assertEqual(output, data)
        self.assertEqual(_result(vm), len(data))
        self.assertEqual(vm.running, 0)

    def test_console_read_consumes_host_input(self):
        devices = ParavirtDeviceSet(console_input=b"abc", console_output=bytearray())
        vm = _make_vm(devices)
        _push_hypercall(vm, PVH_CONSOLE_READ, BUF, 8, 0, 0)

        vm.execute()

        self.assertEqual(_result(vm), 3)
        self.assertEqual(bytes(vm.memory[BUF : BUF + 3]), b"abc")
        self.assertEqual(devices.console_input, bytearray())

    def test_block_read_and_write(self):
        disk = MemoryBlockDevice(32)
        devices = ParavirtDeviceSet(
            console_output=bytearray(),
            block_devices=[disk],
        )
        data = b"rootfs"

        write_vm = _make_vm(devices)
        write_vm.memory[BUF : BUF + len(data)] = data
        _push_hypercall(write_vm, PVH_BLOCK_WRITE, 0, 4, BUF, len(data))
        write_vm.execute()

        self.assertEqual(_result(write_vm), len(data))
        self.assertEqual(bytes(disk.data[4 : 4 + len(data)]), data)

        read_vm = _make_vm(devices)
        _push_hypercall(read_vm, PVH_BLOCK_READ, 0, 4, DST, len(data))
        read_vm.execute()

        self.assertEqual(_result(read_vm), len(data))
        self.assertEqual(bytes(read_vm.memory[DST : DST + len(data)]), data)

    def test_rtc_and_entropy(self):
        devices = ParavirtDeviceSet(
            console_output=bytearray(),
            rtc_ns=lambda: 123456789,
            entropy=lambda n: bytes(range(n)),
        )
        rtc_vm = _make_vm(devices)
        _push_hypercall(rtc_vm, PVH_RTC_NOW_NS, 0, 0, 0, 0)
        rtc_vm.execute()
        self.assertEqual(_result(rtc_vm), 123456789)

        entropy_vm = _make_vm(devices)
        _push_hypercall(entropy_vm, PVH_ENTROPY, BUF, 6, 0, 0)
        entropy_vm.execute()
        self.assertEqual(_result(entropy_vm), 6)
        self.assertEqual(bytes(entropy_vm.memory[BUF : BUF + 6]), bytes(range(6)))

    def test_errors_are_returned_in_result_slot(self):
        devices = ParavirtDeviceSet(console_output=bytearray())

        missing_dev_vm = _make_vm(devices)
        _push_hypercall(missing_dev_vm, PVH_BLOCK_READ, 3, 0, BUF, 1)
        missing_dev_vm.execute()
        self.assertEqual(_result(missing_dev_vm), PV_ENODEV)

        unknown_vm = _make_vm(devices)
        _push_hypercall(unknown_vm, 0xFFFF, 0, 0, 0, 0)
        unknown_vm.execute()
        self.assertEqual(_result(unknown_vm), PV_ENOSYS)

        bad_frame_vm = _make_vm(devices)
        _push_hypercall(bad_frame_vm, PVH_CONSOLE_WRITE, BUF, 0, 0, 0, arg_bytes=8)
        bad_frame_vm.execute()
        self.assertEqual(_result(bad_frame_vm), PV_EINVAL)

    def test_user_mode_cannot_ring_paravirt_doorbell(self):
        devices = ParavirtDeviceSet(console_output=bytearray())
        vm = _make_vm(devices, priv=1)
        _push_hypercall(vm, PVH_CONSOLE_WRITE, BUF, 0, 0, 0)

        with self.assertRaisesRegex(Exception, "PROTECT_FAULT"):
            vm.execute()

    def test_kernel_call_e_syscall_still_traps_invalid_syscall(self):
        devices = ParavirtDeviceSet(console_output=bytearray())
        vm = VirtualMachine(0x10000, 0)
        vm.memory[0:2] = bytes([BC_CALL_E, BCCE_SYSCALL | BCCE_S_SYSN_SZ8])
        vm.ip = 0
        vm.sp = vm.bp = len(vm.memory)
        vm.running = 1
        vm.set_flags(0xFF)  # kernel privilege
        SyscallDispatcher([devices]).attach_to_py_vm(vm)
        vm.push(8, PVH_CONSOLE_WRITE)

        with self.assertRaisesRegex(Exception, "INVAL_SYSCALL"):
            vm.execute()


if __name__ == "__main__":
    unittest.main()
