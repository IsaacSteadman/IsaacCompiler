"""Tests for D1b.5 / D1b.6 -- standardized UEFI boot on StackVM.

These cover the *milestones* called out in the plan's D1b.6:

  1. PE round-trip: compile -> link -> inspect a ``.efi``.
  2. A trivial EFI app prints via Simple Text Output under the minimal firmware
     (exercising the in-VM EFIAPI service-dispatch trap).
  3. An EFI-stub mini-kernel boots, calls ``GetMemoryMap()`` / ``ExitBootServices()``
     through the firmware, and continues running.
  4. (stretch) A GRUB-style EFI bootloader ``LoadImage``/``StartImage`` chain-loads
     a mini-kernel.

The EFI apps are hand-assembled StackVM bytecode so the tests exercise the
firmware's EFIAPI calling convention + service dispatch directly (independent of
the C compiler's code generation, which is covered by the PE round-trip test and
``tests/test_pe_support.py``).
"""

import os
import struct
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.code_gen.stackvm_binutils.executable_file import StackVMExecutable
from IsaacCompiler.code_gen.stackvm_binutils.pe_file import (
    IMAGE_FILE_MACHINE_STACKVM,
    IMAGE_SUBSYSTEM_EFI_APPLICATION,
    dumps_pe_executable,
    is_pe_bytes,
    read_pe_image,
)
from IsaacCompiler.StackVM.PyStackVM import (
    BC_ADD8,
    BC_ADD_SP8,
    BC_CALL,
    BC_HLT,
    BC_LOAD,
    BC_RST_SP8,
    BC_STOR,
    BC_SUB8,
    BCR_ABS_A8,
    BCR_ABS_C,
    BCR_ABS_S8,
    BCR_R_BP8,
    BCR_REG_BP,
    BCR_SZ_8,
    BCR_TOS,
)
from IsaacCompiler.StackVM.uefi import (
    EFI_MEMORY_DESCRIPTOR_SIZE,
    EFI_SUCCESS,
    MinimalUefiFirmware,
    run_uefi_app,
)


# ---------------------------------------------------------------------------
# Tiny StackVM bytecode assembler for EFI apps
# ---------------------------------------------------------------------------

# The minimal firmware enters an EFI image with bp = top-of-RAM and the EFIAPI
# arguments laid directly below it: ImageHandle @ bp-24, SystemTable @ bp-16.
IMAGE_HANDLE_BP = -24
SYSTEM_TABLE_BP = -16

# Member offsets inside the firmware tables (UEFI 2.x order; offset = 0x18 + 8*n).
SYSTAB_BOOT_SERVICES = 0x60
SYSTAB_CON_OUT = 0x40
BS_GET_MEMORY_MAP = 0x38  # member 4
BS_LOAD_IMAGE = 0xC8  # member 22
BS_START_IMAGE = 0xD0  # member 23
BS_EXIT_BOOT_SERVICES = 0xE8  # member 26
CON_OUT_OUTPUT_STRING = 0x08  # member 1


