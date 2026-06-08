"""Tests for the flattened-devicetree core (D1a.1) and StackVM DT bindings (D1a.2).

Covers:
  * the FDT/DTB binary format: header magic/sizes/offsets + alignment, the
    structure-block tokens, the deduplicated strings block, and the
    memory-reservation block,
  * the builder/reader APIs: typed property encode/decode round-trips, build ->
    flatten -> parse round-trips, path lookup, tree walking, and parse errors,
  * the StackVM platform bindings emitted by ``build_stackvm_fdt`` (root,
    /memory, /reserved-memory, /chosen, /cpus, /soc + the MMIO device nodes,
    interrupt-controller phandle wiring), and
  * integration with the D1 boot path: a bindings DTB embedded in a boot image
    round-trips through StartupData and matches the boot memory map / cmdline.
"""

import os
import struct
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.devicetree import (
    FDT_BEGIN_NODE,
    FDT_END,
    FDT_END_NODE,
    FDT_HEADER_SIZE,
    FDT_LAST_COMP_VERSION,
    FDT_MAGIC,
    FDT_NOP,
    FDT_VERSION,
    FdtNode,
    FlattenedDeviceTree,
    decode_cells,
    decode_string,
    decode_stringlist,
    decode_u32,
    decode_u64,
    encode_cells,
    encode_string,
    encode_stringlist,
    encode_u32,
    encode_u64,
)
from IsaacCompiler.StackVM.dt_bindings import (
    COMPAT_CPU,
    COMPAT_INTC,
    COMPAT_MACHINE,
    COMPAT_UART,
    COMPAT_VIRTIO_MMIO,
    PHANDLE_INTC,
    build_stackvm_fdt,
    default_soc_devices,
    dt_regions_from_mem_map,
)
from IsaacCompiler.StackVM.boot import (
    SVMEM_BOOTDATA,
    SVMEM_KERNEL,
    SVMEM_RESERVED,
    build_boot_image,
    populate_startup_data,
    read_startup_data,
)
from IsaacCompiler.StackVM.mmio import (
    SVM_IRQ_RTC,
    SVM_IRQ_UART0,
    SVM_IRQ_VIRTIO_BLK0,
    SVM_IRQ_VIRTIO_NET0,
    SVM_MMIO_IC_BASE,
    SVM_MMIO_RTC_BASE,
    SVM_MMIO_UART0_BASE,
    SVM_MMIO_VIRTIO_BLK0_BASE,
    SVM_MMIO_VIRTIO_NET0_BASE,
)


# ---------------------------------------------------------------------------
# Typed property encoders / decoders (D1a.1)
# ---------------------------------------------------------------------------


class TestPropertyCodecs(unittest.TestCase):
    def test_u32_roundtrip_big_endian(self):
        self.assertEqual(encode_u32(0x12345678), b"\x12\x34\x56\x78")
        self.assertEqual(decode_u32(encode_u32(0xDEADBEEF)), 0xDEADBEEF)

    def test_u64_roundtrip_big_endian(self):
        self.assertEqual(
            encode_u64(0x1122334455667788),
            b"\x11\x22\x33\x44\x55\x66\x77\x88",
        )
        self.assertEqual(decode_u64(encode_u64(0xFFFF0000)), 0xFFFF0000)

    def test_string_roundtrip_is_nul_terminated(self):
        raw = encode_string("ns16550a")
        self.assertTrue(raw.endswith(b"\0"))
        self.assertEqual(decode_string(raw), "ns16550a")

    def test_stringlist_roundtrip(self):
        values = ["virtio,mmio", "stackvm,device"]
        raw = encode_stringlist(values)
        self.assertEqual(raw, b"virtio,mmio\0stackvm,device\0")
        self.assertEqual(decode_stringlist(raw), values)

    def test_empty_stringlist(self):
        self.assertEqual(decode_stringlist(b""), [])

    def test_cells_roundtrip(self):
        self.assertEqual(encode_cells([1, 2, 3]), b"\0\0\0\1\0\0\0\2\0\0\0\3")
        self.assertEqual(decode_cells(encode_cells([0, 0xFFFF, 7])), [0, 0xFFFF, 7])

    def test_decode_rejects_bad_length(self):
        with self.assertRaises(ValueError):
            decode_u32(b"\0\0\0")
        with self.assertRaises(ValueError):
            decode_u64(b"\0\0\0\0")
        with self.assertRaises(ValueError):
            decode_cells(b"\0\0\0")


