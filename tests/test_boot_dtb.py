"""Tests for emulator DTB generation + the slimmed StartupData handoff (D1a.3).

These mirror ``tests/test_boot_protocol.py`` but exercise the devicetree-aware
boot path:

  * the boot path auto-generates a binding-conformant DTB whose /memory matches
    the D1 memory map, /chosen carries the cmdline + initramfs extent, and /cpus
    has exactly ``core_count`` nodes,
  * the generated DTB round-trips (build -> parse -> re-flatten is idempotent)
    and its self-reported /reserved-memory bootdata extent matches the image it
    ships in (the layout fixed-point converged),
  * the slim (DTB-authoritative) form sets SVSD_FLAG_DTB and zeroes the
    DTB-described StartupData fields while keeping the initramfs payload resident,
  * an end-to-end run where a tiny kernel reads ``StartupData.dtb`` (pointer +
    size) and dereferences it, then the test walks the FDT and recovers the
    command line + memory map.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.boot import (
    SVMEM_BOOTDATA,
    SVMEM_KERNEL,
    SVMEM_RESERVED,
    SVSD_FLAG_DTB,
    SVSD_MAGIC,
    boot_kernel,
    build_boot_image,
    build_machine_dtb,
    plan_boot_image,
    populate_startup_data,
    read_startup_data,
)
from IsaacCompiler.StackVM.dt_bindings import (
    COMPAT_MACHINE,
    dt_regions_from_mem_map,
)
from IsaacCompiler.StackVM.devicetree import (
    FlattenedDeviceTree,
    decode_cells,
)
from IsaacCompiler.StackVM.PyStackVM import (
    BC_ADD8,
    BC_HLT,
    BC_LOAD,
    BC_STOR,
    BCR_ABS_A8,
    BCR_ABS_C,
    BCR_ABS_S8,
    BCR_SYSREG,
    SVSR_SDP,
    VM_DISABLED,
)

_SZ8 = 0x60  # size-class 3 (8 bytes) in the high 3 bits of a BCR operand byte

# struct StartupData field offsets (see _SD_FORMAT "<QIIQQQQQQQQQQQ" in boot.py).
SD_OFF_DTB = 88
SD_OFF_DTB_SIZE = 96


def _decode_reg_pairs(reg_cells):
    """Decode a #address-cells=2/#size-cells=2 reg into [(base, size), ...]."""
    out = []
    for i in range(0, len(reg_cells), 4):
        base = (reg_cells[i] << 32) | reg_cells[i + 1]
        size = (reg_cells[i + 2] << 32) | reg_cells[i + 3]
        out.append((base, size))
    return out


# ---------------------------------------------------------------------------
# Layout planning: DTB generation + fixed-point convergence
# ---------------------------------------------------------------------------


class TestDtbGenerationLayout(unittest.TestCase):
    def test_generated_dtb_is_embedded_and_self_consistent(self):
        image = plan_boot_image(
            vm_size=1 << 20,
            kernel_len=5000,
            kernel_base=0x1000,
            cmdline="console=ttyS0 root=/dev/vda ro",
            initramfs=b"cpio-payload" * 64,
            generate_dtb=True,
            core_count=4,
        )
        # A DTB was generated and lives inside the bootdata region.
        self.assertTrue(image.dtb_bytes)
        self.assertEqual(image.dtb_bytes[:4], b"\xd0\x0d\xfe\xed")

        # The embedded blob describes *this* image (layout converged): the
        # /reserved-memory bootdata extent matches the actual bootdata region.
        fdt = FlattenedDeviceTree.from_dtb(image.dtb_bytes)
        bootdata = next(e for e in image.mem_map if e.type == SVMEM_BOOTDATA)
        node = fdt.get_node("/reserved-memory/bootdata@%x" % bootdata.base)
        self.assertIsNotNone(node)
        (base, size), = _decode_reg_pairs(decode_cells(node.get_prop("reg")))
        self.assertEqual((base, size), (bootdata.base, bootdata.size))

        # Re-deriving the DTB from the final image is a no-op (idempotent plan).
        self.assertEqual(image.dtb_bytes, build_machine_dtb(image))

    def test_explicit_dtb_takes_precedence_over_generate(self):
        explicit = b"\xd0\x0d\xfe\xed" + b"not-a-real-tree"
        image = plan_boot_image(
            vm_size=1 << 20,
            kernel_len=100,
            dtb=explicit,
            generate_dtb=True,
        )
        self.assertEqual(image.dtb_bytes, explicit)

    def test_no_generate_means_no_dtb(self):
        image = plan_boot_image(vm_size=1 << 20, kernel_len=100)
        self.assertEqual(image.dtb_bytes, b"")


