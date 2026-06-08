"""Tests for the StackVM software TLB and the redesigned INVTLB shootdown family.

Covers:
  * the consulted per-core TLB (a translation is cached and stays stale until
    it is invalidated),
  * the TLPTR-switch auto-flush invariant,
  * INVTLB_LOCAL / INVTLB_SINGLE / INVTLB_MULTI bytecode (decode + pop order),
  * multi-core broadcast shootdown + TLPTR self-filtering,
  * ASYNC completion delivery via INT_TLB_SHOOTDOWN_DONE.
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
    BC_INVTLB,
    INT_TLB_SHOOTDOWN,
    INT_TLB_SHOOTDOWN_DONE,
    INVTLB_ACK,
    INVTLB_ALL_LOCAL,
    INVTLB_F_ALSO_LOCAL,
    INVTLB_F_ASYNC,
    INVTLB_F_REMOTE_INT,
    INVTLB_LOCAL,
    INVTLB_MULTI,
    INVTLB_SINGLE,
    MultiCoreController,
    SVSR_INT_ARG0,
    SVSR_INT_ARG1,
    SVSR_INT_ARG2,
    SVSR_KERNEL_TLPTR,
    SVSR_USER_TLPTR,
    TLBP_R,
    VM_4_LVL_9_BIT,
    VirtualMachine,
)
from IsaacCompiler.code_gen.stackvm_binutils.emit_load_i_const import emit_load_i_const


def _w64(vm, addr, val):
    vm.memory[addr : addr + 8] = (val & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")


def _build_paged_vm():
    """A user-mode VM with a minimal 4-level page table mapping virt 0 -> dataA.

    Returns (vm, tlpte, dataA_phys, dataB_phys); PT1[0] can be repointed from
    dataA to dataB to exercise stale-TLB behaviour.
    """
    vm = VirtualMachine(0x20000, 0)
    PT4, PT3, PT2, PT1 = 0x1000, 0x2000, 0x3000, 0x4000
    dataA, dataB = 0x5000, 0x6000
    V = 0x001  # PTE_VALID
    W = 0x002  # PTE_WRITE
    _w64(vm, PT4, PT3 | V)
    _w64(vm, PT3, PT2 | V)
    _w64(vm, PT2, PT1 | V)
    _w64(vm, PT1, dataA | V | W)
    _w64(vm, dataA, 0xAAAAAAAAAAAAAAAA)
    _w64(vm, dataB, 0xBBBBBBBBBBBBBBBB)
    tlpte = PT4 | V
    vm.priv_lvl = 1  # user space
    vm.virt_mem_mode = VM_4_LVL_9_BIT
    vm.sys_regs[SVSR_USER_TLPTR] = tlpte  # active user TLPTR (0x09)
    return vm, tlpte, dataA, dataB


class TestTlbCache(unittest.TestCase):
    def test_translation_is_cached_until_invalidated(self):
        vm, tlpte, dataA, dataB = _build_paged_vm()

        # First read walks the tables and caches (tlpte, vpn=0) -> dataA.
        self.assertEqual(vm.get(8, 0), 0xAAAAAAAAAAAAAAAA)
        self.assertIn((tlpte, 0), vm.tlb)

        # Repoint PT1[0] from dataA to dataB *behind the TLB's back*.
        _w64(vm, 0x4000, dataB | 0x001 | 0x002)

        # The stale TLB entry still resolves to dataA.
        self.assertEqual(vm.get(8, 0), 0xAAAAAAAAAAAAAAAA)

        # After invalidating the page, the next access re-walks -> dataB.
        vm.tlb_invalidate_range(tlpte, 0, 1)
        self.assertNotIn((tlpte, 0), vm.tlb)
        self.assertEqual(vm.get(8, 0), 0xBBBBBBBBBBBBBBBB)

    def test_tlptr_read_from_architectural_register(self):
        # The TLPTR must be read from SVSR_USER_TLPTR (0x09), not from
        # sys_regs[1] (ISR) / sys_regs[0] (FLAGS).  Garbage in FLAGS/ISR must not
        # affect translation.
        vm, tlpte, dataA, _dataB = _build_paged_vm()
        vm.sys_regs[0] = 0xDEADBEEF  # SVSR_FLAGS slot
        vm.sys_regs[1] = 0xCAFEF00D  # SVSR_ISR slot
        self.assertEqual(vm.active_tlptr(1), tlpte)
        self.assertEqual(vm.sys_regs[SVSR_USER_TLPTR], tlpte)
        self.assertEqual(vm.get(8, 0), 0xAAAAAAAAAAAAAAAA)

    def test_kernel_reaches_user_space_via_fallback(self):
        # vaddr_msb_eq_priv == 0: a kernel access first tries KERNEL_TLPTR, then
        # falls back to USER_TLPTR.  Here KERNEL_TLPTR is unmapped (0), so the
        # kernel must reach the user mapping via the fallback.
        vm, tlpte, dataA, _dataB = _build_paged_vm()  # USER_TLPTR maps virt 0
        vm.priv_lvl = 0
        vm.vaddr_msb_eq_priv = 0
        self.assertEqual(vm.sys_regs[SVSR_KERNEL_TLPTR], 0)  # no kernel mapping
        self.assertEqual(vm.get(8, 0), 0xAAAAAAAAAAAAAAAA)
        # The translation that resolved was the USER address space.
        self.assertIn((tlpte, 0), vm.tlb)

    def test_select_tlptrs_matches_access_tables(self):
        vm = VirtualMachine(0x1000, 0)
        K = 0x8000
        U = 0x9000
        vm.sys_regs[SVSR_KERNEL_TLPTR] = K
        vm.sys_regs[SVSR_USER_TLPTR] = U
        high = 1 << 63  # MSB set
        low = 0x1000  # MSB clear

        # vaddr_msb_eq_priv == 0: kernel tries kernel then user; user -> user.
        vm.vaddr_msb_eq_priv = 0
        self.assertEqual(vm._select_tlptrs(low, 0), (K, U))
        self.assertEqual(vm._select_tlptrs(high, 0), (K, U))
        self.assertEqual(vm._select_tlptrs(low, 1), (U,))
        self.assertEqual(vm._select_tlptrs(high, 1), (U,))

        # vaddr_msb_eq_priv == 1: the MSB selects the address space.
        vm.vaddr_msb_eq_priv = 1
        self.assertEqual(vm._select_tlptrs(low, 0), (K,))  # kernel space, kernel ok
        self.assertEqual(vm._select_tlptrs(low, 1), ())  # kernel space, user denied
        self.assertEqual(vm._select_tlptrs(high, 0), (U,))  # kernel reaches user
        self.assertEqual(vm._select_tlptrs(high, 1), (U,))  # user space, user ok

    def test_auto_flush_on_tlptr_switch(self):
        vm, tlpte, _dataA, _dataB = _build_paged_vm()
        vm.get(8, 0)  # populate (tlpte, 0)
        vm.tlb[(tlpte, 0x9000)] = [0x7000, TLBP_R]  # second entry, same TLPTR

        # Switch the active user TLPTR: entries for the old one must be evicted.
        new_tlptr = 0x12000 | 0x001
        vm.sys_regs[SVSR_USER_TLPTR] = new_tlptr
        vm._tlb_check_switch()

        self.assertFalse(any(k[0] == tlpte for k in vm.tlb))
        self.assertEqual(vm._tlb_tag[1], new_tlptr)

    def test_range_and_flush_helpers(self):
        vm = VirtualMachine(0x1000, 0)
        T = 0xABC000
        for vpn in (0x0000, 0x1000, 0x2000, 0x3000):
            vm.tlb[(T, vpn)] = [0, TLBP_R]
        vm.tlb[(0xDEF000, 0x0000)] = [0, TLBP_R]  # different TLPTR, must survive

        vm.tlb_invalidate_range(T, 0x1000, 2)  # remove vpn 0x1000 and 0x2000
        self.assertIn((T, 0x0000), vm.tlb)
        self.assertNotIn((T, 0x1000), vm.tlb)
        self.assertNotIn((T, 0x2000), vm.tlb)
        self.assertIn((T, 0x3000), vm.tlb)

        vm.tlb_flush_tlptr(T)
        self.assertFalse(any(k[0] == T for k in vm.tlb))
        self.assertIn((0xDEF000, 0x0000), vm.tlb)  # other TLPTR untouched

        vm.tlb_flush_all()
        self.assertEqual(len(vm.tlb), 0)


def _make_two_cores():
    ctrl = MultiCoreController()
    c0 = VirtualMachine(0x4000, 0)
    c1 = VirtualMachine(0x4000, 0)
    c0.set_core_id(0)
    c1.set_core_id(1)
    ctrl.add_core(c0)
    ctrl.add_core(c1)
    return ctrl, c0, c1


class TestTlbShootdownMultiCore(unittest.TestCase):
    def test_broadcast_invalidates_sibling(self):
        ctrl, c0, c1 = _make_two_cores()
        T = 0x100000
        c0.sys_regs[SVSR_USER_TLPTR] = T  # both cores have T active (user)
        c1.sys_regs[SVSR_USER_TLPTR] = T
        c0.tlb[(T, 0)] = [0x9000, TLBP_R]
        c1.tlb[(T, 0)] = [0x9000, TLBP_R]

        # SYNC broadcast + also-local from core 0.
        c0.tlb_shootdown([(T, 0, 1)], INVTLB_F_ALSO_LOCAL, None)

        self.assertNotIn((T, 0), c0.tlb)
        self.assertNotIn((T, 0), c1.tlb)

    def test_self_filter_ignores_inactive_tlptr(self):
        ctrl, c0, c1 = _make_two_cores()
        T = 0x100000
        OTHER = 0x200000
        c0.sys_regs[SVSR_USER_TLPTR] = T
        c1.sys_regs[SVSR_USER_TLPTR] = OTHER  # core 1 does not have T active
        c1.tlb[(OTHER, 0)] = [0x9000, TLBP_R]

        self.assertFalse(c1.tlb_has_tlptr(T))
        c0.tlb_shootdown([(T, 0, 1)], 0, None)  # broadcast for T

        # Core 1's entry (different TLPTR) must survive.
        self.assertIn((OTHER, 0), c1.tlb)

    def test_async_completion_to_self(self):
        ctrl, c0, c1 = _make_two_cores()
        T = 0x100000
        c0.sys_regs[SVSR_USER_TLPTR] = T
        c1.sys_regs[SVSR_USER_TLPTR] = T
        c0.apic = AdvProgIntCtl()

        # ASYNC broadcast completes immediately (broadcast is synchronous in the
        # emulator) and posts INT_TLB_SHOOTDOWN_DONE to the issuer.
        c0.tlb_shootdown([(T, 0x4000, 1)], INVTLB_F_ASYNC, done_core=0)

        self.assertTrue(c0.apic.int_ready)
        self.assertEqual(c0.apic.which_int, INT_TLB_SHOOTDOWN_DONE)
        self.assertEqual(c0.apic.arg0, T)  # tlptr
        self.assertEqual(c0.apic.arg1, 0x4000)  # base
        self.assertEqual(c0.apic.arg2, 1)  # page_count

    def test_async_completion_to_other_core(self):
        ctrl, c0, c1 = _make_two_cores()
        T = 0x100000
        c0.sys_regs[SVSR_USER_TLPTR] = T
        c1.sys_regs[SVSR_USER_TLPTR] = T
        c1.apic = AdvProgIntCtl()

        c0.tlb_shootdown([(T, 0, 1)], INVTLB_F_ASYNC, done_core=1)

        self.assertTrue(c1.apic.int_ready)
        self.assertEqual(c1.apic.which_int, INT_TLB_SHOOTDOWN_DONE)


class TestInvtlbBytecode(unittest.TestCase):
    def _run(self, vm, prog):
        vm.load_program(bytearray(prog), 0)
        vm.priv_lvl = 0  # INVTLB is kernel-only
        vm.ip = 0
        vm.execute()

    def test_invtlb_single_also_local(self):
        vm = VirtualMachine(0x4000, 0)
        T = 0x100000
        vm.tlb[(T, 0)] = [0x9000, TLBP_R]
        prog = bytearray()
        emit_load_i_const(prog, T, sz_cls=3)  # tlptr  (bottom, 8-byte)
        emit_load_i_const(prog, 0, sz_cls=3)  # vaddr_base
        emit_load_i_const(prog, 1, sz_cls=3)  # page_count (top)
        prog += bytes([BC_INVTLB, INVTLB_SINGLE, INVTLB_F_ALSO_LOCAL])
        prog += bytes([BC_HLT])
        self._run(vm, prog)
        self.assertNotIn((T, 0), vm.tlb)

    def test_invtlb_local(self):
        vm = VirtualMachine(0x4000, 0)
        T = 0x100000
        vm.tlb[(T, 0)] = [0x9000, TLBP_R]
        vm.tlb[(T, 0x1000)] = [0xA000, TLBP_R]
        prog = bytearray()
        emit_load_i_const(prog, T, sz_cls=3)  # tlptr
        emit_load_i_const(prog, 0, sz_cls=3)  # base
        emit_load_i_const(prog, 2, sz_cls=3)  # count (2 pages)
        prog += bytes([BC_INVTLB, INVTLB_LOCAL])
        prog += bytes([BC_HLT])
        self._run(vm, prog)
        self.assertNotIn((T, 0), vm.tlb)
        self.assertNotIn((T, 0x1000), vm.tlb)

    def test_invtlb_multi_reads_entry_array(self):
        ctrl, c0, c1 = _make_two_cores()
        Ta, Tb = 0x100000, 0x300000
        # core 1 has both address spaces' entries present and active.
        c1.sys_regs[SVSR_KERNEL_TLPTR] = Ta
        c1.sys_regs[SVSR_USER_TLPTR] = Tb
        c1.tlb[(Ta, 0)] = [0x9000, TLBP_R]
        c1.tlb[(Tb, 0)] = [0xA000, TLBP_R]
        c0.tlb[(Ta, 0)] = [0x9000, TLBP_R]
        c0.tlb[(Tb, 0)] = [0xA000, TLBP_R]

        E = 0x800  # entry array (physical; VM is disabled here)
        _w64(c0, E + 0, Ta)
        _w64(c0, E + 8, 0)
        _w64(c0, E + 16, 1)
        _w64(c0, E + 24, Tb)
        _w64(c0, E + 32, 0)
        _w64(c0, E + 40, 1)

        prog = bytearray()
        emit_load_i_const(prog, E, sz_cls=3)  # entry_ptr (bottom)
        emit_load_i_const(prog, 2, sz_cls=3)  # num_entries (top)
        prog += bytes([BC_INVTLB, INVTLB_MULTI, INVTLB_F_ALSO_LOCAL])
        prog += bytes([BC_HLT])
        c0.load_program(bytearray(prog), 0)
        c0.priv_lvl = 0
        c0.ip = 0
        c0.execute()

        # Both descriptors invalidated on the issuer (also-local) and the sibling.
        self.assertNotIn((Ta, 0), c0.tlb)
        self.assertNotIn((Tb, 0), c0.tlb)
        self.assertNotIn((Ta, 0), c1.tlb)
        self.assertNotIn((Tb, 0), c1.tlb)


def _make_n_cores(n):
    ctrl = MultiCoreController()
    cores = []
    for i in range(n):
        c = VirtualMachine(0x4000, 0)
        c.set_core_id(i)
        c.apic = AdvProgIntCtl()
        ctrl.add_core(c)
        cores.append(c)
    return ctrl, cores


class TestTlbShootdownRemoteInt(unittest.TestCase):
    """The REMOTE_INT fallback: instead of a silent hardware broadcast, matching
    cores are interrupted with INT_TLB_SHOOTDOWN and acknowledge via INVTLB_ACK,
    which the bus routes back to the issuer to complete the (async) shootdown."""

    def test_remote_int_async_pends_until_ack(self):
        ctrl, (c0, c1) = _make_n_cores(2)
        T = 0x100000
        c0.sys_regs[SVSR_USER_TLPTR] = T
        c1.sys_regs[SVSR_USER_TLPTR] = T  # c1 has T active -> matches

        c0.tlb_shootdown(
            [(T, 0x2000, 1)], INVTLB_F_ASYNC | INVTLB_F_REMOTE_INT, done_core=0
        )

        # The sibling received the request interrupt carrying the descriptor and
        # the shootdown handle (arg3); the issuer is NOT done until it is acked.
        self.assertTrue(c1.apic.int_ready)
        self.assertEqual(c1.apic.which_int, INT_TLB_SHOOTDOWN)
        self.assertEqual(c1.apic.arg0, T)
        self.assertEqual(c1.apic.arg1, 0x2000)
        self.assertEqual(c1.apic.arg2, 1)
        handle = c1.apic.arg3
        self.assertFalse(c0.apic.int_ready)  # completion gated on the ack

        # The sibling acknowledges -> the issuer gets INT_TLB_SHOOTDOWN_DONE.
        ctrl.tlb_ack(handle)
        self.assertTrue(c0.apic.int_ready)
        self.assertEqual(c0.apic.which_int, INT_TLB_SHOOTDOWN_DONE)
        self.assertEqual(c0.apic.arg0, T)
        self.assertEqual(c0.apic.arg1, 0x2000)

    def test_remote_int_async_completes_immediately_when_no_match(self):
        ctrl, (c0, c1) = _make_n_cores(2)
        T = 0x100000
        OTHER = 0x999000
        c0.sys_regs[SVSR_USER_TLPTR] = T
        c1.sys_regs[SVSR_USER_TLPTR] = OTHER  # c1 does NOT have T active

        c0.tlb_shootdown(
            [(T, 0, 1)], INVTLB_F_ASYNC | INVTLB_F_REMOTE_INT, done_core=0
        )

        # No core owed an ack, so completion is immediate and the non-matching
        # sibling was never interrupted.
        self.assertFalse(c1.apic.int_ready)
        self.assertTrue(c0.apic.int_ready)
        self.assertEqual(c0.apic.which_int, INT_TLB_SHOOTDOWN_DONE)

    def test_remote_int_async_waits_for_all_matching_acks(self):
        ctrl, (c0, c1, c2) = _make_n_cores(3)
        T = 0x100000
        for c in (c0, c1, c2):
            c.sys_regs[SVSR_USER_TLPTR] = T  # all three share T

        c0.tlb_shootdown(
            [(T, 0, 1)], INVTLB_F_ASYNC | INVTLB_F_REMOTE_INT, done_core=0
        )

        h1 = c1.apic.arg3
        h2 = c2.apic.arg3
        self.assertEqual(h1, h2)  # one handle for the whole shootdown
        self.assertFalse(c0.apic.int_ready)

        ctrl.tlb_ack(h1)
        self.assertFalse(c0.apic.int_ready)  # still one ack outstanding
        ctrl.tlb_ack(h2)
        self.assertTrue(c0.apic.int_ready)  # last ack completes it
        self.assertEqual(c0.apic.which_int, INT_TLB_SHOOTDOWN_DONE)

    def test_remote_int_sync_invalidates_and_posts_observability(self):
        ctrl, (c0, c1) = _make_n_cores(2)
        T = 0x100000
        c0.sys_regs[SVSR_USER_TLPTR] = T
        c1.sys_regs[SVSR_USER_TLPTR] = T
        c1.tlb[(T, 0)] = [0x9000, TLBP_R]

        # SYNC + REMOTE_INT: the sibling TLB is invalidated directly (broadcast)
        # AND a request interrupt is posted for observability, with no ack gating.
        c0.tlb_shootdown([(T, 0, 1)], INVTLB_F_REMOTE_INT, done_core=None)

        self.assertNotIn((T, 0), c1.tlb)  # invalidated directly
        self.assertTrue(c1.apic.int_ready)
        self.assertEqual(c1.apic.which_int, INT_TLB_SHOOTDOWN)


class TestInvtlbBytecodeShootdownPaths(unittest.TestCase):
    """Bytecode-level coverage of the INVTLB sub-ops the original suite skipped:
    ALL_LOCAL, the ASYNC (done_core-popping) form of SINGLE, and ACK routing."""

    def _run(self, vm, prog):
        vm.load_program(bytearray(prog), 0)
        vm.priv_lvl = 0  # INVTLB is kernel-only
        vm.ip = 0
        vm.execute()

    def test_invtlb_all_local_bytecode(self):
        vm = VirtualMachine(0x4000, 0)
        T = 0x100000
        vm.tlb[(T, 0)] = [0x9000, TLBP_R]
        vm.tlb[(T, 0x1000)] = [0xA000, TLBP_R]
        vm.tlb[(0x222000, 0)] = [0xB000, TLBP_R]
        prog = bytearray([BC_INVTLB, INVTLB_ALL_LOCAL, BC_HLT])
        self._run(vm, prog)
        self.assertEqual(len(vm.tlb), 0)

    def test_invtlb_single_async_bytecode_broadcast_completes(self):
        ctrl, (c0, c1) = _make_n_cores(2)
        T = 0x100000
        c0.sys_regs[SVSR_USER_TLPTR] = T
        c1.sys_regs[SVSR_USER_TLPTR] = T
        c1.tlb[(T, 0)] = [0x9000, TLBP_R]

        # SINGLE + ASYNC + ALSO_LOCAL via bytecode.  pop order is
        # done_core, count, base, tlptr -> push tlptr, base, count, done_core.
        prog = bytearray()
        emit_load_i_const(prog, T, sz_cls=3)  # tlptr (bottom)
        emit_load_i_const(prog, 0, sz_cls=3)  # base
        emit_load_i_const(prog, 1, sz_cls=3)  # count
        emit_load_i_const(prog, 0, sz_cls=3)  # done_core (top)
        prog += bytes(
            [BC_INVTLB, INVTLB_SINGLE, INVTLB_F_ASYNC | INVTLB_F_ALSO_LOCAL]
        )
        prog += bytes([BC_HLT])
        self._run(c0, prog)

        # Broadcast invalidated the sibling, and the broadcast path completes
        # synchronously in the emulator.  execute() runs with apic disarmed
        # (self.apic = None), so the async completion lands in the ipi_log
        # fallback rather than an interrupt mailbox -- carrying the descriptor.
        self.assertNotIn((T, 0), c1.tlb)
        self.assertIn(("tlb_done", 0, T, 0, 1, 0), c0.ipi_log)

    def test_invtlb_ack_bytecode_routes_completion(self):
        ctrl, (c0, c1) = _make_n_cores(2)
        T = 0x100000
        c0.sys_regs[SVSR_USER_TLPTR] = T
        c1.sys_regs[SVSR_USER_TLPTR] = T

        # Issue a remote-int async shootdown; c1 receives the handle, c0 waits.
        c0.tlb_shootdown(
            [(T, 0, 1)], INVTLB_F_ASYNC | INVTLB_F_REMOTE_INT, done_core=0
        )
        handle = c1.apic.arg3
        self.assertFalse(c0.apic.int_ready)

        # c1 acknowledges by *executing* INVTLB_ACK on the handle.
        prog = bytearray()
        emit_load_i_const(prog, handle, sz_cls=3)
        prog += bytes([BC_INVTLB, INVTLB_ACK, BC_HLT])
        self._run(c1, prog)

        self.assertTrue(c0.apic.int_ready)
        self.assertEqual(c0.apic.which_int, INT_TLB_SHOOTDOWN_DONE)


if __name__ == "__main__":
    unittest.main()
