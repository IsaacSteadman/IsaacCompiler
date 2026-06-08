"""Tests for the StackVM boot protocol + kernel launch path (Workstream D1).

Covers:
  * the ``struct StartupData`` / ``struct MemMapEntry`` binary layout and magic,
  * memory-map composition (contiguous, non-overlapping, covers all of RAM,
    correctly typed regions for the kernel image / initramfs / bootdata),
  * populate -> parse round-trip of every field, with and without an initramfs
    and devicetree blob,
  * the kernel launch path: a kernel image is entered in kernel mode with the
    MMU off, interrupts disabled, SVSR_SDP pointing at a valid StartupData, and a
    kernel stack at the top of RAM,
  * an end-to-end run: a tiny kernel reads SVSR_SDP, dereferences StartupData,
    and writes results back into memory.
"""

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

_CPP_TMPDIRS = []


def _compile_cpp_backend_or_skip():
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        raise unittest.SkipTest("C++ compiler not available")
    tmp = tempfile.TemporaryDirectory()
    _CPP_TMPDIRS.append(tmp)
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    out = os.path.join(tmp.name, "stack_vm_test" + suffix)
    subprocess.check_call(
        [
            compiler,
            "-std=c++17",
            "-shared",
            "-fPIC",
            os.path.join(REPO_ROOT, "StackVM", "cpp", "stack_vm.cpp"),
            "-o",
            out,
        ]
    )
    os.environ["STACKVM_CPP_LIB"] = out
    sys.modules.pop("IsaacCompiler.StackVM.CppStackVM", None)
    importlib.invalidate_caches()
    return out

from IsaacCompiler.StackVM.boot import (
    BOOT_PAGE_SIZE,
    MEM_MAP_ENTRY_SIZE,
    STARTUP_DATA_SIZE,
    SVMEM_BOOTDATA,
    SVMEM_INITRAMFS,
    SVMEM_KERNEL,
    SVMEM_RAM,
    SVMEM_RESERVED,
    SVSD_MAGIC,
    SVSD_VERSION,
    boot_kernel,
    build_boot_image,
    populate_startup_data,
    read_startup_data,
)
from IsaacCompiler.StackVM.PyStackVM import (
    BC_HLT,
    BC_LOAD,
    BC_STOR,
    BCR_ABS_A8,
    BCR_ABS_S8,
    BCR_SYSREG,
    SVSR_CORE_ID,
    SVSR_FLAGS,
    SVSR_KERNEL_BP,
    SVSR_KERNEL_SP,
    SVSR_SDP,
    VM_DISABLED,
)

_SZ8 = 0x60  # size-class 3 (8 bytes) in the high 3 bits of a BCR operand byte


# ---------------------------------------------------------------------------
# Static ABI invariants
# ---------------------------------------------------------------------------


class TestAbiConstants(unittest.TestCase):
    def test_magic_is_ascii_svmboot1(self):
        self.assertEqual(SVSD_MAGIC, int.from_bytes(b"SVMBOOT1", "little"))

    def test_struct_sizes(self):
        self.assertEqual(STARTUP_DATA_SIZE, 104)
        self.assertEqual(MEM_MAP_ENTRY_SIZE, 24)


# ---------------------------------------------------------------------------
# Memory-map composition + layout planning
# ---------------------------------------------------------------------------


def _assert_map_covers(test, mem_map, vm_size):
    """The map must tile [0, vm_size) exactly: sorted, contiguous, no gaps."""
    test.assertGreater(len(mem_map), 0)
    test.assertEqual(mem_map[0].base, 0)
    cursor = 0
    for entry in mem_map:
        test.assertEqual(entry.base, cursor, "non-contiguous / overlapping map")
        test.assertGreater(entry.size, 0)
        cursor = entry.base + entry.size
    test.assertEqual(cursor, vm_size, "map does not cover all of RAM")