# ---------------------------------------------------------------------------
# Generated DTB content matches the D1 boot handoff
# ---------------------------------------------------------------------------


class TestGeneratedDtbContent(unittest.TestCase):
    def setUp(self):
        self.cmdline = "console=ttyS0 root=/dev/vda ro quiet"
        self.core_count = 3
        self.initramfs = b"INITRAMFS" * 200
        self.vm, self.image = boot_kernel(
            bytes([BC_HLT]),
            vm_size=1 << 20,
            kernel_base=0x1000,
            cmdline=self.cmdline,
            initramfs=self.initramfs,
            generate_dtb=True,
            core_count=self.core_count,
        )
        self.sd = read_startup_data(self.vm.memory, self.vm.sys_regs[SVSR_SDP])
        self.fdt = FlattenedDeviceTree.from_dtb(self.sd.dtb)

    def test_startupdata_points_at_a_valid_dtb(self):
        self.assertTrue(self.sd.is_valid)
        self.assertFalse(self.sd.dtb_only)  # full handoff: not slim
        self.assertNotEqual(self.sd.dtb_ptr, 0)
        self.assertEqual(self.sd.dtb_size, len(self.sd.dtb))
        self.assertEqual(self.fdt.root.get_string("compatible"), COMPAT_MACHINE)

    def test_dtb_memory_matches_d1_map(self):
        # The DTB /memory advertises exactly the RAM-backed portion of the map.
        ram_regions, _reserved = dt_regions_from_mem_map(self.sd.mem_map)
        mem_nodes = [
            n for p, n in self.fdt.walk() if p.startswith("/memory@")
        ]
        self.assertEqual(len(mem_nodes), 1)
        dtb_regions = _decode_reg_pairs(decode_cells(mem_nodes[0].get_prop("reg")))
        self.assertEqual(dtb_regions, ram_regions)

        # Total advertised RAM equals the non-reserved bytes of the boot map.
        ram_bytes = sum(
            e.size for e in self.sd.mem_map if e.type != SVMEM_RESERVED
        )
        self.assertEqual(sum(size for _b, size in dtb_regions), ram_bytes)

    def test_dtb_chosen_carries_cmdline_and_initrd(self):
        chosen = self.fdt.get_node("/chosen")
        self.assertEqual(chosen.get_string("bootargs"), self.cmdline)
        self.assertEqual(chosen.get_u64("linux,initrd-start"), self.sd.initramfs_base)
        self.assertEqual(
            chosen.get_u64("linux,initrd-end"),
            self.sd.initramfs_base + self.sd.initramfs_size,
        )

    def test_dtb_cpus_count_matches_core_count(self):
        cpus = self.fdt.get_node("/cpus")
        cpu_nodes = [c for c in cpus.children if c.name.startswith("cpu@")]
        self.assertEqual(len(cpu_nodes), self.core_count)

    def test_generated_dtb_roundtrips(self):
        reparsed = FlattenedDeviceTree.from_dtb(self.sd.dtb)
        self.assertEqual(reparsed.to_dtb(), self.sd.dtb)