class EfiAsm:
    """Emits the handful of StackVM opcodes the test apps need."""

    def __init__(self):
        self.code = bytearray()

    def _raw(self, *b):
        self.code += bytes(b)
        return self

    def _u64(self, v):
        self.code += (v & ((1 << 64) - 1)).to_bytes(8, "little")
        return self

    def _i64(self, v):
        self.code += int(v).to_bytes(8, "little", signed=True)
        return self

    # value producers ----------------------------------------------------
    def const(self, v):  # push 8-byte immediate
        return self._raw(BC_LOAD, BCR_SZ_8 | BCR_ABS_C)._u64(v)

    def ld_bp(self, off):  # push *(bp + off)
        return self._raw(BC_LOAD, BCR_SZ_8 | BCR_R_BP8)._i64(off)

    def ld_abs(self, addr):  # push *(addr)
        return self._raw(BC_LOAD, BCR_SZ_8 | BCR_ABS_A8)._u64(addr)

    def deref(self):  # pop addr, push *(addr)
        return self._raw(BC_LOAD, BCR_SZ_8 | BCR_ABS_S8)

    def push_bp(self):  # push bp
        return self._raw(BC_LOAD, BCR_SZ_8 | BCR_REG_BP)

    def peek_tos(self):  # push *(sp)  (peek the current top of stack)
        return self._raw(BC_LOAD, BCR_SZ_8 | BCR_TOS)

    # arithmetic ---------------------------------------------------------
    def add(self):
        return self._raw(BC_ADD8)

    def sub(self):  # (first pushed) - (second pushed)
        return self._raw(BC_SUB8)

    # memory + stack -----------------------------------------------------
    def stor_abs(self, addr):  # pop value, store at addr
        return self._raw(BC_STOR, BCR_SZ_8 | BCR_ABS_A8)._u64(addr)

    def add_sp(self, n):  # reserve n bytes of stack
        return self.const(n)._raw(BC_ADD_SP8)

    def rst_sp(self, n):  # release n bytes of stack
        return self.const(n)._raw(BC_RST_SP8)

    def call(self):  # pop fn ptr, call it
        return self._raw(BC_CALL)

    def hlt(self):
        return self._raw(BC_HLT)

    # high-level helpers -------------------------------------------------
    def push_system_table(self):
        return self.ld_bp(SYSTEM_TABLE_BP)

    def push_boot_service(self, member_off):
        """Push *(*(SystemTable + BootServices) + member_off)."""
        self.push_system_table().const(SYSTAB_BOOT_SERVICES).add().deref()
        return self.const(member_off).add().deref()

    def push_con_out(self):
        return self.push_system_table().const(SYSTAB_CON_OUT).add().deref()

    def push_con_out_fn(self, member_off):
        self.push_con_out().const(member_off).add().deref()
        return self


def build_efi_app(asm: EfiAsm, *, data: bytes = b"", image_size: int = 0x2200):
    """Wrap *asm*'s code + a page-aligned data blob into a PE32+ EFI image.

    Code lands at the image base (entry offset 0); *data* is placed at image
    offset 0x1000, i.e. runtime address ``app_base + 0x1000``.
    """
    mem = bytearray(image_size)
    code = asm.code
    assert len(code) <= 0x1000, "test app code too large"
    mem[0 : len(code)] = code
    if data:
        assert 0x1000 + len(data) <= image_size
        mem[0x1000 : 0x1000 + len(data)] = data
    exe = StackVMExecutable(
        bytes(mem),
        code_segment_end=len(code),
        data_segment_start=0x1000,
        file_size=image_size,
        base_relocations=(),
    )
    return dumps_pe_executable(exe, entry=0)


def _run_cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "IsaacCompiler"] + list(args),
        cwd=REPO_PARENT if cwd is None else cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": REPO_PARENT},
    )


# ---------------------------------------------------------------------------
# Milestone 1: PE round-trip (compile -> link -> inspect .efi)
# ---------------------------------------------------------------------------


class PeRoundTripMilestoneTests(unittest.TestCase):
    def test_compile_link_inspect_efi(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "hello.c")
            efi = os.path.join(tmp, "hello.efi")
            with open(src, "w") as fl:
                fl.write(
                    "unsigned long efi_main(void *ImageHandle, void *SystemTable)\n"
                    "{ return 0; }\n"
                )
            proc = _run_cli(["gcc", src, "-o", efi, "--subsystem", "efi-application"])
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            with open(efi, "rb") as fl:
                blob = fl.read()

            # Inspect: it is a structurally valid PE32+ StackVM EFI application.
            self.assertTrue(is_pe_bytes(blob))
            pe = read_pe_image(blob)
            self.assertEqual(pe.machine, IMAGE_FILE_MACHINE_STACKVM)
            self.assertEqual(pe.subsystem, IMAGE_SUBSYSTEM_EFI_APPLICATION)
            self.assertIsNotNone(pe.section_by_name(".text"))

            # The host readelf CLI renders it as a PE32+ EFI application.
            proc = _run_cli(["readelf", "-h", "-S", efi])
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertIn("PE32+", proc.stdout)
            self.assertIn("EFI Application", proc.stdout)

    def test_loads_back_into_executable(self):
        from IsaacCompiler.code_gen.stackvm_binutils.pe_file import loads_pe_executable

        asm = EfiAsm().hlt()
        blob = build_efi_app(asm)
        back = loads_pe_executable(blob)
        self.assertEqual(back.code_segment_end, len(asm.code))
        self.assertEqual(back.memory[0], BC_HLT)