class TestLayout(unittest.TestCase):
    def test_regions_are_typed_and_aligned(self):
        image = build_boot_image(
            vm_size=1 << 20,
            kernel_len=5000,
            kernel_base=0x1000,
            cmdline="root=/dev/vda ro",
            initramfs=b"INITRAMFS" * 100,
            dtb=b"\xd0\x0d\xfe\xed" + b"dtb-body",
        )
        _assert_map_covers(self, image.mem_map, image.vm_size)

        # Every carved region is page aligned.
        for e in image.mem_map:
            self.assertEqual(e.base % BOOT_PAGE_SIZE, 0)
            self.assertEqual(e.size % BOOT_PAGE_SIZE, 0)

        types = [e.type for e in image.mem_map]
        # Exactly one kernel / initramfs / bootdata region.
        self.assertEqual(types.count(SVMEM_KERNEL), 1)
        self.assertEqual(types.count(SVMEM_INITRAMFS), 1)
        self.assertEqual(types.count(SVMEM_BOOTDATA), 1)
        # Low memory below the kernel is reserved.
        self.assertEqual(image.mem_map[0].type, SVMEM_RESERVED)
        # Free RAM exists above the boot data (where the stack lives).
        self.assertEqual(image.mem_map[-1].type, SVMEM_RAM)

        kernel_region = next(e for e in image.mem_map if e.type == SVMEM_KERNEL)
        self.assertEqual(kernel_region.base, image.kernel_base)
        self.assertEqual(kernel_region.end, image.kernel_end)

        initramfs_region = next(e for e in image.mem_map if e.type == SVMEM_INITRAMFS)
        self.assertEqual(initramfs_region.base, image.initramfs_base)

    def test_regions_do_not_overlap(self):
        image = build_boot_image(vm_size=1 << 20, kernel_len=200)
        seen = []
        for e in image.mem_map:
            for b, end in seen:
                self.assertFalse(b < e.end and e.base < end, "regions overlap")
            seen.append((e.base, e.end))

    def test_too_small_vm_raises(self):
        with self.assertRaises(ValueError):
            build_boot_image(vm_size=0x800, kernel_len=0x4000)

    def test_kernel_base_must_be_aligned(self):
        with self.assertRaises(ValueError):
            build_boot_image(vm_size=1 << 20, kernel_len=10, kernel_base=0x1001)


# ---------------------------------------------------------------------------
# populate -> parse round-trip
# ---------------------------------------------------------------------------


class TestPopulateParse(unittest.TestCase):
    def test_full_roundtrip(self):
        cmdline = "console=ttyS0 root=/dev/vda1 ro quiet"
        initramfs = bytes(range(256)) * 3
        dtb = b"\xd0\x0d\xfe\xed" + b"devicetree-blob-payload"
        vm_size = 1 << 20

        image = build_boot_image(
            vm_size=vm_size,
            kernel_len=4096,
            kernel_base=0x1000,
            cmdline=cmdline,
            initramfs=initramfs,
            dtb=dtb,
            core_count=4,
            boot_core_id=0,
        )
        memory = bytearray(vm_size)
        addr = populate_startup_data(memory, image, initramfs=initramfs)
        self.assertEqual(addr, image.startup_data_addr)

        sd = read_startup_data(memory, addr)
        self.assertTrue(sd.is_valid)
        self.assertEqual(sd.magic, SVSD_MAGIC)
        self.assertEqual(sd.version, SVSD_VERSION)
        self.assertEqual(sd.struct_size, STARTUP_DATA_SIZE)
        self.assertEqual(sd.core_count, 4)
        self.assertEqual(sd.boot_core_id, 0)

        # Memory map parsed back matches the planned map and tiles RAM.
        self.assertEqual(sd.mem_map_count, len(image.mem_map))
        _assert_map_covers(self, sd.mem_map, vm_size)

        # initramfs described + actually present in memory.
        self.assertEqual(sd.initramfs_base, image.initramfs_base)
        self.assertEqual(sd.initramfs_size, len(initramfs))
        self.assertEqual(
            bytes(memory[sd.initramfs_base : sd.initramfs_base + sd.initramfs_size]),
            initramfs,
        )

        # cmdline (NUL-terminated) round-trips.
        self.assertEqual(sd.cmdline, cmdline.encode("utf-8"))
        self.assertEqual(sd.cmdline_size, len(cmdline) + 1)

        # devicetree blob round-trips.
        self.assertEqual(sd.dtb, dtb)
        self.assertEqual(sd.dtb_size, len(dtb))

        # Every sub-table pointer lives inside the bootdata region.
        for ptr in (sd.mem_map_ptr, sd.cmdline_ptr, sd.dtb_ptr):
            self.assertGreaterEqual(ptr, image.bootdata_base)
            self.assertLess(ptr, image.bootdata_end)

    def test_no_initramfs_no_dtb(self):
        vm_size = 1 << 19
        image = build_boot_image(vm_size=vm_size, kernel_len=100, cmdline="")
        memory = bytearray(vm_size)
        populate_startup_data(memory, image)
        sd = read_startup_data(memory, image.startup_data_addr)

        self.assertEqual(sd.initramfs_base, 0)
        self.assertEqual(sd.initramfs_size, 0)
        self.assertEqual(sd.dtb_ptr, 0)
        self.assertEqual(sd.dtb_size, 0)
        self.assertIsNone(sd.dtb)
        # No initramfs region in the map.
        self.assertEqual([e for e in sd.mem_map if e.type == SVMEM_INITRAMFS], [])
        # cmdline is still a valid (empty) NUL-terminated string.
        self.assertEqual(sd.cmdline, b"")
        self.assertEqual(sd.cmdline_size, 1)