# ---------------------------------------------------------------------------
# FDT header / blob format (D1a.1)
# ---------------------------------------------------------------------------


def _build_sample_tree():
    fdt = FlattenedDeviceTree(boot_cpuid_phys=0)
    root = fdt.root
    root.set_u32("#address-cells", 2)
    root.set_u32("#size-cells", 2)
    root.set_string("compatible", "stackvm,virt")

    chosen = root.add_subnode("chosen")
    chosen.set_string("bootargs", "console=ttyS0")

    soc = root.add_subnode("soc")
    soc.set_empty("ranges")
    serial = soc.add_subnode("serial@ffff0000")
    serial.set_string("compatible", "stackvm,uart")
    serial.set_prop("reg", encode_u64(0xFFFF0000) + encode_u64(0x1000))
    serial.set_cells("interrupts", [1])

    fdt.add_reservation(0x1000, 0x2000)
    return fdt


class TestFdtFormat(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(FDT_MAGIC, 0xD00DFEED)
        self.assertEqual(FDT_HEADER_SIZE, 40)
        self.assertEqual(FDT_VERSION, 17)
        self.assertEqual(FDT_LAST_COMP_VERSION, 16)

    def test_header_fields_and_alignment(self):
        blob = _build_sample_tree().to_dtb()
        (
            magic,
            totalsize,
            off_struct,
            off_strings,
            off_rsvmap,
            version,
            last_comp,
            boot_cpuid,
            size_strings,
            size_struct,
        ) = struct.unpack_from(">10I", blob, 0)

        self.assertEqual(magic, FDT_MAGIC)
        self.assertEqual(totalsize, len(blob))
        self.assertEqual(version, FDT_VERSION)
        self.assertEqual(last_comp, FDT_LAST_COMP_VERSION)
        # Block placement + spec-mandated alignment.
        self.assertEqual(off_rsvmap, FDT_HEADER_SIZE)
        self.assertEqual(off_rsvmap % 8, 0)
        self.assertEqual(off_struct % 4, 0)
        self.assertEqual(off_struct + size_struct, off_strings)
        self.assertEqual(off_strings + size_strings, totalsize)
        # The structure block always ends with FDT_END.
        self.assertEqual(
            struct.unpack_from(">I", blob, off_struct + size_struct - 4)[0], FDT_END
        )

    def test_strings_block_dedups_property_names(self):
        # "compatible" appears in two nodes but must be interned once.
        fdt = FlattenedDeviceTree()
        a = fdt.root.add_subnode("a")
        a.set_string("compatible", "x")
        b = fdt.root.add_subnode("b")
        b.set_string("compatible", "y")
        blob = fdt.to_dtb()
        (_, _, _, off_strings, _, _, _, _, size_strings, _) = struct.unpack_from(
            ">10I", blob, 0
        )
        strings = blob[off_strings : off_strings + size_strings]
        self.assertEqual(strings.count(b"compatible\0"), 1)

    def test_reservation_block_terminated(self):
        blob = _build_sample_tree().to_dtb()
        off_rsvmap = struct.unpack_from(">10I", blob, 0)[4]
        addr, size = struct.unpack_from(">QQ", blob, off_rsvmap)
        self.assertEqual((addr, size), (0x1000, 0x2000))
        term = struct.unpack_from(">QQ", blob, off_rsvmap + 16)
        self.assertEqual(term, (0, 0))


# ---------------------------------------------------------------------------
# Build -> flatten -> parse round-trip + reader API (D1a.1)
# ---------------------------------------------------------------------------


class TestRoundTrip(unittest.TestCase):
    def test_full_roundtrip(self):
        original = _build_sample_tree()
        parsed = FlattenedDeviceTree.from_dtb(original.to_dtb())

        self.assertEqual(parsed.reservations, [(0x1000, 0x2000)])
        self.assertEqual(parsed.boot_cpuid_phys, 0)

        root = parsed.root
        self.assertEqual(root.get_u32("#address-cells"), 2)
        self.assertEqual(root.get_string("compatible"), "stackvm,virt")

        chosen = parsed.get_node("/chosen")
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.get_string("bootargs"), "console=ttyS0")

        serial = parsed.get_node("/soc/serial@ffff0000")
        self.assertIsNotNone(serial)
        self.assertEqual(serial.get_string("compatible"), "stackvm,uart")
        self.assertEqual(decode_cells(serial.get_prop("reg")), [0, 0xFFFF0000, 0, 0x1000])
        self.assertEqual(serial.get_cells("interrupts"), [1])

    def test_idempotent_reencode(self):
        blob1 = _build_sample_tree().to_dtb()
        blob2 = FlattenedDeviceTree.from_dtb(blob1).to_dtb()
        self.assertEqual(blob1, blob2)

    def test_empty_property_is_preserved(self):
        fdt = FlattenedDeviceTree()
        fdt.root.add_subnode("soc").set_empty("ranges")
        parsed = FlattenedDeviceTree.from_dtb(fdt.to_dtb())
        soc = parsed.get_node("/soc")
        self.assertTrue(soc.has_prop("ranges"))
        self.assertEqual(soc.get_prop("ranges"), b"")

    def test_walk_visits_every_node(self):
        paths = [p for p, _ in _build_sample_tree().walk()]
        self.assertEqual(
            paths, ["/", "/chosen", "/soc", "/soc/serial@ffff0000"]
        )

    def test_get_node_missing_returns_none(self):
        fdt = _build_sample_tree()
        self.assertIsNone(fdt.get_node("/nope"))
        self.assertIsNone(fdt.get_node("/soc/missing"))

    def test_parse_tolerates_nop_tokens(self):
        # A hand-assembled blob with NOP tokens around an empty-named root node.
        struct_block = b"".join(
            struct.pack(">I", tok)
            for tok in (FDT_NOP, FDT_BEGIN_NODE)
        )
        struct_block += b"\x00\x00\x00\x00"  # root name "" padded to 4
        struct_block += b"".join(
            struct.pack(">I", tok) for tok in (FDT_NOP, FDT_END_NODE, FDT_END)
        )
        reservations = struct.pack(">QQ", 0, 0)
        off_struct = FDT_HEADER_SIZE + len(reservations)
        off_strings = off_struct + len(struct_block)
        header = struct.pack(
            ">10I",
            FDT_MAGIC,
            off_strings,
            off_struct,
            off_strings,
            FDT_HEADER_SIZE,
            FDT_VERSION,
            FDT_LAST_COMP_VERSION,
            0,
            0,
            len(struct_block),
        )
        blob = header + reservations + struct_block
        parsed = FlattenedDeviceTree.from_dtb(blob)
        self.assertEqual(parsed.root.name, "")
        self.assertEqual(len(parsed.root.children), 0)