# ---------------------------------------------------------------------------
# Milestone 2: trivial EFI app prints via Simple Text Output
# ---------------------------------------------------------------------------


class SimpleTextOutputMilestoneTests(unittest.TestCase):
    def _hello_app(self, message="Hello, UEFI!"):
        # CHAR16 message placed in the image data segment (runtime app_base+0x1000).
        data = message.encode("utf-16-le") + b"\x00\x00"
        string_addr = 0x1000 + 0x1000  # app_base (0x1000) + data offset (0x1000)
        asm = EfiAsm()
        # ConOut->OutputString(This=ConOut, String=&message)
        asm.add_sp(8)  # caller-reserved EFI_STATUS return slot
        asm.const(string_addr)  # arg1: String
        asm.push_con_out()  # arg0: This
        asm.push_con_out_fn(CON_OUT_OUTPUT_STRING)  # OutputString fn ptr
        asm.call()
        # Capture the returned EFI_STATUS into the data segment for inspection.
        asm.rst_sp(16)  # pop the 2 args -> return slot is now TOS
        asm.peek_tos()
        asm.stor_abs(0x1000 + 0x1100)  # store status at app_base+0x1100
        asm.hlt()
        return build_efi_app(asm, data=data), string_addr

    def test_app_prints_via_simple_text_output(self):
        app, _string_addr = self._hello_app("Hello, UEFI!")
        out = bytearray()
        vm, launch, firmware = run_uefi_app(app, vm_size=1 << 20, console_output=out)
        self.assertEqual(vm.running, 0)
        self.assertEqual(bytes(out), "Hello, UEFI!".encode("utf-8"))
        # The service returned EFI_SUCCESS into the caller's return slot.
        status = int.from_bytes(vm.memory[0x1000 + 0x1100 : 0x1000 + 0x1108], "little")
        self.assertEqual(status, EFI_SUCCESS)

    def test_output_goes_through_system_table_pointer(self):
        # Sanity: the app reached OutputString by walking SystemTable->ConOut, so
        # the printed text proves the table layout the firmware built is correct.
        app, _ = self._hello_app("ABC")
        out = bytearray()
        run_uefi_app(app, vm_size=1 << 20, console_output=out)
        self.assertEqual(bytes(out), b"ABC")


# ---------------------------------------------------------------------------
# Milestone 3: EFI-stub kernel calls GetMemoryMap()/ExitBootServices()
# ---------------------------------------------------------------------------

# Scratch layout inside the stub's data segment (runtime app_base + 0x1000 == 0x2000).
STUB_MAPSIZE = 0x2000
STUB_MAPKEY = 0x2010
STUB_DESCSIZE = 0x2018
STUB_DESCVER = 0x2020
STUB_EBS_STATUS = 0x2030
STUB_CONTINUED = 0x2038
STUB_MAPBUF = 0x2100
STUB_CONTINUE_MAGIC = 0xC1A11ED


