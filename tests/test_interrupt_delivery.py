"""Tests for D2 -- interrupt-delivery correctness in the Python StackVM.

The asynchronous interrupt controller (AdvProgIntCtl) used to be a single-slot
mailbox that the CPU delivered *unconditionally* after every instruction,
ignoring the FLAGS interrupt-enable bit and the priority mask.  D2 makes it a
proper local APIC:

  * Maskable interrupts are gated on FLAGS bit 14 (Enable Interrupts) and on the
    priority mask (lower priority number == more urgent; a pending interrupt is
    delivered only when its priority is strictly more urgent than the current
    FLAGS priority).
  * INT_NMI (0x02) is non-maskable -- delivered regardless of the enable bit or
    the priority mask.
  * Multiple pending sources are queued (drained most-urgent-first, FIFO among
    ties) rather than overwriting a single slot.

These tests cover the controller in isolation, the VM gating helper
(deliver_pending_interrupt), and full execution through execute_with_interrupts
with a real ISR table + handler.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.PyStackVM import (
    AdvProgIntCtl,
    BC_HLT,
    BC_NOP,
    BC_RET_E,
    BC_STOR,
    BCRE_IS_INT,
    BCR_ABS_A8,
    BCR_SZ_1,
    FLAGS_INT_ENABLE,
    FLAGS_PRIORITY_MASK,
    INT_NMI,
    INT_TIMER,
    INT_HW_IO,
    SVSR_FLAGS,
    SVSR_ISR,
    SVSR_INT_ARG0,
    SVSR_INT_ARG1,
    VirtualMachine,
)
from IsaacCompiler.code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const

# IRET = RET_E with IS_SYS (0x80) | IS_INT (BCRE_IS_INT).
IRET_BYTE = 0x80 | BCRE_IS_INT


def _never(_int_n):
    # priority_of resolver that must not be consulted (entries pin priorities).
    raise AssertionError("priority resolver should not be called")


def _const_priority(value):
    return lambda _int_n: value


# ---------------------------------------------------------------------------
# Controller in isolation
# ---------------------------------------------------------------------------
class TestAdvProgIntCtl(unittest.TestCase):
    def test_empty_controller_is_idle(self):
        apic = AdvProgIntCtl()
        self.assertFalse(apic.pending())
        self.assertFalse(apic.int_ready)
        self.assertIsNone(
            apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _const_priority(0))
        )

    def test_trigger_updates_legacy_head_view(self):
        apic = AdvProgIntCtl()
        apic.trigger(INT_HW_IO, 0x11, 0x22, 0x33, 0x44)
        self.assertTrue(apic.pending())
        self.assertTrue(apic.int_ready)
        self.assertEqual(apic.which_int, INT_HW_IO)
        self.assertEqual(
            (apic.arg0, apic.arg1, apic.arg2, apic.arg3), (0x11, 0x22, 0x33, 0x44)
        )

    def test_multiple_sources_are_queued_not_lost(self):
        # The old single-slot mailbox dropped all but the most recent trigger.
        apic = AdvProgIntCtl()
        apic.trigger(0x30, priority=0x40)
        apic.trigger(0x31, priority=0x41)
        apic.trigger(0x32, priority=0x42)

        drained = []
        while True:
            entry = apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _never)
            if entry is None:
                break
            drained.append(entry[0])
        self.assertEqual(sorted(drained), [0x30, 0x31, 0x32])
        self.assertFalse(apic.pending())

    def test_disabled_holds_maskable_interrupt(self):
        apic = AdvProgIntCtl()
        apic.trigger(INT_TIMER, priority=0x10)
        # Interrupts disabled: nothing delivered, but the source is retained.
        self.assertIsNone(apic.take_deliverable(False, FLAGS_PRIORITY_MASK, _never))
        self.assertTrue(apic.pending())
        # Once enabled it comes through.
        entry = apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _never)
        self.assertIsNotNone(entry)
        self.assertEqual(entry[0], INT_TIMER)

    def test_priority_orders_delivery_most_urgent_first(self):
        apic = AdvProgIntCtl()
        apic.trigger(0x30, priority=0x40)  # least urgent
        apic.trigger(0x31, priority=0x08)  # most urgent
        apic.trigger(0x32, priority=0x20)
        order = []
        while apic.pending():
            entry = apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _never)
            order.append((entry[0], entry[5]))
        self.assertEqual(order, [(0x31, 0x08), (0x32, 0x20), (0x30, 0x40)])

    def test_fifo_among_equal_priorities(self):
        apic = AdvProgIntCtl()
        apic.trigger(0xA0, priority=0x20)
        apic.trigger(0xA1, priority=0x20)
        apic.trigger(0xA2, priority=0x20)
        order = []
        while apic.pending():
            order.append(apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _never)[0])
        self.assertEqual(order, [0xA0, 0xA1, 0xA2])

    def test_priority_threshold_is_strict(self):
        # A pending interrupt at priority p is masked while the current priority
        # is <= p, delivered only once the current priority is strictly greater.
        apic = AdvProgIntCtl()
        apic.trigger(0x30, priority=0x40)
        self.assertIsNone(apic.take_deliverable(True, 0x40, _never))  # equal -> masked
        self.assertIsNone(apic.take_deliverable(True, 0x10, _never))  # higher -> masked
        entry = apic.take_deliverable(True, 0x41, _never)  # now eligible
        self.assertIsNotNone(entry)
        self.assertEqual(entry[0], 0x30)

    def test_nesting_preemption_by_priority(self):
        # While running at priority 0x10, a more-urgent (0x08) interrupt preempts
        # but a less-urgent (0x20) one stays masked until the level drops.
        apic = AdvProgIntCtl()
        apic.trigger(0x40, priority=0x08)
        apic.trigger(0x41, priority=0x20)
        entry = apic.take_deliverable(True, 0x10, _never)
        self.assertEqual(entry[0], 0x40)
        # 0x41 is still masked at the running level.
        self.assertIsNone(apic.take_deliverable(True, 0x10, _never))
        self.assertTrue(apic.pending())
        # After IRET lowers the level it is delivered.
        entry = apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _never)
        self.assertEqual(entry[0], 0x41)

    def test_explicit_priority_overrides_resolver(self):
        apic = AdvProgIntCtl()
        apic.trigger(INT_TIMER, priority=0x05)
        # priority_of would say 0xF0 (masked), but the pinned 0x05 wins.
        entry = apic.take_deliverable(True, 0x10, _const_priority(0xF0))
        self.assertIsNotNone(entry)
        self.assertEqual(entry[0], INT_TIMER)

    def test_unpinned_priority_uses_resolver(self):
        apic = AdvProgIntCtl()
        apic.trigger(INT_TIMER)  # no explicit priority
        self.assertIsNone(apic.take_deliverable(True, 0x10, _const_priority(0x80)))
        entry = apic.take_deliverable(True, 0x90, _const_priority(0x80))
        self.assertEqual(entry[0], INT_TIMER)

    def test_nmi_bypasses_disable(self):
        apic = AdvProgIntCtl()
        apic.trigger(INT_NMI)
        entry = apic.take_deliverable(False, 0x00, _never)  # disabled + max priority
        self.assertIsNotNone(entry)
        self.assertEqual(entry[0], INT_NMI)

    def test_nmi_bypasses_priority_mask(self):
        apic = AdvProgIntCtl()
        apic.trigger(INT_NMI)
        # cur_priority 0 would mask everything maskable; NMI still gets through.
        entry = apic.take_deliverable(True, 0x00, _never)
        self.assertEqual(entry[0], INT_NMI)

    def test_nmi_precedes_queued_maskable(self):
        apic = AdvProgIntCtl()
        apic.trigger(0x40, priority=0x01)  # very urgent maskable
        apic.trigger(INT_NMI)
        first = apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _never)
        self.assertEqual(first[0], INT_NMI)
        second = apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _never)
        self.assertEqual(second[0], 0x40)

    def test_nmi_edge_collapses_to_latest(self):
        apic = AdvProgIntCtl()
        apic.trigger(INT_NMI, 0xAA)
        apic.trigger(INT_NMI, 0xBB)
        entry = apic.take_deliverable(False, 0x00, _never)
        self.assertEqual(entry[1], 0xBB)  # latest NMI payload
        self.assertFalse(apic.pending())  # only one NMI edge pending

    def test_head_view_tracks_remaining_after_take(self):
        apic = AdvProgIntCtl()
        apic.trigger(0x30, 0xDE, priority=0x10)
        apic.trigger(0x31, 0xAD, priority=0x20)
        apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _never)  # removes 0x30
        self.assertTrue(apic.int_ready)
        self.assertEqual(apic.which_int, 0x31)
        self.assertEqual(apic.arg0, 0xAD)
        apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _never)  # removes 0x31
        self.assertFalse(apic.int_ready)
        self.assertEqual(apic.which_int, 0)


# ---------------------------------------------------------------------------
# Shared VM + ISR-table fixture
# ---------------------------------------------------------------------------
ISR_BASE = 0x4000
HANDLER_A = 0x6000
HANDLER_B = 0x6100
MARKER_A = 0x0100
MARKER_B = 0x0101


def _install_isr(vm, vec, run_flags, handler):
    base = ISR_BASE + vec * 16
    vm.memory[base : base + 8] = (run_flags & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
    vm.memory[base + 8 : base + 16] = (handler & 0xFFFFFFFFFFFFFFFF).to_bytes(
        8, "little"
    )


def _emit_marker_handler(vm, addr, marker):
    """A handler that stores 1 at *marker* (or increments it) and IRETs."""
    h = bytearray()
    emit_load_i_const(h, 1, sz_cls=0)  # push 1 (1 byte)
    h += bytes([BC_STOR, BCR_ABS_A8 | BCR_SZ_1]) + marker.to_bytes(8, "little")
    h += bytes([BC_RET_E, IRET_BYTE])
    vm.memory[addr : addr + len(h)] = h


def _make_vm(main_program, handler_priority=0x10):
    """Kernel-mode VM with an ISR table; TIMER/NMI/HW_IO -> marker handler A.

    handler_priority is the priority recorded in each ISR FLAGS entry (used both
    as the delivered-handler run level and, for unpinned sources, as the mask
    threshold via _isr_priority).
    """
    vm = VirtualMachine(0x10000, 0x4000)
    vm.sys_regs[SVSR_ISR] = ISR_BASE
    for vec in (INT_TIMER, INT_NMI, INT_HW_IO):
        _install_isr(vm, vec, handler_priority, HANDLER_A)
    _emit_marker_handler(vm, HANDLER_A, MARKER_A)
    vm.memory[0 : len(main_program)] = bytes(main_program)
    vm.ip = 0
    vm.sp = vm.bp = len(vm.memory)
    vm.running = 1
    return vm


# ---------------------------------------------------------------------------
# VM gating helper (deliver_pending_interrupt) -- no execution loop
# ---------------------------------------------------------------------------
class TestVmGatedDelivery(unittest.TestCase):
    def _vm(self, flags):
        vm = _make_vm([BC_NOP, BC_HLT])
        vm.set_flags(flags)
        return vm

    def test_enabled_enters_handler(self):
        vm = self._vm(0xFF | FLAGS_INT_ENABLE)  # priv 0, priority 255, enabled
        apic = AdvProgIntCtl()
        vm.apic = apic
        apic.trigger(INT_TIMER, 0xDEAD)
        delivered = vm.deliver_pending_interrupt(apic)
        self.assertEqual(delivered, INT_TIMER)
        self.assertEqual(vm.ip, HANDLER_A)
        # arg0 was delivered through SVSR_INT_ARG0.
        self.assertEqual(vm.sys_regs[SVSR_INT_ARG0], 0xDEAD)
        # The handler runs at the ISR-configured priority.
        self.assertEqual(vm.sys_regs[SVSR_FLAGS] & FLAGS_PRIORITY_MASK, 0x10)
        self.assertFalse(apic.pending())

    def test_disabled_does_not_enter_handler(self):
        vm = self._vm(0xFF)  # bit 14 clear
        apic = AdvProgIntCtl()
        vm.apic = apic
        apic.trigger(INT_TIMER)
        delivered = vm.deliver_pending_interrupt(apic)
        self.assertIsNone(delivered)
        self.assertEqual(vm.ip, 0)  # never jumped to handler
        self.assertTrue(apic.pending())  # still queued

    def test_enable_bit_is_bit_14(self):
        # Exactly bit 14 toggles maskable delivery; neighbouring bits must not.
        vm = self._vm(0x00FF)
        self.assertFalse(vm.sys_regs[SVSR_FLAGS] & FLAGS_INT_ENABLE)
        vm.set_flags(0x00FF | (1 << 14))
        apic = AdvProgIntCtl()
        vm.apic = apic
        apic.trigger(INT_TIMER)
        self.assertEqual(vm.deliver_pending_interrupt(apic), INT_TIMER)

    def test_isr_priority_masks_unpinned_source(self):
        # Run at priority 0x10; the TIMER's ISR-configured priority is also 0x10,
        # so an unpinned timer is masked (0x10 < 0x10 is false).
        vm = _make_vm([BC_NOP, BC_HLT], handler_priority=0x10)
        vm.set_flags(0x10 | FLAGS_INT_ENABLE)
        apic = AdvProgIntCtl()
        vm.apic = apic
        apic.trigger(INT_TIMER)  # unpinned -> resolves to ISR priority 0x10
        self.assertIsNone(vm.deliver_pending_interrupt(apic))
        self.assertTrue(apic.pending())
        # Lower the running level: now it is more urgent than current.
        vm.set_flags(0x20 | FLAGS_INT_ENABLE)
        self.assertEqual(vm.deliver_pending_interrupt(apic), INT_TIMER)

    def test_nmi_delivered_while_disabled(self):
        vm = self._vm(0x00)  # interrupts disabled, priority 0 (mask everything)
        apic = AdvProgIntCtl()
        vm.apic = apic
        apic.trigger(INT_NMI)
        self.assertEqual(vm.deliver_pending_interrupt(apic), INT_NMI)
        self.assertEqual(vm.ip, HANDLER_A)


# ---------------------------------------------------------------------------
# Full execution through execute_with_interrupts
# ---------------------------------------------------------------------------
class TestInterruptDeliveryEndToEnd(unittest.TestCase):
    def test_interrupt_serviced_when_enabled(self):
        vm = _make_vm([BC_NOP, BC_NOP, BC_HLT])
        vm.set_flags(0xFF | FLAGS_INT_ENABLE)
        apic = AdvProgIntCtl()
        vm.apic = apic
        apic.trigger(INT_TIMER)
        vm.execute_with_interrupts(apic)
        self.assertEqual(vm.memory[MARKER_A], 1)  # handler ran
        self.assertFalse(apic.pending())
        self.assertFalse(vm.running)  # main reached HLT after IRET

    def test_interrupt_held_when_disabled(self):
        vm = _make_vm([BC_NOP, BC_NOP, BC_HLT])
        vm.set_flags(0xFF)  # interrupts disabled
        apic = AdvProgIntCtl()
        vm.apic = apic
        apic.trigger(INT_TIMER)
        vm.execute_with_interrupts(apic)
        self.assertEqual(vm.memory[MARKER_A], 0)  # handler never ran
        self.assertTrue(apic.pending())  # interrupt still pending, not lost

    def test_nmi_serviced_even_when_disabled(self):
        vm = _make_vm([BC_NOP, BC_NOP, BC_HLT])
        vm.set_flags(0xFF)  # interrupts disabled
        apic = AdvProgIntCtl()
        vm.apic = apic
        apic.trigger(INT_NMI)
        vm.execute_with_interrupts(apic)
        self.assertEqual(vm.memory[MARKER_A], 1)  # NMI handler ran anyway
        self.assertFalse(apic.pending())

    def test_multiple_pending_sources_all_serviced(self):
        # Two distinct sources queued before the run; both handlers must run.
        vm = _make_vm([BC_NOP, BC_NOP, BC_NOP, BC_NOP, BC_HLT])
        _install_isr(vm, INT_HW_IO, 0x10, HANDLER_B)
        _emit_marker_handler(vm, HANDLER_B, MARKER_B)
        vm.set_flags(0xFF | FLAGS_INT_ENABLE)
        apic = AdvProgIntCtl()
        vm.apic = apic
        apic.trigger(INT_TIMER)  # -> handler A / MARKER_A
        apic.trigger(INT_HW_IO)  # -> handler B / MARKER_B
        vm.execute_with_interrupts(apic)
        self.assertEqual(vm.memory[MARKER_A], 1)
        self.assertEqual(vm.memory[MARKER_B], 1)
        self.assertFalse(apic.pending())


if __name__ == "__main__":
    unittest.main()
