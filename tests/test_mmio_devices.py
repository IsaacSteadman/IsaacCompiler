"""Tests for D5 -- MMIO devices and virtio-style transport."""

import os
import struct
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from IsaacCompiler.StackVM.PyStackVM import (
    AdvProgIntCtl,
    INT_HW_IO,
    SVSR_KERNEL_TLPTR,
    VM_4_LVL_9_BIT,
    VirtualMachine,
)
from IsaacCompiler.StackVM.mmio import (
    FB_REG_DIRTY_SEQ,
    FB_REG_FLUSH,
    FB_REG_FORMAT,
    FB_REG_HEIGHT,
    FB_REG_PIXEL_BASE,
    FB_REG_PIXEL_SIZE,
    FB_REG_STRIDE,
    FB_REG_WIDTH,
    FramebufferDevice,
    IC_REG_CLAIM,
    IC_REG_ENABLE,
    IC_REG_EOI,
    IC_REG_PENDING,
    IC_REG_ROUTE_BASE,
    InMemoryNetBackend,
    MemoryBlockImage,
    MmioBus,
    MmioInterruptController,
    RtcDevice,
    RTC_REG_NOW_NS,
    SVM_IRQ_UART0,
    SVM_IRQ_VIRTIO_BLK0,
    SVM_IRQ_VIRTIO_NET0,
    SVM_FB_FORMAT_XRGB8888,
    SVM_MMIO_FRAMEBUFFER0_BASE,
    SVM_MMIO_UART0_BASE,
    UART_IRQ_RX,
    UART_REG_DATA,
    UART_REG_IRQ_ENABLE,
    UART_REG_STATUS,
    UART_STATUS_RX_READY,
    UART_STATUS_TX_READY,
    UartSerialDevice,
    VIRTIO_BLK_S_OK,
    VIRTIO_BLK_SECTOR_SIZE,
    VIRTIO_BLK_T_IN,
    VIRTIO_BLK_T_OUT,
    VIRTIO_DEVICE_BLOCK,
    VIRTIO_DEVICE_NET,
    VIRTIO_MAGIC,
    VIRTIO_NET_HDR_SIZE,
    VIRTIO_REG_DEVICE_ID,
    VIRTIO_REG_INTERRUPT_STATUS,
    VIRTIO_REG_MAGIC,
    VIRTIO_REG_QUEUE_AVAIL,
    VIRTIO_REG_QUEUE_DESC,
    VIRTIO_REG_QUEUE_NOTIFY,
    VIRTIO_REG_QUEUE_NUM,
    VIRTIO_REG_QUEUE_SEL,
    VIRTIO_REG_QUEUE_USED,
    VIRTQ_DESC_F_NEXT,
    VIRTQ_DESC_F_WRITE,
    VIRTQ_DESC_SIZE,
    VirtioBlockDevice,
    VirtioNetDevice,
    HostBlockImage,
    build_default_mmio_machine,
)

UART_BASE = 0x2000
IC_BASE = 0x3000
RTC_BASE = 0x4000
BLK_BASE = 0x5000
NET_BASE = 0x6000

DESC = 0x0800
AVAIL = 0x0C00
USED = 0x0D00
HDR = 0x0E00
DATA = 0x1000
STATUS = 0x1200


def _vm(mem_size=0x20000):
    vm = VirtualMachine(mem_size, 0)
    vm.sp = vm.bp = len(vm.memory)
    vm.running = 1
    vm.set_flags(0xFF)
    return vm


def _write_desc(vm, desc_base, index, addr, length, flags=0, next_index=0):
    base = desc_base + index * VIRTQ_DESC_SIZE
    vm.memory[base : base + VIRTQ_DESC_SIZE] = struct.pack(
        "<QIHH", addr, length, flags, next_index
    )


def _setup_queue(vm, dev_base, queue, desc=DESC, avail=AVAIL, used=USED, num=8):
    vm.set(8, dev_base + VIRTIO_REG_QUEUE_SEL, queue)
    vm.set(8, dev_base + VIRTIO_REG_QUEUE_DESC, desc)
    vm.set(8, dev_base + VIRTIO_REG_QUEUE_AVAIL, avail)
    vm.set(8, dev_base + VIRTIO_REG_QUEUE_USED, used)
    vm.set(8, dev_base + VIRTIO_REG_QUEUE_NUM, num)
    vm.memory[avail : avail + 4 + num * 2] = b"\0" * (4 + num * 2)
    vm.memory[used : used + 4 + num * 8] = b"\0" * (4 + num * 8)