# ---------------------------------------------------------------------------
# Slim (DTB-authoritative) StartupData
# ---------------------------------------------------------------------------


class TestSlimStartupData(unittest.TestCase):
    def test_slim_zeroes_dtb_described_fields(self):
        cmdline = "root=/dev/vda1 ro"
        initramfs = b"X" * 5000
        vm, image = boot_kernel(
            bytes([BC_HLT]),
            vm_size=1 << 20,
            kernel_base=0x1000,
            cmdline=cmdline,
            initramfs=initramfs,
            slim=True,
            core_count=2,
        )
        sd = read_startup_data(vm.memory, vm.sys_regs[SVSR_SDP])

        # Slim handoff: flag set, struct still valid, DTB present.
        self.assertTrue(sd.is_valid)
        self.assertTrue(sd.dtb_only)
        self.assertEqual(sd.flags & SVSD_FLAG_DTB, SVSD_FLAG_DTB)
        self.assertNotEqual(sd.dtb_ptr, 0)
        self.assertEqual(sd.dtb_size, len(sd.dtb))

        # The DTB-described fields are zeroed.
        self.assertEqual(sd.mem_map_count, 0)
        self.assertEqual(sd.mem_map, [])
        self.assertEqual(sd.cmdline_ptr, 0)
        self.assertIsNone(sd.cmdline)
        self.assertEqual(sd.initramfs_base, 0)
        self.assertEqual(sd.initramfs_size, 0)
        self.assertEqual(sd.core_count, 0)
        # boot_core_id is retained in the slim form.
        self.assertEqual(sd.boot_core_id, image.boot_core_id)

        # Everything is recoverable from the DTB instead.
        fdt = FlattenedDeviceTree.from_dtb(sd.dtb)
        chosen = fdt.get_node("/chosen")
        self.assertEqual(chosen.get_string("bootargs"), cmdline)
        cpu_nodes = [
            c for c in fdt.get_node("/cpus").children if c.name.startswith("cpu@")
        ]
        self.assertEqual(len(cpu_nodes), 2)

        # The initramfs *payload* is still resident at the DTB-advertised base.
        istart = chosen.get_u64("linux,initrd-start")
        iend = chosen.get_u64("linux,initrd-end")
        self.assertEqual(iend - istart, len(initramfs))
        self.assertEqual(bytes(vm.memory[istart:iend]), initramfs)

    def test_slim_requires_a_dtb(self):
        image = build_boot_image(vm_size=1 << 20, kernel_len=100, cmdline="x")
        self.assertEqual(image.dtb_bytes, b"")  # no DTB planned
        memory = bytearray(image.vm_size)
        with self.assertRaises(ValueError):
            populate_startup_data(memory, image, slim=True)


# ---------------------------------------------------------------------------
# End-to-end: a tiny kernel reads StartupData.dtb and the test walks the FDT
# ---------------------------------------------------------------------------


def _read_sd_field(offset: int, result_addr: int) -> bytes:
    """Bytecode: *result_addr = *(uint64*)(SVSR_SDP + offset)."""
    code = bytearray()
    code += bytes([BC_LOAD, _SZ8 | BCR_SYSREG, SVSR_SDP])  # push SDP
    code += bytes([BC_LOAD, _SZ8 | BCR_ABS_C]) + offset.to_bytes(8, "little")
    code += bytes([BC_ADD8])  # SDP + offset
    code += bytes([BC_LOAD, _SZ8 | BCR_ABS_S8])  # *(SDP + offset)
    code += bytes([BC_STOR, _SZ8 | BCR_ABS_A8]) + result_addr.to_bytes(8, "little")
    return bytes(code)


