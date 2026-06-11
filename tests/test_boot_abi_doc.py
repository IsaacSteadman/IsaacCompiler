"""Tests for the E1 Boot ABI document (StackVM/Documentation/BootAbi.html).

The document is meant to be the consolidated boot *contract* an out-of-tree
kernel port targets.  To keep it from rotting into stale prose, this test pins
the concrete numeric constants it publishes to the authoritative definitions in
the code, so changing a constant without updating the document fails CI.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.boot import (
    MEM_MAP_ENTRY_SIZE,
    STARTUP_DATA_SIZE,
    SVMEM_BOOTDATA,
    SVMEM_INITRAMFS,
    SVMEM_KERNEL,
    SVMEM_RAM,
    SVMEM_RESERVED,
    SVSD_FLAG_DTB,
    SVSD_MAGIC,
    SVSD_VERSION,
)
from IsaacCompiler.StackVM.mmio import (
    SVM_IRQ_RTC,
    SVM_IRQ_UART0,
    SVM_IRQ_VIRTIO_BLK0,
    SVM_IRQ_VIRTIO_NET0,
    SVM_MMIO_BASE,
    SVM_MMIO_IC_BASE,
    SVM_MMIO_RTC_BASE,
    SVM_MMIO_UART0_BASE,
    SVM_MMIO_VIRTIO_BLK0_BASE,
    SVM_MMIO_VIRTIO_NET0_BASE,
    VIRTIO_MAGIC,
)
from IsaacCompiler.StackVM.paravirt import (
    PVH_BLOCK_READ,
    PVH_BLOCK_WRITE,
    PVH_CONSOLE_READ,
    PVH_CONSOLE_WRITE,
    PVH_ENTROPY,
    PVH_RTC_NOW_NS,
)
from IsaacCompiler.StackVM.PyStackVM import (
    INT_PAGE_FAULT,
    INT_PARAVIRT,
    INT_PROTECT_FAULT,
    INT_TIMER,
    INT_TLB_SHOOTDOWN,
    INT_TLB_SHOOTDOWN_DONE,
)
from IsaacCompiler.code_gen.stackvm_binutils.elf_file import (
    EM_STACKVM,
    R_STACKVM_64,
    R_STACKVM_COPY,
    R_STACKVM_GLOB_DAT,
    R_STACKVM_JUMP_SLOT,
    R_STACKVM_PC64,
    R_STACKVM_RELATIVE,
)

DOC_PATH = os.path.join(
    REPO_ROOT, "StackVM", "Documentation", "BootAbi.html"
)


def _hex(value):
    return "0x" + format(value, "X")


class BootAbiDocExistsTests(unittest.TestCase):
    def test_document_exists_and_is_html(self):
        self.assertTrue(os.path.exists(DOC_PATH), "BootAbi.html missing")
        with open(DOC_PATH, "r", encoding="utf-8") as fl:
            text = fl.read()
        self.assertIn("StackVM Boot ABI", text)
        self.assertIn("DocStyle.css", text)


class BootAbiDocContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DOC_PATH, "r", encoding="utf-8") as fl:
            cls.text = fl.read()

    def _assert_all(self, expected):
        missing = [needle for needle in expected if needle not in self.text]
        self.assertEqual(missing, [], msg="document missing: %r" % missing)

    def test_startupdata_constants(self):
        self._assert_all(
            [
                _hex(SVSD_MAGIC),
                "SVSD_VERSION</code> = %d" % SVSD_VERSION,
                str(STARTUP_DATA_SIZE),
                str(MEM_MAP_ENTRY_SIZE),
                "SVSD_FLAG_DTB",
            ]
        )
        self.assertEqual(SVSD_FLAG_DTB, 1)
        for value, name in [
            (SVMEM_RAM, "SVMEM_RAM"),
            (SVMEM_RESERVED, "SVMEM_RESERVED"),
            (SVMEM_KERNEL, "SVMEM_KERNEL"),
            (SVMEM_INITRAMFS, "SVMEM_INITRAMFS"),
            (SVMEM_BOOTDATA, "SVMEM_BOOTDATA"),
        ]:
            self.assertIn(name, self.text)
            self.assertIn("<td>%d</td><td>%s</td>" % (value, name), self.text)

    def test_paravirt_hypercall_numbers(self):
        self.assertEqual(
            [
                PVH_CONSOLE_WRITE,
                PVH_CONSOLE_READ,
                PVH_BLOCK_READ,
                PVH_BLOCK_WRITE,
                PVH_RTC_NOW_NS,
                PVH_ENTROPY,
            ],
            [0x00, 0x01, 0x02, 0x03, 0x04, 0x05],
        )
        self._assert_all(
            [
                "<td>0x00</td><td>CONSOLE_WRITE</td>",
                "<td>0x05</td><td>ENTROPY</td>",
                "ENOSYS</code> = -38",
                "EINVAL</code> = -22",
            ]
        )

    def test_mmio_device_map_and_irqs(self):
        self.assertEqual(SVM_MMIO_BASE, 0xFFFF0000)
        self._assert_all(
            [
                _hex(SVM_MMIO_UART0_BASE),
                _hex(SVM_MMIO_IC_BASE),
                _hex(SVM_MMIO_RTC_BASE),
                _hex(SVM_MMIO_VIRTIO_BLK0_BASE),
                _hex(SVM_MMIO_VIRTIO_NET0_BASE),
                "SVM_IRQ_UART0 = %d" % SVM_IRQ_UART0,
                "SVM_IRQ_VIRTIO_BLK0 = %d" % SVM_IRQ_VIRTIO_BLK0,
                "SVM_IRQ_RTC = %d" % SVM_IRQ_RTC,
                "SVM_IRQ_VIRTIO_NET0 = %d" % SVM_IRQ_VIRTIO_NET0,
                _hex(VIRTIO_MAGIC),
            ]
        )

    def test_interrupt_vectors(self):
        self.assertEqual(
            (INT_PAGE_FAULT, INT_PROTECT_FAULT, INT_TIMER, INT_PARAVIRT),
            (0x0E, 0x0D, 0x11, 0x12),
        )
        self._assert_all(
            [
                "<td>0x0E</td><td>PAGE_FAULT</td>",
                "<td>0x0D</td><td>PROTECT_FAULT</td>",
                "<td>0x11</td><td>TIMER</td>",
                "<td>0x12</td><td>PARAVIRT</td>",
                "<td>0x%02X</td><td>TLB_SHOOTDOWN_DONE</td>" % INT_TLB_SHOOTDOWN_DONE,
                "<td>0x%02X</td><td>TLB_SHOOTDOWN</td>" % INT_TLB_SHOOTDOWN,
            ]
        )

    def test_dynamic_linker_abi(self):
        self.assertEqual(EM_STACKVM, 0x5356)
        self.assertEqual(
            (
                R_STACKVM_64,
                R_STACKVM_PC64,
                R_STACKVM_RELATIVE,
                R_STACKVM_GLOB_DAT,
                R_STACKVM_JUMP_SLOT,
                R_STACKVM_COPY,
            ),
            (1, 2, 3, 4, 5, 6),
        )
        self._assert_all(
            [
                _hex(EM_STACKVM),
                "R_STACKVM_64</code>=1",
                "R_STACKVM_GLOB_DAT</code>=4",
                "R_STACKVM_COPY</code>=6",
                "DynamicLinking.html",
            ]
        )

    def test_references_companion_documents(self):
        self._assert_all(
            [
                "Interrupts.html",
                "SYSREG.html",
                "Devicetree.html",
                "Uefi.html",
                "TlbShootdown.html",
                "INVTLB.html",
                "CALL_E.html",
            ]
        )


if __name__ == "__main__":
    unittest.main()