def _submit_one(vm, avail, head, idx=1):
    vm.memory[avail + 2 : avail + 4] = idx.to_bytes(2, "little")
    vm.memory[avail + 4 : avail + 6] = head.to_bytes(2, "little")


def _used_idx(vm, used=USED):
    return int.from_bytes(vm.memory[used + 2 : used + 4], "little")


class MmioDispatchAndInterruptTests(unittest.TestCase):
    def test_mmio_dispatches_past_backing_memory_and_leaves_ram_alone(self):
        output = bytearray()
        bus = MmioBus()
        uart = UartSerialDevice(output=output)
        bus.add_region(UART_BASE, 0x100, uart, "uart")
        vm = _vm(mem_size=0x1000)
        vm.attach_mmio_bus(bus)

        self.assertTrue(vm.set(1, UART_BASE + UART_REG_DATA, ord("A")))
        self.assertEqual(output, b"A")
        self.assertTrue(vm.set(1, 0x10, 0x5A))
        self.assertEqual(vm.get(1, 0x10), 0x5A)

    def test_mmio_dispatch_uses_translated_physical_address(self):
        output = bytearray()
        bus = MmioBus()
        bus.add_region(
            SVM_MMIO_UART0_BASE,
            0x100,
            UartSerialDevice(output=output),
            "uart",
        )
        vm = _vm(mem_size=0x10000)
        vm.attach_mmio_bus(bus)

        p4, p3, p2, p1 = 0x1000, 0x2000, 0x3000, 0x4000
        flags = 0x7  # valid + writable + executable
        vm.sys_regs[SVSR_KERNEL_TLPTR] = p4 | flags
        vm.memory[p4 : p4 + 8] = (p3 | flags).to_bytes(8, "little")
        vm.memory[p3 : p3 + 8] = (p2 | flags).to_bytes(8, "little")
        vm.memory[p2 : p2 + 8] = (p1 | flags).to_bytes(8, "little")
        virt = 0x8000
        pte1_index = ((virt >> 12) & 0x1FF) << 3
        vm.memory[p1 + pte1_index : p1 + pte1_index + 8] = (
            SVM_MMIO_UART0_BASE | flags
        ).to_bytes(8, "little")
        vm.set_flags(0xFF | (VM_4_LVL_9_BIT << 10))

        self.assertTrue(vm.set(1, virt + UART_REG_DATA, ord("V")))
        self.assertEqual(output, b"V")

    def test_uart_rx_irq_flows_through_mask_route_claim_and_eoi(self):
        apic = AdvProgIntCtl()
        ic = MmioInterruptController()
        uart = UartSerialDevice(irq_controller=ic, irq=SVM_IRQ_UART0, output=bytearray())
        bus = MmioBus()
        bus.add_region(IC_BASE, 0x1000, ic, "ic")
        bus.add_region(UART_BASE, 0x100, uart, "uart")
        vm = _vm()
        vm.attach_mmio_bus(bus)
        vm.apic = apic

        vm.set(8, IC_BASE + IC_REG_ROUTE_BASE + SVM_IRQ_UART0 * 8, INT_HW_IO)
        vm.set(8, UART_BASE + UART_REG_IRQ_ENABLE, UART_IRQ_RX)
        uart.inject_rx(b"z")
        self.assertFalse(apic.pending())
        self.assertEqual(vm.get(8, IC_BASE + IC_REG_PENDING), 1 << SVM_IRQ_UART0)

        vm.set(8, IC_BASE + IC_REG_ENABLE, 1 << SVM_IRQ_UART0)
        self.assertTrue(apic.pending())
        entry = apic.take_deliverable(True, 0xFF, lambda _int_n: 0x10)
        self.assertEqual(entry[0], INT_HW_IO)
        self.assertEqual(entry[1], SVM_IRQ_UART0)
        self.assertEqual(vm.get(8, IC_BASE + IC_REG_CLAIM), SVM_IRQ_UART0)
        self.assertEqual(vm.get(8, UART_BASE + UART_REG_STATUS), UART_STATUS_RX_READY | UART_STATUS_TX_READY)
        self.assertEqual(vm.get(1, UART_BASE + UART_REG_DATA), ord("z"))
        vm.set(8, IC_BASE + IC_REG_EOI, SVM_IRQ_UART0)
        self.assertEqual(vm.get(8, UART_BASE + UART_REG_STATUS), UART_STATUS_TX_READY)

    def test_rtc_reads_host_time_source(self):
        bus = MmioBus()
        bus.add_region(RTC_BASE, 0x100, RtcDevice(lambda: 1234567890123), "rtc")
        vm = _vm()
        vm.attach_mmio_bus(bus)

        self.assertEqual(vm.get(8, RTC_BASE + RTC_REG_NOW_NS), 1234567890123)

    def test_framebuffer_registers_pixel_aperture_and_flush(self):
        fb = FramebufferDevice(3, 2, pixel_base=0x9000)
        bus = MmioBus()
        bus.add_region(0x7000, 0x1000, fb, "fb")
        bus.add_region(fb.pixel_base, fb.pixel_size, fb.pixel_device, "fb-pixels")
        vm = _vm()
        vm.attach_mmio_bus(bus)

        self.assertEqual(vm.get(8, 0x7000 + FB_REG_WIDTH), 3)
        self.assertEqual(vm.get(8, 0x7000 + FB_REG_HEIGHT), 2)
        self.assertEqual(vm.get(8, 0x7000 + FB_REG_STRIDE), 12)
        self.assertEqual(vm.get(8, 0x7000 + FB_REG_FORMAT), SVM_FB_FORMAT_XRGB8888)
        self.assertEqual(vm.get(8, 0x7000 + FB_REG_PIXEL_BASE), 0x9000)
        self.assertEqual(vm.get(8, 0x7000 + FB_REG_PIXEL_SIZE), 24)

        vm.set(4, 0x9000 + 4, 0x11223344)
        self.assertEqual(fb.snapshot()[4:8], b"\x44\x33\x22\x11")
        self.assertEqual(vm.get(4, 0x9000 + 4), 0x11223344)
        self.assertEqual(vm.get(8, 0x7000 + FB_REG_DIRTY_SEQ), 1)
        self.assertEqual(fb.dirty_ranges, [(4, 8)])

        vm.set(8, 0x7000 + FB_REG_FLUSH, 1)
        self.assertEqual(fb.flush_count, 1)
        self.assertEqual(fb.dirty_ranges, [])

    def test_default_machine_can_attach_framebuffer(self):
        machine = build_default_mmio_machine(framebuffer=True, framebuffer_width=4, framebuffer_height=3)
        vm = _vm()
        machine.attach_to_vm(vm)

        self.assertIsNotNone(machine.framebuffer)
        self.assertEqual(vm.get(8, SVM_MMIO_FRAMEBUFFER0_BASE + FB_REG_WIDTH), 4)
        pixel_base = vm.get(8, SVM_MMIO_FRAMEBUFFER0_BASE + FB_REG_PIXEL_BASE)
        vm.set(4, pixel_base, 0xAABBCCDD)
        self.assertEqual(machine.framebuffer.snapshot()[:4], b"\xdd\xcc\xbb\xaa")