class TestBuilderErrors(unittest.TestCase):
    def test_duplicate_sibling_name_rejected(self):
        node = FdtNode("soc")
        node.add_subnode("serial@0")
        with self.assertRaises(ValueError):
            node.add_subnode("serial@0")

    def test_missing_property_raises_keyerror(self):
        with self.assertRaises(KeyError):
            FdtNode("x").get_u32("absent")

    def test_relative_path_rejected(self):
        with self.assertRaises(ValueError):
            FlattenedDeviceTree().get_node("soc")

    def test_bad_magic_rejected(self):
        blob = bytearray(_build_sample_tree().to_dtb())
        blob[0] ^= 0xFF
        with self.assertRaises(ValueError):
            FlattenedDeviceTree.from_dtb(bytes(blob))

    def test_zero_size_reservation_rejected(self):
        with self.assertRaises(ValueError):
            FlattenedDeviceTree().add_reservation(0x1000, 0)


# ---------------------------------------------------------------------------
# StackVM platform bindings (D1a.2)
# ---------------------------------------------------------------------------


def _build_bindings_fdt(core_count=2, initramfs=True):
    return build_stackvm_fdt(
        memory_regions=[(0x1000, 0xFF000)],
        core_count=core_count,
        boot_core_id=0,
        cmdline="console=ttyS0 root=/dev/vda ro",
        initramfs_base=0x40000 if initramfs else 0,
        initramfs_size=0x8000 if initramfs else 0,
        reserved_regions=[("kernel", 0x1000, 0x4000), ("bootdata", 0x5000, 0x1000)],
    )