class EfiStubMilestoneTests(unittest.TestCase):
    def _stub_kernel(self):
        asm = EfiAsm()
        # *MapSize = 0xF00 (generous: the real map is far smaller).
        asm.const(0xF00).stor_abs(STUB_MAPSIZE)
        # GetMemoryMap(&MapSize, MapBuf, &MapKey, &DescSize, &DescVer)
        asm.add_sp(8)  # return slot
        asm.const(STUB_DESCVER)  # arg4
        asm.const(STUB_DESCSIZE)  # arg3
        asm.const(STUB_MAPKEY)  # arg2
        asm.const(STUB_MAPBUF)  # arg1
        asm.const(STUB_MAPSIZE)  # arg0
        asm.push_boot_service(BS_GET_MEMORY_MAP)
        asm.call()
        asm.rst_sp(40)  # 5 args
        # ExitBootServices(ImageHandle, MapKey)
        asm.add_sp(8)  # return slot
        asm.ld_abs(STUB_MAPKEY)  # arg1: MapKey (from GetMemoryMap)
        asm.ld_bp(IMAGE_HANDLE_BP)  # arg0: ImageHandle
        asm.push_boot_service(BS_EXIT_BOOT_SERVICES)
        asm.call()
        asm.rst_sp(16)  # 2 args -> return slot is TOS
        asm.peek_tos()
        asm.stor_abs(STUB_EBS_STATUS)  # record the EBS status
        # "continue past ExitBootServices": write a marker, then halt.
        asm.const(STUB_CONTINUE_MAGIC).stor_abs(STUB_CONTINUED)
        asm.hlt()
        return build_efi_app(asm)

    def test_stub_gets_map_exits_boot_services_and_continues(self):
        vm, launch, firmware = run_uefi_app(self._stub_kernel(), vm_size=1 << 20)
        self.assertEqual(vm.running, 0)

        # GetMemoryMap wrote a non-empty, descriptor-sized map.
        required = int.from_bytes(vm.memory[STUB_MAPSIZE : STUB_MAPSIZE + 8], "little")
        self.assertGreater(required, 0)
        self.assertEqual(required % EFI_MEMORY_DESCRIPTOR_SIZE, 0)
        desc_size = int.from_bytes(vm.memory[STUB_DESCSIZE : STUB_DESCSIZE + 8], "little")
        self.assertEqual(desc_size, EFI_MEMORY_DESCRIPTOR_SIZE)
        # At least one descriptor parses out of the buffer the stub passed in.
        first = struct.unpack_from("<IIQQQQ", vm.memory, STUB_MAPBUF)
        self.assertGreater(first[4], 0)  # NumberOfPages > 0

        # ExitBootServices succeeded and tore down boot services.
        ebs_status = int.from_bytes(
            vm.memory[STUB_EBS_STATUS : STUB_EBS_STATUS + 8], "little"
        )
        self.assertEqual(ebs_status, EFI_SUCCESS)
        self.assertFalse(firmware.boot_services_active)

        # The stub continued executing after ExitBootServices.
        continued = int.from_bytes(
            vm.memory[STUB_CONTINUED : STUB_CONTINUED + 8], "little"
        )
        self.assertEqual(continued, STUB_CONTINUE_MAGIC)

    def test_stale_map_key_is_rejected(self):
        # Loading without running: a stale MapKey must be rejected by ExitBootServices.
        firmware = MinimalUefiFirmware(vm_size=1 << 20)
        launch = firmware.load_efi_app(self._stub_kernel())
        good_key = firmware.map_key
        from IsaacCompiler.StackVM.uefi import EFI_INVALID_PARAMETER

        self.assertEqual(
            firmware.exit_boot_services(launch.image_handle, good_key - 1),
            EFI_INVALID_PARAMETER,
        )
        self.assertTrue(firmware.boot_services_active)
        self.assertEqual(
            firmware.exit_boot_services(launch.image_handle, good_key), EFI_SUCCESS
        )
        self.assertFalse(firmware.boot_services_active)


# ---------------------------------------------------------------------------
# Milestone 4 (stretch): GRUB-style chain-load via LoadImage / StartImage
# ---------------------------------------------------------------------------

