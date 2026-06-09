"""Tests for the Multiboot2 boot protocol on StackVM (Workstream D1b.5).

Covers the header parser, the boot-information (MBI) builder/reader, the physical
layout planner, and the end-to-end handoff: a tiny Multiboot2 kernel is loaded,
entered with the bootloader magic + MBI pointer, and recovers the command line,
memory map and modules the bootloader handed it.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.PyStackVM import (
    BC_HLT,
    BC_LOAD,
    BC_STOR,
    BCR_ABS_A8,
    BCR_ABS_C,
    BCR_R_BP8,
    BCR_SYSREG,
    BCR_SZ_8,
    SVSR_INT_ARG0,
    SVSR_INT_ARG1,
)
from IsaacCompiler.StackVM import multiboot2 as mb2
from IsaacCompiler.StackVM.multiboot2 import (
    MULTIBOOT2_BOOTLOADER_MAGIC,
    MULTIBOOT2_HEADER_MAGIC,
    MULTIBOOT_MEMORY_AVAILABLE,
    MULTIBOOT_MEMORY_RESERVED,
    MULTIBOOT_TAG_TYPE_CMDLINE,
    MULTIBOOT_TAG_TYPE_EFI64,
    MULTIBOOT_TAG_TYPE_FRAMEBUFFER,
    MULTIBOOT_TAG_TYPE_MMAP,
    build_multiboot2_header,
    parse_multiboot2_header,
    parse_multiboot2_info,
    plan_multiboot2_image,
    run_multiboot2_in_vm,
)

LOAD_BASE = 0x100000


def _u64(v):
    return (v & ((1 << 64) - 1)).to_bytes(8, "little")


def _i64(v):
    return int(v).to_bytes(8, "little", signed=True)


def _kernel_with_header(code: bytes, *, architecture=0, framebuffer=None):
    """Build a Multiboot2 kernel = [header][code] with entry pointing at the code.

    The header length is fixed once the entry-address tag is present, so build a
    dummy first to measure, then point the entry at the byte after the header.
    """
    dummy = build_multiboot2_header(
        architecture=architecture, entry_addr=0, request_framebuffer=framebuffer
    )
    entry = LOAD_BASE + len(dummy)
    header = build_multiboot2_header(
        architecture=architecture, entry_addr=entry, request_framebuffer=framebuffer
    )
    assert len(header) == len(dummy)
    return header + code, entry


class HeaderParseTests(unittest.TestCase):
    def test_header_round_trips_and_checksum_valid(self):
        header = build_multiboot2_header(
            architecture=0,
            entry_addr=0x100100,
            information_request=[6, 1],
            request_framebuffer=(640, 480, 32),
            module_align=True,
            request_efi_bs=True,
        )
        parsed = parse_multiboot2_header(header)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.magic, MULTIBOOT2_HEADER_MAGIC)
        self.assertTrue(parsed.checksum_valid)
        self.assertEqual(parsed.entry_addr, 0x100100)
        self.assertEqual(parsed.information_request, [6, 1])
        self.assertEqual(parsed.framebuffer, (640, 480, 32))
        self.assertTrue(parsed.module_align)
        self.assertTrue(parsed.efi_boot_services)

    def test_header_found_when_not_at_offset_zero(self):
        header = build_multiboot2_header(entry_addr=0x100000)
        image = b"\x00" * 16 + header + b"\xab" * 32  # 8-aligned padding prefix
        parsed = parse_multiboot2_header(image)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.header_offset, 16)

    def test_non_multiboot2_image_returns_none(self):
        self.assertIsNone(parse_multiboot2_header(b"\xde\xad\xbe\xef" * 64))

    def test_bad_checksum_is_rejected(self):
        header = bytearray(build_multiboot2_header(entry_addr=0x100000))
        header[12] ^= 0xFF  # corrupt the checksum word
        self.assertIsNone(parse_multiboot2_header(bytes(header)))


class InfoBuilderTests(unittest.TestCase):
    def test_mbi_round_trips_through_reader(self):
        builder = mb2.Multiboot2InfoBuilder()
        builder.add_bootloader_name("StackVM")
        builder.add_cmdline("console=ttyS0 root=/dev/vda")
        builder.add_basic_meminfo(640, 4096)
        builder.add_memory_map(
            [
                (0, 0x100000, MULTIBOOT_MEMORY_RESERVED),
                (0x100000, 0x300000, MULTIBOOT_MEMORY_AVAILABLE),
            ]
        )
        builder.add_module(mb2.Multiboot2Module(0x400000, 0x401000, "initrd"))
        builder.add_framebuffer(0xF0000000, 4096, 1024, 768, 32)
        builder.add_efi64_system_table(0x9000)
        builder.add_load_base_addr(0x100000)
        blob = builder.build()

        # total_size is 8-aligned and matches the blob length.
        total = int.from_bytes(blob[0:4], "little")
        self.assertEqual(total, len(blob))
        self.assertEqual(total % 8, 0)

        mem = bytearray(0x10000)
        mem[0x2000 : 0x2000 + len(blob)] = blob
        info = parse_multiboot2_info(mem, 0x2000)
        self.assertEqual(info["bootloader_name"], "StackVM")
        self.assertEqual(info["cmdline"], "console=ttyS0 root=/dev/vda")
        self.assertEqual(info["basic_meminfo"], (640, 4096))
        self.assertEqual(
            info["mmap"],
            [
                (0, 0x100000, MULTIBOOT_MEMORY_RESERVED),
                (0x100000, 0x300000, MULTIBOOT_MEMORY_AVAILABLE),
            ],
        )
        self.assertEqual(info["modules"], [(0x400000, 0x401000, "initrd")])
        self.assertEqual(info["framebuffer"][0], 0xF0000000)
        self.assertEqual(info["efi64_system_table"], 0x9000)
        self.assertEqual(info["load_base_addr"], 0x100000)


class LayoutTests(unittest.TestCase):
    def test_layout_tiles_memory_and_fits_mbi(self):
        kernel, _entry = _kernel_with_header(bytes([BC_HLT]))
        image = plan_multiboot2_image(
            kernel,
            vm_size=4 << 20,
            load_base=LOAD_BASE,
            cmdline="x",
            modules=[(b"INITRD", "initrd")],
        )
        # Memory map covers [0, vm_size) with no gaps.
        cursor = 0
        for entry in image.mem_map:
            self.assertEqual(entry.base, cursor)
            cursor = entry.end
        self.assertEqual(cursor, image.vm_size)
        # The MBI fits inside its reserved region and below the module/kernel.
        self.assertLessEqual(len(image.mbi_bytes), image.mbi_end - image.mbi_base)
        self.assertGreaterEqual(image.mbi_base, image.kernel_end)

    def test_rejects_non_multiboot2_image(self):
        with self.assertRaises(ValueError):
            plan_multiboot2_image(b"not a kernel", vm_size=1 << 20)

    def test_rejects_unaligned_load_base(self):
        kernel, _ = _kernel_with_header(bytes([BC_HLT]))
        with self.assertRaises(ValueError):
            plan_multiboot2_image(kernel, vm_size=1 << 20, load_base=0x100001)


class HandoffTests(unittest.TestCase):
    def _probe_kernel(self):
        # Stores magic@0x800, mbi@0x808, SVSR_INT_ARG0@0x810, SVSR_INT_ARG1@0x818.
        code = bytearray()
        # magic (kmain arg0 @ bp-24)
        code += bytes([BC_LOAD, BCR_SZ_8 | BCR_R_BP8]) + _i64(-24)
        code += bytes([BC_STOR, BCR_SZ_8 | BCR_ABS_A8]) + _u64(0x800)
        # mbi (kmain arg1 @ bp-16)
        code += bytes([BC_LOAD, BCR_SZ_8 | BCR_R_BP8]) + _i64(-16)
        code += bytes([BC_STOR, BCR_SZ_8 | BCR_ABS_A8]) + _u64(0x808)
        # SVSR_INT_ARG0 (magic) and SVSR_INT_ARG1 (mbi)
        code += bytes([BC_LOAD, BCR_SZ_8 | BCR_SYSREG, SVSR_INT_ARG0])
        code += bytes([BC_STOR, BCR_SZ_8 | BCR_ABS_A8]) + _u64(0x810)
        code += bytes([BC_LOAD, BCR_SZ_8 | BCR_SYSREG, SVSR_INT_ARG1])
        code += bytes([BC_STOR, BCR_SZ_8 | BCR_ABS_A8]) + _u64(0x818)
        code += bytes([BC_HLT])
        return _kernel_with_header(bytes(code))

    def test_kernel_receives_magic_mbi_and_recovers_handoff(self):
        kernel, entry = self._probe_kernel()
        initramfs = b"INITRAMFS-PAYLOAD"
        vm, image = run_multiboot2_in_vm(
            kernel,
            vm_size=4 << 20,
            load_base=LOAD_BASE,
            cmdline="root=/dev/vda ro quiet",
            modules=[(initramfs, "initrd")],
        )
        self.assertEqual(vm.running, 0)
        self.assertEqual(image.entry, entry)

        # Stack handoff: kmain(magic, mbi).
        magic = int.from_bytes(vm.memory[0x800:0x808], "little")
        mbi = int.from_bytes(vm.memory[0x808:0x810], "little")
        self.assertEqual(magic, MULTIBOOT2_BOOTLOADER_MAGIC)
        self.assertEqual(mbi, image.mbi_base)
        # Register handoff: SVSR_INT_ARG0/1 mirror the stack args.
        self.assertEqual(int.from_bytes(vm.memory[0x810:0x818], "little"), magic)
        self.assertEqual(int.from_bytes(vm.memory[0x818:0x820], "little"), mbi)

        # The kernel walks the MBI and recovers what the bootloader handed it.
        info = parse_multiboot2_info(vm.memory, mbi)
        self.assertEqual(info["cmdline"], "root=/dev/vda ro quiet")
        self.assertEqual(info["bootloader_name"], "StackVM Multiboot2")
        self.assertIn(MULTIBOOT_TAG_TYPE_MMAP, info["tags"])
        self.assertIn(MULTIBOOT_TAG_TYPE_CMDLINE, info["tags"])
        # First mmap region is the low reserved area; the big RAM region is available.
        self.assertTrue(
            any(t == MULTIBOOT_MEMORY_AVAILABLE for _b, _l, t in info["mmap"])
        )

        # The module (initramfs) payload is resident and described by the MBI.
        self.assertEqual(len(info["modules"]), 1)
        mod_start, mod_end, name = info["modules"][0]
        self.assertEqual(name, "initrd")
        self.assertEqual(vm.memory[mod_start:mod_end], initramfs)

    def test_efi_and_framebuffer_tags_present_when_requested(self):
        kernel, _entry = _kernel_with_header(bytes([BC_HLT]))
        vm, image = run_multiboot2_in_vm(
            kernel,
            vm_size=4 << 20,
            load_base=LOAD_BASE,
            efi_system_table=0xABCD000,
            framebuffer=(0xF0000000, 4096, 1024, 768, 32),
        )
        info = parse_multiboot2_info(vm.memory, image.mbi_base)
        self.assertIn(MULTIBOOT_TAG_TYPE_EFI64, info["tags"])
        self.assertEqual(info["efi64_system_table"], 0xABCD000)
        self.assertIn(MULTIBOOT_TAG_TYPE_FRAMEBUFFER, info["tags"])
        self.assertEqual(info["framebuffer"][0], 0xF0000000)


if __name__ == "__main__":
    unittest.main()
