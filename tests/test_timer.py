"""Tests for D3 -- the programmable interval timer and SVSR_CYCLE_COUNT.

D3 adds a programmable interval timer (ProgrammableIntervalTimer) that drives
the scheduler tick: its timebase is the core's retired-instruction count, the
VM increments the read-only SVSR_CYCLE_COUNT register (0x0C) once per retired
instruction, and the timer posts INT_TIMER (0x11) into the per-core APIC every
`interval` cycles where it is then subject to the normal FLAGS enable/priority
gating from D2.

These tests cover the timer in isolation, the cycle counter, and end-to-end
delivery through execute_with_interrupts (serviced when enabled, held pending
when disabled, and repeated ticks as a scheduler would see them).
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
    BC_ADD1,
    BC_HLT,
    BC_LOAD,
    BC_NOP,
    BC_RET_E,
    BC_STOR,
    BCRE_IS_INT,
    BCR_ABS_A8,
    BCR_SZ_1,
    FLAGS_INT_ENABLE,
    FLAGS_PRIORITY_MASK,
    INT_TIMER,
    ProgrammableIntervalTimer,
    SVSR_CYCLE_COUNT,
    SVSR_FLAGS,
    SVSR_ISR,
    VirtualMachine,
)
from IsaacCompiler.code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const

UINT64_MAX = 0xFFFFFFFFFFFFFFFF

# IRET = RET_E with IS_SYS (0x80) | IS_INT (BCRE_IS_INT).
IRET_BYTE = 0x80 | BCRE_IS_INT


def _resolve(value):
    return lambda _int_n: value


# ---------------------------------------------------------------------------
# Timer in isolation (no VM)
# ---------------------------------------------------------------------------
class TestProgrammableIntervalTimer(unittest.TestCase):
    def test_unprogrammed_timer_is_idle(self):
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(apic)
        # interval 0 / disabled by default: ticking does nothing.
        for _ in range(100):
            self.assertEqual(timer.tick(), 0)
        self.assertFalse(apic.pending())
        self.assertEqual(timer.fire_count, 0)
        self.assertEqual(timer.remaining, 0)

    def test_disabled_even_with_interval_does_nothing(self):
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(apic, interval=4, enabled=False)
        self.assertFalse(timer.enabled)
        for _ in range(20):
            timer.tick()
        self.assertFalse(apic.pending())
        self.assertEqual(timer.fire_count, 0)

    def test_periodic_fires_every_interval(self):
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(apic, interval=4, enabled=True)
        # No fire for the first interval-1 ticks.
        for _ in range(3):
            self.assertEqual(timer.tick(), 0)
        self.assertEqual(timer.remaining, 1)
        # The 4th tick crosses the boundary.
        self.assertEqual(timer.tick(), 1)
        self.assertEqual(timer.fire_count, 1)
        self.assertTrue(apic.pending())
        self.assertEqual(apic.which_int, INT_TIMER)
        # It reloads and fires again 4 ticks later.
        for _ in range(3):
            self.assertEqual(timer.tick(), 0)
        self.assertEqual(timer.tick(), 1)
        self.assertEqual(timer.fire_count, 2)

    def test_periodic_fire_count_over_many_cycles(self):
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(apic, interval=5, enabled=True)
        for _ in range(53):
            timer.tick()
        self.assertEqual(timer.fire_count, 53 // 5)

    def test_one_shot_fires_once_then_disarms(self):
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(
            apic, interval=3, periodic=False, enabled=True
        )
        for _ in range(2):
            self.assertEqual(timer.tick(), 0)
        self.assertEqual(timer.tick(), 1)  # fires on the 3rd tick
        self.assertEqual(timer.fire_count, 1)
        self.assertFalse(timer.enabled)  # disarmed
        # Further ticks never fire again.
        for _ in range(10):
            self.assertEqual(timer.tick(), 0)
        self.assertEqual(timer.fire_count, 1)

    def test_one_shot_rearm(self):
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(
            apic, interval=2, periodic=False, enabled=True
        )
        timer.tick()
        timer.tick()  # fires, disarms
        self.assertEqual(timer.fire_count, 1)
        self.assertFalse(timer.enabled)
        timer.arm()  # re-arm without reprogramming
        self.assertTrue(timer.enabled)
        self.assertEqual(timer.remaining, 2)
        timer.tick()
        timer.tick()
        self.assertEqual(timer.fire_count, 2)

    def test_disable_then_reenable_via_program(self):
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(apic, interval=4, enabled=True)
        timer.tick()
        timer.disable()
        self.assertFalse(timer.enabled)
        for _ in range(20):
            timer.tick()
        self.assertEqual(timer.fire_count, 0)
        self.assertFalse(apic.pending())
        # Reprogram with a new interval resets the countdown.
        timer.program(2, enabled=True)
        self.assertTrue(timer.enabled)
        self.assertEqual(timer.remaining, 2)
        timer.tick()
        timer.tick()
        self.assertEqual(timer.fire_count, 1)

    def test_large_step_crosses_multiple_boundaries(self):
        # A single large tick(cycles) posts one interrupt per boundary crossed.
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(apic, interval=4, enabled=True)
        posted = timer.tick(10)  # crosses boundaries at 4 and 8
        self.assertEqual(posted, 2)
        self.assertEqual(timer.fire_count, 2)
        self.assertEqual(timer.remaining, 2)  # 12 - 10 left until next

    def test_pinned_priority_is_delivered(self):
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(
            apic, interval=1, enabled=True, priority=0x07
        )
        timer.tick()
        entry = apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _resolve(0xF0))
        self.assertEqual(entry[0], INT_TIMER)
        self.assertEqual(entry[5], 0x07)  # pinned priority survives

    def test_unpinned_priority_defers_to_resolver(self):
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(apic, interval=1, enabled=True)
        timer.tick()
        # No pinned priority -> entry priority is None, resolved at delivery time.
        entry = apic.take_deliverable(True, FLAGS_PRIORITY_MASK, _resolve(0x20))
        self.assertEqual(entry[0], INT_TIMER)
        self.assertIsNone(entry[5])


# ---------------------------------------------------------------------------
# SVSR_CYCLE_COUNT
# ---------------------------------------------------------------------------
class TestCycleCounter(unittest.TestCase):
    def _make_vm(self, program):
        vm = VirtualMachine(0x1000, 0x400)
        vm.memory[0 : len(program)] = bytes(program)
        vm.ip = 0
        vm.sp = vm.bp = len(vm.memory)
        vm.running = 1
        return vm

    def test_cycle_count_increments_per_instruction(self):
        # NOP, NOP, HLT -> 3 retired instructions (HLT counts as retired).
        vm = self._make_vm([BC_NOP, BC_NOP, BC_HLT])
        self.assertEqual(vm.sys_regs[SVSR_CYCLE_COUNT], 0)
        apic = AdvProgIntCtl()
        vm.execute_with_interrupts(apic)
        self.assertEqual(vm.sys_regs[SVSR_CYCLE_COUNT], 3)

    def test_step_increments_cycle_count(self):
        vm = self._make_vm([BC_NOP, BC_NOP, BC_NOP, BC_HLT])
        vm.step()
        self.assertEqual(vm.sys_regs[SVSR_CYCLE_COUNT], 1)
        vm.step()
        self.assertEqual(vm.sys_regs[SVSR_CYCLE_COUNT], 2)

    def test_cycle_count_wraps_on_overflow(self):
        vm = self._make_vm([BC_NOP, BC_HLT])
        vm.sys_regs[SVSR_CYCLE_COUNT] = UINT64_MAX
        vm.step()  # one NOP
        self.assertEqual(vm.sys_regs[SVSR_CYCLE_COUNT], 0)


# ---------------------------------------------------------------------------
# End-to-end: timer interrupts serviced through execute_with_interrupts
# ---------------------------------------------------------------------------
ISR_BASE = 0x4000
HANDLER = 0x6000
TICK_COUNT = 0x3000  # 1-byte counter the ISR increments (clear of code/ISR/stack)


def _install_isr(vm, vec, run_flags, handler):
    base = ISR_BASE + vec * 16
    vm.memory[base : base + 8] = (run_flags & UINT64_MAX).to_bytes(8, "little")
    vm.memory[base + 8 : base + 16] = (handler & UINT64_MAX).to_bytes(8, "little")


def _emit_increment_handler(vm, addr, counter):
    """ISR that does counter += 1 (1-byte, wrapping) and IRETs."""
    h = bytearray()
    h += bytes([BC_LOAD, BCR_ABS_A8 | BCR_SZ_1]) + counter.to_bytes(8, "little")
    emit_load_i_const(h, 1, sz_cls=0)  # push 1
    h += bytes([BC_ADD1])  # counter_value + 1
    h += bytes([BC_STOR, BCR_ABS_A8 | BCR_SZ_1]) + counter.to_bytes(8, "little")
    h += bytes([BC_RET_E, IRET_BYTE])
    vm.memory[addr : addr + len(h)] = h


def _make_timer_vm(main_program, handler_priority=0x10):
    """Kernel-mode VM with an INT_TIMER ISR that increments TICK_COUNT."""
    vm = VirtualMachine(0x10000, 0x4000)
    vm.sys_regs[SVSR_ISR] = ISR_BASE
    _install_isr(vm, INT_TIMER, handler_priority, HANDLER)
    _emit_increment_handler(vm, HANDLER, TICK_COUNT)
    vm.memory[0 : len(main_program)] = bytes(main_program)
    vm.ip = 0
    vm.sp = vm.bp = len(vm.memory)
    vm.running = 1
    return vm


class TestTimerEndToEnd(unittest.TestCase):
    def test_timer_interrupt_serviced_when_enabled(self):
        # Run a stretch of NOPs so the timer fires before HLT.
        vm = _make_timer_vm([BC_NOP] * 40 + [BC_HLT])
        vm.set_flags(0xFF | FLAGS_INT_ENABLE)
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(apic, interval=8, enabled=True)
        vm.execute_with_interrupts(apic, timer)
        # The handler ran at least once and the timer posted at least once.
        self.assertGreaterEqual(vm.memory[TICK_COUNT], 1)
        self.assertGreaterEqual(timer.fire_count, 1)
        # The cycle counter advanced past the program length.
        self.assertGreater(vm.sys_regs[SVSR_CYCLE_COUNT], 40)

    def test_timer_held_pending_when_interrupts_disabled(self):
        vm = _make_timer_vm([BC_NOP] * 40 + [BC_HLT])
        vm.set_flags(0xFF)  # interrupts disabled (bit 14 clear)
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(apic, interval=8, enabled=True)
        vm.execute_with_interrupts(apic, timer)
        # The timer fired (posts happened) but no handler ran...
        self.assertGreaterEqual(timer.fire_count, 1)
        self.assertEqual(vm.memory[TICK_COUNT], 0)
        # ...and the timer interrupt is still pending, not lost.
        self.assertTrue(apic.pending())
        self.assertEqual(apic.which_int, INT_TIMER)

    def test_pending_timer_serviced_after_reenable(self):
        # Held while disabled, then delivered once interrupts are enabled.
        vm = _make_timer_vm([BC_NOP, BC_HLT])
        vm.set_flags(0xFF)  # disabled
        apic = AdvProgIntCtl()
        vm.apic = apic
        timer = ProgrammableIntervalTimer(apic, interval=1, enabled=True)
        timer.tick()  # post one INT_TIMER directly
        self.assertIsNone(vm.deliver_pending_interrupt(apic))  # masked
        self.assertEqual(vm.memory[TICK_COUNT], 0)
        vm.set_flags(0xFF | FLAGS_INT_ENABLE)  # enable
        self.assertEqual(vm.deliver_pending_interrupt(apic), INT_TIMER)
        self.assertEqual(vm.ip, HANDLER)

    def test_repeated_ticks_drive_repeated_service(self):
        # A long NOP sled (BC_NOP == 0, so the zero-initialised region is already
        # a NOP stream) terminated by HLT runs long enough for many timer ticks;
        # the ISR bumps a counter each time, exactly as a scheduler tick would.
        # interval (16) comfortably exceeds the 5-instruction ISR so the main
        # program keeps making forward progress between ticks and reaches HLT.
        vm = _make_timer_vm([BC_NOP] * 300 + [BC_HLT])
        vm.set_flags(0xFF | FLAGS_INT_ENABLE)
        apic = AdvProgIntCtl()
        timer = ProgrammableIntervalTimer(apic, interval=16, enabled=True)
        vm.execute_with_interrupts(apic, timer)
        # The timer fired many times and the ISR was serviced repeatedly (the
        # 1-byte counter stays in range -- far fewer than 256 services).
        self.assertGreaterEqual(timer.fire_count, 10)
        self.assertGreaterEqual(vm.memory[TICK_COUNT], 5)
        self.assertFalse(vm.running)  # main reached HLT


if __name__ == "__main__":
    unittest.main()