CHAIN_MARKER_ADDR = 0x900
CHAIN_MARKER = 0xC0FFEE


class ChainLoadMilestoneTests(unittest.TestCase):
    def _mini_kernel(self):
        asm = EfiAsm()
        asm.const(CHAIN_MARKER).stor_abs(CHAIN_MARKER_ADDR)
        asm.hlt()
        return build_efi_app(asm, image_size=0x80)

    def _bootloader(self, *, src_addr=0, src_size=0, src_data=b""):
        asm = EfiAsm()
        # local 8-byte slot at bp-32 to receive the loaded image handle.
        asm.add_sp(8)
        # LoadImage(BootPolicy=1, ParentImageHandle, DevicePath=0, SourceBuffer,
        #           SourceSize, &ImageHandle).  When SourceBuffer is 0 the firmware
        #           loads the default boot image on the device.
        asm.add_sp(8)  # return slot
        asm.push_bp().const(32).sub()  # arg5: &ImageHandle (bp-32)
        asm.const(src_size)  # arg4: SourceSize
        asm.const(src_addr)  # arg3: SourceBuffer
        asm.const(0)  # arg2: DevicePath
        asm.ld_bp(IMAGE_HANDLE_BP)  # arg1: ParentImageHandle
        asm.const(1)  # arg0: BootPolicy
        asm.push_boot_service(BS_LOAD_IMAGE)
        asm.call()
        asm.rst_sp(48)  # 6 args
        # StartImage(ImageHandle, ExitDataSize=0, ExitData=0) -- chain-loads.
        asm.add_sp(8)  # return slot
        asm.const(0)  # arg2: ExitData**
        asm.const(0)  # arg1: ExitDataSize*
        asm.ld_bp(-32)  # arg0: ImageHandle (from LoadImage)
        asm.push_boot_service(BS_START_IMAGE)
        asm.call()
        asm.hlt()  # unreachable: StartImage chain-loads and does not return
        # Stage the source kernel PE in the data segment when requested.
        image_size = max(0x2200, 0x1000 + len(src_data) + 0x100)
        return build_efi_app(asm, data=src_data, image_size=image_size)

    def test_bootloader_chain_loads_mini_kernel(self):
        firmware = MinimalUefiFirmware(
            vm_size=1 << 20, boot_image_payload=self._mini_kernel()
        )
        firmware.load_efi_app(self._bootloader())
        firmware.run()
        self.assertEqual(firmware.vm.running, 0)
        # The bootloader loaded exactly one image and chain-loaded it.
        self.assertEqual(len(firmware.loaded_images), 1)
        self.assertTrue(next(iter(firmware.loaded_images.values())).started)
        # The chain-loaded mini-kernel ran and wrote its marker.
        marker = int.from_bytes(
            firmware.vm.memory[CHAIN_MARKER_ADDR : CHAIN_MARKER_ADDR + 8], "little"
        )
        self.assertEqual(marker, CHAIN_MARKER)

    def test_load_image_from_source_buffer(self):
        # LoadImage with an explicit SourceBuffer: the bootloader carries the
        # mini-kernel PE in its own data segment (runtime app_base + 0x1000).
        kernel_pe = self._mini_kernel()
        src_addr = 0x1000 + 0x1000  # app_base + data offset
        firmware = MinimalUefiFirmware(vm_size=1 << 20)  # no default boot image
        firmware.load_efi_app(
            self._bootloader(
                src_addr=src_addr, src_size=len(kernel_pe), src_data=kernel_pe
            )
        )
        firmware.run()
        self.assertEqual(len(firmware.loaded_images), 1)
        marker = int.from_bytes(
            firmware.vm.memory[CHAIN_MARKER_ADDR : CHAIN_MARKER_ADDR + 8], "little"
        )
        self.assertEqual(marker, CHAIN_MARKER)


if __name__ == "__main__":
    unittest.main()