# ---------------------------------------------------------------------------
# Kernel launch path
# ---------------------------------------------------------------------------


class TestLaunchState(unittest.TestCase):
    def test_enters_kernel_mode_mmu_off(self):
        kernel_image = bytes([BC_HLT])
        vm, image = boot_kernel(
            kernel_image,
            vm_size=1 << 20,
            kernel_base=0x1000,
            cmdline="boot",
        )
        # Kernel privilege, MMU off, interrupts disabled at entry.
        self.assertEqual(vm.priv_lvl, 0)
        self.assertEqual(vm.virt_mem_mode, VM_DISABLED)
        flags = vm.sys_regs[SVSR_FLAGS]
        self.assertEqual((flags >> 8) & 1, 0, "priv bit must be kernel(0)")
        self.assertEqual((flags >> 14) & 1, 0, "interrupts must be off at entry")

        # Entry at the kernel base; image bytes loaded there.
        self.assertEqual(vm.ip, image.kernel_base)
        self.assertEqual(
            bytes(vm.memory[image.kernel_base : image.kernel_base + len(kernel_image)]),
            kernel_image,
        )

        # SVSR_SDP points at a valid StartupData.
        self.assertEqual(vm.sys_regs[SVSR_SDP], image.startup_data_addr)
        sd = read_startup_data(vm.memory, vm.sys_regs[SVSR_SDP])
        self.assertTrue(sd.is_valid)

        # Kernel stack at the very top of RAM.
        self.assertEqual(vm.sp, image.vm_size)
        self.assertEqual(vm.bp, image.vm_size)
        self.assertEqual(vm.sys_regs[SVSR_KERNEL_SP], image.vm_size)
        self.assertEqual(vm.sys_regs[SVSR_KERNEL_BP], image.vm_size)
        self.assertEqual(vm.sys_regs[SVSR_CORE_ID], image.boot_core_id)

    def test_cpp_backend_launch_state_matches_python(self):
        _compile_cpp_backend_or_skip()
        vm, image = boot_kernel(
            bytes([BC_HLT]),
            vm_size=1 << 20,
            kernel_base=0x1000,
            cmdline="boot",
            backend="cpp",
        )

        self.assertEqual(vm.priv_lvl, 0)
        self.assertEqual(vm.virt_mem_mode, VM_DISABLED)
        self.assertEqual(vm.ip, image.kernel_base)
        self.assertEqual(vm.sys_regs[SVSR_SDP], image.startup_data_addr)
        self.assertEqual(vm.sys_regs[SVSR_CORE_ID], image.boot_core_id)
        self.assertTrue(read_startup_data(vm.memory, vm.sys_regs[SVSR_SDP]).is_valid)


# ---------------------------------------------------------------------------
# End-to-end execution
# ---------------------------------------------------------------------------


def _build_probe_kernel(result_magic: int, result_sdp: int) -> bytes:
    """A kernel that stores SVSR_SDP and *SVSR_SDP (the StartupData magic) into
    fixed memory slots, then halts."""
    code = bytearray()
    # *result_sdp = SVSR_SDP
    code += bytes([BC_LOAD, _SZ8 | BCR_SYSREG, SVSR_SDP])
    code += bytes([BC_STOR, _SZ8 | BCR_ABS_A8]) + result_sdp.to_bytes(8, "little")
    # *result_magic = *(uint64*)SVSR_SDP
    code += bytes([BC_LOAD, _SZ8 | BCR_SYSREG, SVSR_SDP])
    code += bytes([BC_LOAD, _SZ8 | BCR_ABS_S8])
    code += bytes([BC_STOR, _SZ8 | BCR_ABS_A8]) + result_magic.to_bytes(8, "little")
    code += bytes([BC_HLT])
    return bytes(code)


class TestEndToEnd(unittest.TestCase):
    def test_kernel_reads_startupdata_via_sdp(self):
        vm_size = 1 << 20
        # Result slots high in free RAM, well clear of the (tiny) kernel stack.
        result_magic = vm_size - 0x1000
        result_sdp = vm_size - 0x1000 + 8

        kernel_image = _build_probe_kernel(result_magic, result_sdp)
        vm, image = boot_kernel(
            kernel_image,
            vm_size=vm_size,
            kernel_base=0x1000,
            cmdline="probe",
            initramfs=b"cpio-payload",
        )
        vm.execute()

        got_sdp = int.from_bytes(vm.memory[result_sdp : result_sdp + 8], "little")
        got_magic = int.from_bytes(vm.memory[result_magic : result_magic + 8], "little")

        self.assertEqual(got_sdp, image.startup_data_addr)
        self.assertEqual(got_magic, SVSD_MAGIC)
        # The kernel halted normally.
        self.assertEqual(vm.running, 0)


if __name__ == "__main__":
    unittest.main()