class TestBindings(unittest.TestCase):
    def test_root_node(self):
        root = _build_bindings_fdt().root
        self.assertEqual(root.get_u32("#address-cells"), 2)
        self.assertEqual(root.get_u32("#size-cells"), 2)
        self.assertEqual(root.get_string("compatible"), COMPAT_MACHINE)

    def test_memory_node(self):
        memory = _build_bindings_fdt().get_node("/memory@1000")
        self.assertIsNotNone(memory)
        self.assertEqual(memory.get_string("device_type"), "memory")
        self.assertEqual(decode_cells(memory.get_prop("reg")), [0, 0x1000, 0, 0xFF000])

    def test_reserved_memory(self):
        fdt = _build_bindings_fdt()
        kernel = fdt.get_node("/reserved-memory/kernel@1000")
        bootdata = fdt.get_node("/reserved-memory/bootdata@5000")
        self.assertIsNotNone(kernel)
        self.assertIsNotNone(bootdata)
        self.assertTrue(kernel.has_prop("no-map"))
        self.assertEqual(decode_cells(kernel.get_prop("reg")), [0, 0x1000, 0, 0x4000])

    def test_chosen(self):
        chosen = _build_bindings_fdt().get_node("/chosen")
        self.assertEqual(
            chosen.get_string("bootargs"), "console=ttyS0 root=/dev/vda ro"
        )
        self.assertEqual(
            chosen.get_string("stdout-path"),
            "/soc/serial@%x" % SVM_MMIO_UART0_BASE,
        )
        self.assertEqual(chosen.get_u64("linux,initrd-start"), 0x40000)
        self.assertEqual(chosen.get_u64("linux,initrd-end"), 0x48000)

    def test_chosen_without_initramfs_omits_initrd(self):
        chosen = _build_bindings_fdt(initramfs=False).get_node("/chosen")
        self.assertFalse(chosen.has_prop("linux,initrd-start"))
        self.assertFalse(chosen.has_prop("linux,initrd-end"))

    def test_cpus_one_node_per_core(self):
        fdt = _build_bindings_fdt(core_count=4)
        cpus = fdt.get_node("/cpus")
        self.assertEqual(cpus.get_u32("#address-cells"), 1)
        self.assertEqual(cpus.get_u32("#size-cells"), 0)
        cpu_nodes = [c for c in cpus.children if c.name.startswith("cpu@")]
        self.assertEqual(len(cpu_nodes), 4)
        for core in range(4):
            cpu = fdt.get_node("/cpus/cpu@%x" % core)
            self.assertIsNotNone(cpu)
            self.assertEqual(cpu.get_string("compatible"), COMPAT_CPU)
            self.assertEqual(cpu.get_u32("reg"), core)

    def test_soc_interrupt_controller(self):
        intc = _build_bindings_fdt().get_node(
            "/soc/interrupt-controller@%x" % SVM_MMIO_IC_BASE
        )
        self.assertIsNotNone(intc)
        self.assertEqual(intc.get_string("compatible"), COMPAT_INTC)
        self.assertTrue(intc.has_prop("interrupt-controller"))
        self.assertEqual(intc.get_u32("#interrupt-cells"), 1)
        self.assertEqual(intc.get_u32("phandle"), PHANDLE_INTC)

    def test_soc_devices_reg_irq_and_parent(self):
        fdt = _build_bindings_fdt()
        cases = [
            ("serial@%x" % SVM_MMIO_UART0_BASE, COMPAT_UART, SVM_MMIO_UART0_BASE, SVM_IRQ_UART0),
            ("rtc@%x" % SVM_MMIO_RTC_BASE, "stackvm,rtc", SVM_MMIO_RTC_BASE, SVM_IRQ_RTC),
            ("virtio@%x" % SVM_MMIO_VIRTIO_BLK0_BASE, COMPAT_VIRTIO_MMIO, SVM_MMIO_VIRTIO_BLK0_BASE, SVM_IRQ_VIRTIO_BLK0),
            ("virtio@%x" % SVM_MMIO_VIRTIO_NET0_BASE, COMPAT_VIRTIO_MMIO, SVM_MMIO_VIRTIO_NET0_BASE, SVM_IRQ_VIRTIO_NET0),
        ]
        for name, compat, base, irq in cases:
            node = fdt.get_node("/soc/" + name)
            self.assertIsNotNone(node, name)
            self.assertEqual(node.get_string("compatible"), compat)
            self.assertEqual(decode_cells(node.get_prop("reg")), [0, base, 0, 0x1000])
            self.assertEqual(node.get_cells("interrupts"), [irq])
            self.assertEqual(node.get_u32("interrupt-parent"), PHANDLE_INTC)

    def test_default_soc_devices_count(self):
        # intc + serial + rtc + virtio-blk + virtio-net
        self.assertEqual(len(default_soc_devices()), 5)

    def test_bindings_dtb_roundtrips(self):
        blob = _build_bindings_fdt().to_dtb()
        parsed = FlattenedDeviceTree.from_dtb(blob)
        self.assertEqual(parsed.root.get_string("compatible"), COMPAT_MACHINE)
        self.assertEqual(
            parsed.get_node("/cpus/cpu@1").get_u32("reg"), 1
        )