def _build_dtb_probe_kernel(res_ptr: int, res_size: int, res_hdr: int) -> bytes:
    """A kernel that recovers StartupData.dtb (pointer + size) and dereferences
    it, storing the pointer, the size, and the first 8 bytes of the blob (which
    begin with the FDT magic) into fixed result slots, then halts."""
    code = bytearray()
    code += _read_sd_field(SD_OFF_DTB, res_ptr)
    code += _read_sd_field(SD_OFF_DTB_SIZE, res_size)
    # *res_hdr = *(uint64*)dtb_ptr  (dtb_ptr = *(SDP + SD_OFF_DTB))
    code += bytes([BC_LOAD, _SZ8 | BCR_SYSREG, SVSR_SDP])
    code += bytes([BC_LOAD, _SZ8 | BCR_ABS_C]) + SD_OFF_DTB.to_bytes(8, "little")
    code += bytes([BC_ADD8])
    code += bytes([BC_LOAD, _SZ8 | BCR_ABS_S8])  # -> dtb_ptr
    code += bytes([BC_LOAD, _SZ8 | BCR_ABS_S8])  # -> *(dtb_ptr): first 8 bytes
    code += bytes([BC_STOR, _SZ8 | BCR_ABS_A8]) + res_hdr.to_bytes(8, "little")
    code += bytes([BC_HLT])
    return bytes(code)


class TestEndToEnd(unittest.TestCase):
    def test_kernel_reads_dtb_then_test_walks_fdt(self):
        vm_size = 1 << 20
        cmdline = "console=ttyS0 root=/dev/vda ro"
        initramfs = b"cpio" * 256
        core_count = 4

        # Result slots high in free RAM, clear of the kernel stack.
        res_ptr = vm_size - 0x1000
        res_size = res_ptr + 8
        res_hdr = res_ptr + 16

        kernel = _build_dtb_probe_kernel(res_ptr, res_size, res_hdr)
        vm, image = boot_kernel(
            kernel,
            vm_size=vm_size,
            kernel_base=0x1000,
            cmdline=cmdline,
            initramfs=initramfs,
            generate_dtb=True,
            core_count=core_count,
        )
        # Sanity: enters in kernel mode with the MMU off (D1 launch contract).
        self.assertEqual(vm.priv_lvl, 0)
        self.assertEqual(vm.virt_mem_mode, VM_DISABLED)

        vm.execute()
        self.assertEqual(vm.running, 0)

        got_ptr = int.from_bytes(vm.memory[res_ptr : res_ptr + 8], "little")
        got_size = int.from_bytes(vm.memory[res_size : res_size + 8], "little")
        got_hdr = int.from_bytes(vm.memory[res_hdr : res_hdr + 8], "little")

        sd = read_startup_data(vm.memory, vm.sys_regs[SVSR_SDP])
        self.assertEqual(got_ptr, sd.dtb_ptr)
        self.assertEqual(got_size, sd.dtb_size)
        # The kernel read a real FDT: the first 4 bytes are the big-endian magic.
        self.assertEqual(got_hdr & 0xFFFFFFFF, int.from_bytes(b"\xd0\x0d\xfe\xed", "little"))

        # Now walk the FDT the kernel pointed us at and recover the handoff.
        # (from_dtb validates the FDT_MAGIC header, so a bad blob would raise.)
        blob = bytes(vm.memory[got_ptr : got_ptr + got_size])
        fdt = FlattenedDeviceTree.from_dtb(blob)

        # cmdline recovered from /chosen.
        self.assertEqual(fdt.get_node("/chosen").get_string("bootargs"), cmdline)

        # /cpus count matches.
        cpu_nodes = [
            c for c in fdt.get_node("/cpus").children if c.name.startswith("cpu@")
        ]
        self.assertEqual(len(cpu_nodes), core_count)

        # Memory map recovered from /memory == the RAM-backed boot map.
        ram_regions, _resv = dt_regions_from_mem_map(image.mem_map)
        mem_node = next(
            n for p, n in fdt.walk() if p.startswith("/memory@")
        )
        self.assertEqual(
            _decode_reg_pairs(decode_cells(mem_node.get_prop("reg"))), ram_regions
        )


if __name__ == "__main__":
    unittest.main()
