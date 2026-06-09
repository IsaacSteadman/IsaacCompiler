"""Tests for D1b.3/D1b.4 -- StackVM UEFI substrate and minimal firmware."""

import os
import struct
import sys
import tempfile
import unittest
import uuid
import zlib

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.code_gen.stackvm_binutils.executable_file import StackVMExecutable
from IsaacCompiler.code_gen.stackvm_binutils.pe_file import dumps_pe_executable
from IsaacCompiler.StackVM.PyStackVM import BC_HLT
from IsaacCompiler.StackVM.mmio import MemoryBlockImage
from IsaacCompiler.StackVM.uefi import (
    EFI_BUFFER_TOO_SMALL,
    EFI_DTB_TABLE_GUID,
    EFI_GRAPHICS_OUTPUT_PROTOCOL_GUID,
    EFI_INVALID_PARAMETER,
    EFI_LOADED_IMAGE_PROTOCOL_GUID,
    EFI_MEMORY_DESCRIPTOR_SIZE,
    EFI_SUCCESS,
    EFI_SYSTEM_TABLE_SIGNATURE,
    EFI_BOOT_SERVICES_SIGNATURE,
    EFI_RUNTIME_SERVICES_SIGNATURE,
    EFI_BOOT_SERVICES_DATA,
    EVT_TIMER,
    MinimalUefiFirmware,
    TIMER_RELATIVE,
    UefiSimpleFileSystem,
    UefiVariableStore,
    boot_uefi_app,
    pack_guid,
    unpack_guid,
)


def _efi_hlt_image():
    mem = bytearray(0x1010)
    mem[0] = BC_HLT
    mem[0x1000:0x1008] = (0).to_bytes(8, "little")
    exe = StackVMExecutable(
        bytes(mem),
        code_segment_end=1,
        data_segment_start=0x1000,
        file_size=0x1008,
        base_relocations=(0x1000,),
    )
    return dumps_pe_executable(exe, entry=0)


def _table_header(memory, addr):
    return struct.unpack_from("<QIIII", memory, addr)


def _assert_table_crc(test, memory, addr):
    sig, rev, size, crc, reserved = _table_header(memory, addr)
    blob = bytearray(memory[addr : addr + size])
    blob[16:20] = b"\0\0\0\0"
    test.assertEqual(crc, zlib.crc32(blob) & 0xFFFFFFFF)
    test.assertEqual(reserved, 0)
    test.assertGreater(rev, 0)
    return sig, size


class UefiFirmwareTablesTests(unittest.TestCase):
    def test_loads_pe_app_builds_tables_protocols_and_stack_handoff(self):
        block = MemoryBlockImage(4096)
        vm, launch, firmware = boot_uefi_app(
            _efi_hlt_image(),
            vm_size=1 << 20,
            block_backend=block,
            console_input=b"K",
            rtc_ns=lambda: 1_600_000_000_123_456_789,
        )

        self.assertEqual(vm.ip, launch.entry_addr)
        self.assertEqual(vm.ip, launch.app_base)
        self.assertEqual(vm.get(8, vm.sp), launch.image_handle)
        self.assertEqual(vm.get(8, vm.sp + 8), launch.system_table_addr)
        self.assertEqual(
            int.from_bytes(vm.memory[launch.app_base + 0x1000 : launch.app_base + 0x1008], "little"),
            launch.app_base,
        )

        sig, size = _assert_table_crc(self, vm.memory, launch.system_table_addr)
        self.assertEqual(sig, EFI_SYSTEM_TABLE_SIGNATURE)
        self.assertEqual(size, 0x78)
        self.assertEqual(vm.get(8, launch.system_table_addr + 0x58), launch.runtime_services_addr)
        self.assertEqual(vm.get(8, launch.system_table_addr + 0x60), launch.boot_services_addr)
        self.assertEqual(vm.get(8, launch.system_table_addr + 0x68), 1)
        self.assertEqual(vm.get(8, launch.system_table_addr + 0x70), launch.configuration_table_addr)

        sig, _size = _assert_table_crc(self, vm.memory, launch.boot_services_addr)
        self.assertEqual(sig, EFI_BOOT_SERVICES_SIGNATURE)
        sig, _size = _assert_table_crc(self, vm.memory, launch.runtime_services_addr)
        self.assertEqual(sig, EFI_RUNTIME_SERVICES_SIGNATURE)

        config = launch.configuration_table_addr
        self.assertEqual(unpack_guid(vm.memory[config : config + 16]), EFI_DTB_TABLE_GUID)
        self.assertEqual(vm.get(8, config + 16), launch.dtb_addr)
        self.assertTrue(vm.memory[launch.dtb_addr : launch.dtb_addr + 4])

        status, loaded_image = firmware.handle_protocol(
            launch.image_handle,
            EFI_LOADED_IMAGE_PROTOCOL_GUID,
        )
        self.assertEqual(status, EFI_SUCCESS)
        self.assertEqual(vm.get(8, loaded_image + 64), launch.app_base)

        status, fb_handle, gop = firmware.locate_protocol(EFI_GRAPHICS_OUTPUT_PROTOCOL_GUID)
        self.assertEqual(status, EFI_SUCCESS)
        self.assertNotEqual(fb_handle, 0)
        self.assertNotEqual(gop, 0)

        vm.execute()
        self.assertEqual(vm.running, 0)

    def test_table_function_pointers_dispatch_to_services(self):
        _vm, launch, firmware = boot_uefi_app(_efi_hlt_image(), vm_size=1 << 20)
        con_out = launch.vm.get(8, launch.system_table_addr + 0x40)
        output_string = launch.vm.get(8, con_out + 8)

        self.assertEqual(firmware.call_service(output_string, "hello"), EFI_SUCCESS)
        self.assertEqual(firmware.console_output, b"hello")