# ---------------------------------------------------------------------------
# dt_regions_from_mem_map + D1 boot-path integration (D1a.1 + D1a.2)
# ---------------------------------------------------------------------------


class TestBootIntegration(unittest.TestCase):
    def test_dt_regions_from_mem_map(self):
        image = build_boot_image(
            vm_size=1 << 20,
            kernel_len=5000,
            kernel_base=0x1000,
            cmdline="boot",
            initramfs=b"INITRAMFS" * 100,
        )
        memory, reserved = dt_regions_from_mem_map(image.mem_map)

        # The low reserved guard region is not advertised as RAM; RAM-backed
        # regions are coalesced into a single contiguous run from kernel_base up.
        self.assertEqual(memory, [(image.kernel_base, image.vm_size - image.kernel_base)])
        # No RAM region overlaps the low reserved guard.
        low_reserved = next(e for e in image.mem_map if e.type == SVMEM_RESERVED)
        self.assertTrue(all(base >= low_reserved.end for base, _ in memory))
        # Kernel + bootdata are carved out as reserved-memory.
        names = {name for name, _, _ in reserved}
        self.assertEqual(names, {"kernel", "bootdata"})

    def test_bindings_dtb_embedded_in_boot_image(self):
        vm_size = 1 << 20
        cmdline = "console=ttyS0 root=/dev/vda ro"
        initramfs = b"cpio-payload" * 64
        image = build_boot_image(
            vm_size=vm_size,
            kernel_len=4096,
            kernel_base=0x1000,
            cmdline=cmdline,
            initramfs=initramfs,
        )
        memory, reserved = dt_regions_from_mem_map(image.mem_map)
        dtb = build_stackvm_fdt(
            memory_regions=memory,
            reserved_regions=reserved,
            core_count=image.core_count,
            boot_core_id=image.boot_core_id,
            cmdline=cmdline,
            initramfs_base=image.initramfs_base,
            initramfs_size=image.initramfs_size,
        ).to_dtb()

        # Rebuild the image now that we have the real DTB, populate, read back.
        image = build_boot_image(
            vm_size=vm_size,
            kernel_len=4096,
            kernel_base=0x1000,
            cmdline=cmdline,
            initramfs=initramfs,
            dtb=dtb,
        )
        memv = bytearray(vm_size)
        addr = populate_startup_data(memv, image, initramfs=initramfs)
        sd = read_startup_data(memv, addr)

        self.assertTrue(sd.is_valid)
        self.assertEqual(sd.dtb, dtb)

        # Parse the embedded DTB straight out of StartupData and confirm the
        # bindings agree with the boot handoff.
        parsed = FlattenedDeviceTree.from_dtb(sd.dtb)
        chosen = parsed.get_node("/chosen")
        self.assertEqual(chosen.get_string("bootargs"), sd.cmdline.decode())
        self.assertEqual(chosen.get_u64("linux,initrd-start"), sd.initramfs_base)
        self.assertEqual(
            chosen.get_u64("linux,initrd-end"), sd.initramfs_base + sd.initramfs_size
        )

        # /memory advertises exactly the RAM-backed portion of the boot map.
        mem_reg = decode_cells(parsed.get_node("/memory@1000").get_prop("reg"))
        ram_bytes = sum(
            e.size for e in sd.mem_map if e.type != SVMEM_RESERVED
        )
        # reg is (base_hi base_lo size_hi size_lo) pairs; sum the sizes.
        total_reg_size = sum(
            (mem_reg[i] << 32) | mem_reg[i + 1] for i in range(2, len(mem_reg), 4)
        )
        self.assertEqual(total_reg_size, ram_bytes)


if __name__ == "__main__":
    unittest.main()
