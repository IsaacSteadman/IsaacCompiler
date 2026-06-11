"""Tests for the E2 phased boot/runtime milestones (Workstream E3).

Each milestone is a checked-in mini-kernel image that proves one platform
capability end-to-end on the Python reference VM (see StackVM/milestones.py and
the boot ABI in StackVM/Documentation/BootAbi.html).  These tests run every
milestone and assert both the overall pass flag and the capability-specific
invariants the plan calls out:

  * timer fires + interrupt gating honours enable/priority (M2);
  * page-fault delivery + demand-mapping under an enabled MMU (M3);
  * MMIO UART console output (M4);
  * virtio-blk block read/write with persistence (M6);
  * IPI + TLB shootdown between cores (M7);
  * virtio-net TX/RX (M8).

Milestone 1 additionally exercises the toolchain end-to-end: a freestanding C
program is compiled to a StackVM ELF (vmlinux) and inspected with the host
binutils CLIs (readelf/nm/objcopy/kallsyms).
"""

import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.milestones import (
    MILESTONES,
    run_all_milestones,
    run_milestone,
)


def _run_cli(*argv, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "IsaacCompiler", *argv],
        cwd=REPO_PARENT if cwd is None else cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": REPO_PARENT},
    )


def _run_stackvm_cli(*argv):
    return subprocess.run(
        [sys.executable, "-m", "IsaacCompiler.StackVM", *argv],
        cwd=REPO_PARENT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": REPO_PARENT},
    )


class MilestonePassTests(unittest.TestCase):
    """Every milestone runs and passes."""

    def test_all_eight_milestones_pass(self):
        results = run_all_milestones()
        self.assertEqual([r.number for r in results], list(range(1, 9)))
        failures = [str(r) for r in results if not r.passed]
        self.assertEqual(failures, [], msg="failing milestones: %s" % failures)

    def test_run_milestone_rejects_unknown(self):
        with self.assertRaises(ValueError):
            run_milestone(99)
        self.assertEqual(sorted(MILESTONES), list(range(1, 9)))


class Milestone1Tests(unittest.TestCase):
    def test_boots_and_prints_via_paravirt_console(self):
        result = run_milestone(1)
        self.assertTrue(result.passed, msg=result.detail)
        self.assertEqual(result.detail["console"], b"Hello from StackVM milestone 1\n")
        self.assertTrue(result.detail["startupdata_valid"])
        self.assertEqual(result.detail["entry_priv"], 0)
        self.assertTrue(result.detail["mmu_off"])

    def test_toolchain_builds_freestanding_elf(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "mini_kernel.c")
            with open(src, "w") as fl:
                fl.write(
                    "static int acc;\n"
                    "int kmain(int x) { for (int i = 0; i < x; i++) acc += i; return acc; }\n"
                    "int main(int argc, char **argv) { return kmain(argc); }\n"
                )
            vmlinux = os.path.join(tmp, "vmlinux")

            compile_proc = _run_cli(src, "-o", vmlinux)
            self.assertEqual(compile_proc.returncode, 0, msg=compile_proc.stderr)
            self.assertTrue(os.path.exists(vmlinux))

            # readelf identifies it as a StackVM ELF64 executable.
            readelf = _run_cli("readelf", "-h", "-S", vmlinux)
            self.assertEqual(readelf.returncode, 0, msg=readelf.stderr)
            self.assertIn("ELF Header:", readelf.stdout)
            self.assertIn("StackVM", readelf.stdout)
            self.assertIn("EXEC (Executable file)", readelf.stdout)

            # nm and kallsyms run cleanly over the linked image.
            self.assertEqual(_run_cli("nm", vmlinux).returncode, 0)
            kallsyms = _run_cli("kallsyms", vmlinux)
            self.assertEqual(kallsyms.returncode, 0, msg=kallsyms.stderr)
            self.assertIn("kallsyms_num_syms", kallsyms.stdout)

            # objcopy extracts a flat boot image from the ELF.
            flat = os.path.join(tmp, "flat.bin")
            objcopy = _run_cli("objcopy", "-O", "binary", vmlinux, flat)
            self.assertEqual(objcopy.returncode, 0, msg=objcopy.stderr)
            self.assertGreater(os.path.getsize(flat), 0)


class Milestone2Tests(unittest.TestCase):
    def test_timer_serviced_when_enabled_held_when_disabled(self):
        result = run_milestone(2)
        self.assertTrue(result.passed, msg=result.detail)
        self.assertGreaterEqual(result.detail["ticks_when_enabled"], 1)
        self.assertGreaterEqual(result.detail["fires_when_enabled"], 1)
        # Disabled: the timer still fired but nothing was serviced, and the
        # interrupt is held pending rather than lost.
        self.assertEqual(result.detail["ticks_when_disabled"], 0)
        self.assertTrue(result.detail["pending_when_disabled"])


class Milestone3Tests(unittest.TestCase):
    def test_page_fault_delivered_and_demand_mapped(self):
        result = run_milestone(3)
        self.assertTrue(result.passed, msg=result.detail)
        self.assertEqual(result.detail["faults_delivered"], 1)
        self.assertEqual(result.detail["fault_addr"], 0x200000)
        self.assertTrue(result.detail["value_roundtrip"])
        self.assertTrue(result.detail["backing_frame_written"])


class Milestone4Tests(unittest.TestCase):
    def test_uart_console_output(self):
        result = run_milestone(4)
        self.assertTrue(result.passed, msg=result.detail)
        self.assertIn(b"StackVM: early console online", result.detail["output"])
        self.assertTrue(result.detail["tx_ready"])


class Milestone5Tests(unittest.TestCase):
    def test_initramfs_located_and_entered(self):
        result = run_milestone(5)
        self.assertTrue(result.passed, msg=result.detail)
        self.assertEqual(
            result.detail["initramfs_base_read"],
            result.detail["initramfs_base_expected"],
        )
        self.assertEqual(result.detail["console"], b"init: /bin/sh started\n")


class Milestone6Tests(unittest.TestCase):
    def test_block_write_read_and_persistence(self):
        result = run_milestone(6)
        self.assertTrue(result.passed, msg=result.detail)
        self.assertTrue(result.detail["wrote_ok"])
        self.assertTrue(result.detail["read_ok"])
        self.assertTrue(result.detail["persisted"])
        self.assertEqual(result.detail["read_back"], b"persistent-rootfs-superblock")


class Milestone7Tests(unittest.TestCase):
    def test_ipi_and_tlb_shootdown_between_cores(self):
        result = run_milestone(7)
        self.assertTrue(result.passed, msg=result.detail)
        self.assertTrue(result.detail["ipi_serviced"])
        self.assertTrue(result.detail["shootdown_serviced_and_acked"])


class Milestone8Tests(unittest.TestCase):
    def test_net_tx_and_rx(self):
        result = run_milestone(8)
        self.assertTrue(result.passed, msg=result.detail)
        self.assertTrue(result.detail["tx_ok"])
        self.assertTrue(result.detail["rx_ok"])
        self.assertEqual(result.detail["tx_packets"], [b"hello-net"])
        self.assertEqual(result.detail["rx_data"], b"frame-from-the-wire")


class MilestoneCliTests(unittest.TestCase):
    def test_cli_runs_all_milestones(self):
        proc = _run_stackvm_cli("milestones")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("8/8 milestones passed", proc.stdout)

    def test_cli_runs_single_milestone(self):
        proc = _run_stackvm_cli("milestones", "1")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("milestone 1", proc.stdout)
        self.assertIn("1/1 milestones passed", proc.stdout)


if __name__ == "__main__":
    unittest.main()