class UefiDeviceSubstrateTests(unittest.TestCase):
    def test_console_rtc_block_simplefs_variables_and_gop(self):
        with tempfile.TemporaryDirectory() as td:
            nvram_path = os.path.join(td, "vars.json")
            block = MemoryBlockImage(8192)
            firmware = MinimalUefiFirmware(
                vm_size=1 << 20,
                block_backend=block,
                console_input=b"Z",
                console_output=bytearray(),
                nvram_path=nvram_path,
                rtc_ns=lambda: 1_600_000_000_123_456_789,
                framebuffer_width=4,
                framebuffer_height=3,
            )
            firmware.load_efi_app(_efi_hlt_image())

            self.assertEqual(firmware.text_out.output_string("OK"), EFI_SUCCESS)
            self.assertEqual(firmware.console_output, b"OK")
            self.assertEqual(firmware.text_in.read_key_stroke(), (EFI_SUCCESS, ord("Z")))

            status, now = firmware.get_time()
            self.assertEqual(status, EFI_SUCCESS)
            self.assertEqual(now["year"], 2020)
            self.assertEqual(now["nanosecond"], 123_456_789)

            guid = uuid.UUID("12345678-1234-5678-9abc-def012345678")
            self.assertEqual(
                firmware.variables.set_variable("BootNext", guid, b"\x01\x00", 7),
                EFI_SUCCESS,
            )
            persisted = UefiVariableStore(nvram_path)
            self.assertEqual(persisted.get_variable("BootNext", guid), (EFI_SUCCESS, 7, b"\x01\x00"))

            sector = b"A" * 512
            self.assertEqual(firmware.block_io.write_blocks(1, 2, sector), EFI_SUCCESS)
            self.assertEqual(firmware.block_io.read_blocks(1, 2, 512), (EFI_SUCCESS, sector))

            self.assertEqual(
                firmware.simple_file_system.write_file("\\EFI\\BOOT\\BOOT.SVM", b"kernel"),
                EFI_SUCCESS,
            )
            fs2 = UefiSimpleFileSystem(block)
            self.assertEqual(fs2.read_file("\\efi\\boot\\boot.svm"), (EFI_SUCCESS, b"kernel"))

            self.assertEqual(firmware.gop.write_pixel(2, 1, 0x11223344), EFI_SUCCESS)
            off = 1 * firmware.framebuffer.stride + 2 * 4
            self.assertEqual(firmware.framebuffer.snapshot()[off : off + 4], b"\x44\x33\x22\x11")

    def test_memory_map_events_and_exit_boot_services(self):
        _vm, launch, firmware = boot_uefi_app(_efi_hlt_image(), vm_size=1 << 20)

        status, required, key, desc_size, version, data = firmware.get_memory_map(0)
        self.assertEqual(status, EFI_BUFFER_TOO_SMALL)
        self.assertGreater(required, 0)
        self.assertEqual(desc_size, EFI_MEMORY_DESCRIPTOR_SIZE)
        self.assertEqual(data, b"")

        old_key = key
        status, addr = firmware.allocate_pages(2, EFI_BOOT_SERVICES_DATA)
        self.assertEqual(status, EFI_SUCCESS)
        self.assertNotEqual(firmware.map_key, old_key)
        self.assertEqual(
            firmware.exit_boot_services(launch.image_handle, old_key),
            EFI_INVALID_PARAMETER,
        )

        status, required, key, desc_size, version, data = firmware.get_memory_map(1 << 20)
        self.assertEqual(status, EFI_SUCCESS)
        descs = [
            struct.unpack_from("<IIQQQQ", data, i)
            for i in range(0, len(data), EFI_MEMORY_DESCRIPTOR_SIZE)
        ]
        self.assertTrue(
            any(d[0] == EFI_BOOT_SERVICES_DATA and d[2] == addr and d[4] == 2 for d in descs)
        )

        status, event = firmware.create_event(EVT_TIMER)
        self.assertEqual(status, EFI_SUCCESS)
        self.assertEqual(firmware.set_timer(event, TIMER_RELATIVE, 100), EFI_SUCCESS)
        self.assertGreaterEqual(firmware.timer.interval, 1)
        firmware.advance_time_100ns(99)
        self.assertNotEqual(firmware.check_event(event), EFI_SUCCESS)
        firmware.advance_time_100ns(1)
        self.assertEqual(firmware.check_event(event), EFI_SUCCESS)

        status, _required, key, _desc_size, _version, _data = firmware.get_memory_map(1 << 20)
        self.assertEqual(status, EFI_SUCCESS)
        self.assertEqual(firmware.exit_boot_services(launch.image_handle, key), EFI_SUCCESS)
        self.assertFalse(firmware.boot_services_active)


class UefiGuidTests(unittest.TestCase):
    def test_guid_packs_mixed_endian_like_uefi(self):
        guid = uuid.UUID("b1b621d5-f19c-41a5-830b-d9152c69aae0")
        self.assertEqual(unpack_guid(pack_guid(guid)), guid)


if __name__ == "__main__":
    unittest.main()