class VirtioBlockTests(unittest.TestCase):
    def _attach_block(self, backend):
        apic = AdvProgIntCtl()
        ic = MmioInterruptController()
        blk = VirtioBlockDevice(backend, irq_controller=ic, irq=SVM_IRQ_VIRTIO_BLK0)
        bus = MmioBus()
        bus.add_region(IC_BASE, 0x1000, ic, "ic")
        bus.add_region(BLK_BASE, 0x1000, blk, "blk")
        vm = _vm()
        vm.attach_mmio_bus(bus)
        vm.apic = apic
        vm.set(8, IC_BASE + IC_REG_ENABLE, 1 << SVM_IRQ_VIRTIO_BLK0)
        _setup_queue(vm, BLK_BASE, 0)
        return vm, apic

    def _submit_block_req(self, vm, req_type, sector, payload_len):
        vm.memory[HDR : HDR + 16] = struct.pack("<IIQ", req_type, 0, sector)
        vm.memory[STATUS] = 0xFF
        _write_desc(vm, DESC, 0, HDR, 16, VIRTQ_DESC_F_NEXT, 1)
        data_flags = VIRTQ_DESC_F_NEXT
        if req_type == VIRTIO_BLK_T_IN:
            data_flags |= VIRTQ_DESC_F_WRITE
        _write_desc(vm, DESC, 1, DATA, payload_len, data_flags, 2)
        _write_desc(vm, DESC, 2, STATUS, 1, VIRTQ_DESC_F_WRITE, 0)
        _submit_one(vm, AVAIL, 0)
        vm.set(8, BLK_BASE + VIRTIO_REG_QUEUE_NOTIFY, 0)

    def test_virtio_block_writes_to_persistent_host_image_and_reads_back(self):
        with tempfile.TemporaryDirectory() as td:
            image_path = os.path.join(td, "rootfs.img")
            data = b"persistent-rootfs"
            backend = HostBlockImage(image_path, size=4096)
            vm, apic = self._attach_block(backend)
            vm.memory[DATA : DATA + len(data)] = data

            self.assertEqual(vm.get(8, BLK_BASE + VIRTIO_REG_MAGIC), VIRTIO_MAGIC)
            self.assertEqual(vm.get(8, BLK_BASE + VIRTIO_REG_DEVICE_ID), VIRTIO_DEVICE_BLOCK)
            self._submit_block_req(vm, VIRTIO_BLK_T_OUT, 1, len(data))

            self.assertEqual(vm.memory[STATUS], VIRTIO_BLK_S_OK)
            self.assertEqual(_used_idx(vm), 1)
            self.assertTrue(apic.pending())
            entry = apic.take_deliverable(True, 0xFF, lambda _int_n: 0x10)
            self.assertEqual(entry[1], SVM_IRQ_VIRTIO_BLK0)
            self.assertEqual(vm.get(8, BLK_BASE + VIRTIO_REG_INTERRUPT_STATUS), 1)
            with open(image_path, "rb") as f:
                f.seek(VIRTIO_BLK_SECTOR_SIZE)
                self.assertEqual(f.read(len(data)), data)

            vm2, _apic2 = self._attach_block(HostBlockImage(image_path, size=4096))
            self._submit_block_req(vm2, VIRTIO_BLK_T_IN, 1, len(data))
            self.assertEqual(vm2.memory[STATUS], VIRTIO_BLK_S_OK)
            self.assertEqual(bytes(vm2.memory[DATA : DATA + len(data)]), data)


class VirtioNetTests(unittest.TestCase):
    def _attach_net(self, backend):
        apic = AdvProgIntCtl()
        ic = MmioInterruptController()
        net = VirtioNetDevice(backend, irq_controller=ic, irq=SVM_IRQ_VIRTIO_NET0)
        bus = MmioBus()
        bus.add_region(IC_BASE, 0x1000, ic, "ic")
        bus.add_region(NET_BASE, 0x1000, net, "net")
        vm = _vm()
        vm.attach_mmio_bus(bus)
        vm.apic = apic
        vm.set(8, IC_BASE + IC_REG_ENABLE, 1 << SVM_IRQ_VIRTIO_NET0)
        return vm, apic, net

    def test_virtio_net_tx_and_rx_use_host_backend(self):
        backend = InMemoryNetBackend([b"incoming"])
        vm, apic, _net = self._attach_net(backend)

        self.assertEqual(vm.get(8, NET_BASE + VIRTIO_REG_DEVICE_ID), VIRTIO_DEVICE_NET)

        tx_desc = 0x1800
        tx_avail = 0x1A00
        tx_used = 0x1B00
        tx_packet = b"\0" * VIRTIO_NET_HDR_SIZE + b"hello"
        vm.memory[DATA : DATA + len(tx_packet)] = tx_packet
        _setup_queue(vm, NET_BASE, 1, desc=tx_desc, avail=tx_avail, used=tx_used)
        _write_desc(vm, tx_desc, 0, DATA, len(tx_packet), 0, 0)
        _submit_one(vm, tx_avail, 0)
        vm.set(8, NET_BASE + VIRTIO_REG_QUEUE_NOTIFY, 1)
        self.assertEqual(backend.tx_packets, [b"hello"])
        self.assertEqual(_used_idx(vm, tx_used), 1)

        rx_desc = 0x1C00
        rx_avail = 0x1E00
        rx_used = 0x1F00
        rx_buf = 0x2000
        _setup_queue(vm, NET_BASE, 0, desc=rx_desc, avail=rx_avail, used=rx_used)
        _write_desc(vm, rx_desc, 0, rx_buf, 64, VIRTQ_DESC_F_WRITE, 0)
        _submit_one(vm, rx_avail, 0)
        vm.set(8, NET_BASE + VIRTIO_REG_QUEUE_NOTIFY, 0)

        self.assertEqual(bytes(vm.memory[rx_buf : rx_buf + len(b"incoming")]), b"incoming")
        self.assertEqual(_used_idx(vm, rx_used), 1)
        self.assertTrue(apic.pending())
        irqs = []
        while apic.pending():
            irqs.append(apic.take_deliverable(True, 0xFF, lambda _int_n: 0x10)[1])
        self.assertIn(SVM_IRQ_VIRTIO_NET0, irqs)


if __name__ == "__main__":
    unittest.main()
