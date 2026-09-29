/*
 * ============================================================================
 *  SPDX-License-Identifier: UPL-1.0
 *
 *  Copyright (c) 2026 Chase Allen Ringquist
 *
 *  This file is part of an operating system, software, and network Work
 *  conceived and authored by Chase Allen Ringquist. The Author retains
 *  copyright and authorship. Use of this file is licensed as follows.
 *
 *  ----------------------------------------------------------------------------
 *  The Universal Permissive License (UPL), Version 1.0
 *
 *  Subject to the condition set forth below, permission is hereby granted to
 *  any person obtaining a copy of this software, associated documentation
 *  and/or data (collectively the "Software"), free of charge and under any
 *  and all copyright rights in the Software, and any and all patent rights
 *  owned or freely licensable by each licensor hereunder covering either
 *  (i) the unmodified Software as contributed to or provided by such
 *  licensor, or (ii) the Larger Works (as defined below), to deal in both
 *
 *  (a) the Software, and
 *
 *  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
 *  if one is included with the Software (each a "Larger Work" to which the
 *  Software is contributed by such licensors),
 *
 *  without restriction, including without limitation the rights to copy,
 *  create derivative works of, display, perform, and distribute the Software
 *  and make, use, sell, offer for sale, import, export, have made, and have
 *  sold the Software and the Larger Work(s), and to sublicense the foregoing
 *  rights on either these or other terms.
 *
 *  This license is subject to the following condition:
 *
 *  The above copyright notice and either this complete permission notice or
 *  at a minimum a reference to the UPL must be included in all copies or
 *  substantial portions of the Software.
 *
 *  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 *  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 *  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 *  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 *  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 *  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 *  DEALINGS IN THE SOFTWARE.
 *  ----------------------------------------------------------------------------
 *
 *  Do not remove or alter this notice or any record of origin.
 *  See NOTICE.md in the project root for authorship and ownership terms.
 *
 *  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
 *            Bixby, OK, United States
 * ============================================================================
 */

use crate::{Serial, port_read_u32, port_write_u32};
use bootloader_api::{BootInfo, info::MemoryRegionKind};
use core::{
    fmt::Write,
    mem::size_of,
    ptr::{copy_nonoverlapping, read_volatile, write_bytes, write_volatile},
    sync::atomic::{Ordering, compiler_fence},
};
use smoltcp::phy::{Device, DeviceCapabilities, Medium, RxToken, TxToken};
use smoltcp::time::Instant;

const VENDOR_INTEL: u16 = 0x8086;
const DEVICE_82540EM: u16 = 0x100e;
const RX_COUNT: usize = 8;
const TX_COUNT: usize = 8;
const BUFFER_SIZE: usize = 2048;
const RX_DESCRIPTOR_OFFSET: usize = 0;
const TX_DESCRIPTOR_OFFSET: usize = RX_COUNT * size_of::<RxDescriptor>();
const RX_BUFFER_OFFSET: usize = TX_DESCRIPTOR_OFFSET + TX_COUNT * size_of::<TxDescriptor>();
const TX_BUFFER_OFFSET: usize = RX_BUFFER_OFFSET + RX_COUNT * BUFFER_SIZE;
const DMA_POOL_SIZE: usize = TX_BUFFER_OFFSET + TX_COUNT * BUFFER_SIZE;
const PAGE_SIZE: u64 = 4096;
const MIN_DMA_PHYS_ADDR: u64 = 0x10_0000;
const RXD_STAT_DD: u8 = 1;
const TXD_STAT_DD: u8 = 1;

const REG_CTRL: u32 = 0x0000;
const REG_IMC: u32 = 0x00d8;
const REG_RCTL: u32 = 0x0100;
const REG_TCTL: u32 = 0x0400;
const REG_TIPG: u32 = 0x0410;
const REG_RDBAL: u32 = 0x2800;
const REG_RDBAH: u32 = 0x2804;
const REG_RDLEN: u32 = 0x2808;
const REG_RDH: u32 = 0x2810;
const REG_RDT: u32 = 0x2818;
const REG_TDBAL: u32 = 0x3800;
const REG_TDBAH: u32 = 0x3804;
const REG_TDLEN: u32 = 0x3808;
const REG_TDH: u32 = 0x3810;
const REG_TDT: u32 = 0x3818;
const REG_RAL: u32 = 0x5400;
const REG_RAH: u32 = 0x5404;

#[repr(C)]
#[derive(Clone, Copy)]
struct RxDescriptor {
    address: u64,
    length: u16,
    checksum: u16,
    status: u8,
    errors: u8,
    special: u16,
}

impl RxDescriptor {
    const EMPTY: Self = Self {
        address: 0,
        length: 0,
        checksum: 0,
        status: 0,
        errors: 0,
        special: 0,
    };
}

#[repr(C)]
#[derive(Clone, Copy)]
struct TxDescriptor {
    address: u64,
    length: u16,
    checksum_offset: u8,
    command: u8,
    status: u8,
    checksum_start: u8,
    special: u16,
}

impl TxDescriptor {
    const EMPTY: Self = Self {
        address: 0,
        length: 0,
        checksum_offset: 0,
        command: 0,
        status: TXD_STAT_DD,
        checksum_start: 0,
        special: 0,
    };
}

pub(crate) struct E1000 {
    mmio: *mut u32,
    mac: [u8; 6],
    rx_descriptors: *mut RxDescriptor,
    tx_descriptors: *mut TxDescriptor,
    rx_buffers: *mut u8,
    tx_buffers: *mut u8,
    rx_index: usize,
    tx_index: usize,
    tx_failed: bool,
}

impl E1000 {
    pub(crate) fn initialize(boot_info: &mut BootInfo) -> Result<Self, &'static str> {
        let (bus, device, function) =
            find_qemu_e1000().ok_or("QEMU Intel 82540EM (8086:100e) was not found on PCI")?;
        let _ = writeln!(
            Serial,
            "network controller: 8086:100e at {:02x}:{:02x}.{}",
            bus, device, function
        );

        let command = pci_read(bus, device, function, 0x04) as u16 | 0x0006;
        pci_write_u16(bus, device, function, 0x04, command);
        let bar_low = pci_read(bus, device, function, 0x10);
        let bar_type = (bar_low >> 1) & 0x3;
        if bar_low & 1 != 0 || (bar_type != 0 && bar_type != 2) {
            return Err("E1000 BAR0 has an unsupported register-region type");
        }
        let mut bar = u64::from(bar_low & !0x0f);
        if bar_type == 2 {
            bar |= u64::from(pci_read(bus, device, function, 0x14)) << 32;
        }
        if bar == 0 {
            return Err("E1000 BAR0 is unassigned");
        }

        let physical_memory_offset = boot_info
            .physical_memory_offset
            .into_option()
            .ok_or("bootloader did not map physical memory for E1000 MMIO")?;
        let mmio_virtual = physical_memory_offset
            .checked_add(bar)
            .ok_or("E1000 MMIO virtual address overflow")?;
        if mmio_virtual > usize::MAX as u64 {
            return Err("E1000 MMIO address does not fit the kernel pointer width");
        }
        let mmio = mmio_virtual as *mut u32;

        let dma_base = allocate_dma_pool(boot_info)?;
        let dma_offset = boot_info
            .physical_memory_offset
            .into_option()
            .ok_or("bootloader did not map physical memory for E1000 DMA")?;
        let dma_virtual = dma_offset
            .checked_add(dma_base)
            .ok_or("E1000 DMA virtual address overflow")?;
        if dma_virtual > usize::MAX as u64 {
            return Err("E1000 DMA mapping does not fit the kernel pointer width");
        }
        let dma_virtual = dma_virtual as *mut u8;
        let rx_descriptors =
            unsafe { dma_virtual.add(RX_DESCRIPTOR_OFFSET).cast::<RxDescriptor>() };
        let tx_descriptors =
            unsafe { dma_virtual.add(TX_DESCRIPTOR_OFFSET).cast::<TxDescriptor>() };
        let rx_buffers = unsafe { dma_virtual.add(RX_BUFFER_OFFSET) };
        let tx_buffers = unsafe { dma_virtual.add(TX_BUFFER_OFFSET) };
        if dma_base % 16 != 0 || (dma_base + TX_DESCRIPTOR_OFFSET as u64) % 16 != 0 {
            return Err("E1000 DMA descriptor rings are not 16-byte aligned");
        }
        unsafe {
            write_bytes(dma_virtual, 0, DMA_POOL_SIZE);
            for index in 0..RX_COUNT {
                write_volatile(
                    rx_descriptors.add(index),
                    RxDescriptor {
                        address: dma_base + RX_BUFFER_OFFSET as u64 + (index * BUFFER_SIZE) as u64,
                        ..RxDescriptor::EMPTY
                    },
                );
            }
            for index in 0..TX_COUNT {
                write_volatile(
                    tx_descriptors.add(index),
                    TxDescriptor {
                        address: dma_base + TX_BUFFER_OFFSET as u64 + (index * BUFFER_SIZE) as u64,
                        ..TxDescriptor::EMPTY
                    },
                );
            }
        }
        let rx_desc = dma_base + RX_DESCRIPTOR_OFFSET as u64;
        let tx_desc = dma_base + TX_DESCRIPTOR_OFFSET as u64;
        if dma_base + DMA_POOL_SIZE as u64 > u64::from(u32::MAX) {
            return Err("E1000 DMA pool is above the 4-GiB DMA limit");
        }

        let mut nic = Self {
            mmio,
            mac: [0; 6],
            rx_descriptors,
            tx_descriptors,
            rx_buffers,
            tx_buffers,
            rx_index: 0,
            tx_index: 0,
            tx_failed: false,
        };
        nic.write_reg(REG_IMC, u32::MAX);
        nic.write_reg(REG_CTRL, nic.read_reg(REG_CTRL) | (1 << 26));
        let mut reset_cleared = false;
        for _ in 0..1_000_000 {
            if nic.read_reg(REG_CTRL) & (1 << 26) == 0 {
                reset_cleared = true;
                break;
            }
            core::hint::spin_loop();
        }
        if !reset_cleared {
            return Err("E1000 reset did not complete");
        }
        nic.write_reg(REG_IMC, u32::MAX);

        let low = nic.read_reg(REG_RAL);
        let high = nic.read_reg(REG_RAH);
        nic.mac = [
            low as u8,
            (low >> 8) as u8,
            (low >> 16) as u8,
            (low >> 24) as u8,
            high as u8,
            (high >> 8) as u8,
        ];
        if nic.mac == [0; 6] || nic.mac[0] & 1 != 0 {
            return Err("E1000 returned an invalid unicast MAC address");
        }

        compiler_fence(Ordering::Release);
        nic.write_reg(REG_RDBAL, rx_desc as u32);
        nic.write_reg(REG_RDBAH, (rx_desc >> 32) as u32);
        nic.write_reg(REG_RDLEN, (RX_COUNT * size_of::<RxDescriptor>()) as u32);
        nic.write_reg(REG_RDH, 0);
        nic.write_reg(REG_RDT, (RX_COUNT - 1) as u32);

        nic.write_reg(REG_TDBAL, tx_desc as u32);
        nic.write_reg(REG_TDBAH, (tx_desc >> 32) as u32);
        nic.write_reg(REG_TDLEN, (TX_COUNT * size_of::<TxDescriptor>()) as u32);
        nic.write_reg(REG_TDH, 0);
        nic.write_reg(REG_TDT, 0);
        nic.write_reg(REG_TIPG, 0x0060_200a);
        nic.write_reg(REG_TCTL, (1 << 1) | (1 << 3) | (0x0f << 4) | (0x40 << 12));
        nic.write_reg(REG_RCTL, (1 << 1) | (1 << 15) | (1 << 26));
        nic.write_reg(REG_CTRL, nic.read_reg(REG_CTRL) | (1 << 6));

        let _ = writeln!(
            Serial,
            "E1000 initialized: MAC {:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}",
            nic.mac[0], nic.mac[1], nic.mac[2], nic.mac[3], nic.mac[4], nic.mac[5]
        );
        Ok(nic)
    }

    pub(crate) fn mac(&self) -> [u8; 6] {
        self.mac
    }

    pub(crate) fn take_tx_error(&mut self) -> bool {
        core::mem::replace(&mut self.tx_failed, false)
    }

    pub(crate) fn report_status(&self) {
        let _ = writeln!(
            Serial,
            "E1000 status: link={:08x} RCTL={:08x} RDH={} RDT={} TDH={} TDT={}",
            self.read_reg(0x0008),
            self.read_reg(REG_RCTL),
            self.read_reg(REG_RDH),
            self.read_reg(REG_RDT),
            self.read_reg(REG_TDH),
            self.read_reg(REG_TDT)
        );
        unsafe {
            let status = read_volatile(core::ptr::addr_of!((*self.rx_descriptors).status));
            let length = read_volatile(core::ptr::addr_of!((*self.rx_descriptors).length));
            let _ = writeln!(
                Serial,
                "E1000 RX descriptor 0: status={:02x} length={}",
                status, length
            );
        }
    }

    fn read_reg(&self, offset: u32) -> u32 {
        unsafe { read_volatile(self.mmio.add((offset / 4) as usize)) }
    }

    fn write_reg(&mut self, offset: u32, value: u32) {
        unsafe { write_volatile(self.mmio.add((offset / 4) as usize), value) }
    }

    fn receive_frame(&mut self, output: &mut [u8]) -> Option<usize> {
        unsafe {
            let descriptor = self.rx_descriptors.add(self.rx_index);
            let status = read_volatile(core::ptr::addr_of!((*descriptor).status));
            if status & RXD_STAT_DD == 0 {
                return None;
            }
            compiler_fence(Ordering::Acquire);
            let length = usize::from(read_volatile(core::ptr::addr_of!((*descriptor).length)));
            let errors = read_volatile(core::ptr::addr_of!((*descriptor).errors));
            let buffer = self.rx_buffers.add(self.rx_index * BUFFER_SIZE);
            let copied = if errors == 0 && length <= output.len() && length <= BUFFER_SIZE {
                copy_nonoverlapping(buffer, output.as_mut_ptr(), length);
                Some(length)
            } else {
                None
            };

            write_volatile(core::ptr::addr_of_mut!((*descriptor).length), 0);
            write_volatile(core::ptr::addr_of_mut!((*descriptor).status), 0);
            compiler_fence(Ordering::Release);
            self.write_reg(REG_RDT, self.rx_index as u32);
            self.rx_index = (self.rx_index + 1) % RX_COUNT;
            copied
        }
    }

    fn transmit_frame(&mut self, frame: &[u8]) -> bool {
        if frame.len() > BUFFER_SIZE {
            return false;
        }

        let index = self.tx_index;
        unsafe {
            let descriptor = self.tx_descriptors.add(index);
            let mut available = false;
            for _ in 0..1_000_000 {
                if read_volatile(core::ptr::addr_of!((*descriptor).status)) & TXD_STAT_DD != 0 {
                    available = true;
                    break;
                }
                core::hint::spin_loop();
            }
            if !available {
                return false;
            }

            let buffer = self.tx_buffers.add(index * BUFFER_SIZE);
            copy_nonoverlapping(frame.as_ptr(), buffer, frame.len());
            let wire_length = frame.len().max(60);
            if wire_length > frame.len() {
                core::ptr::write_bytes(buffer.add(frame.len()), 0, wire_length - frame.len());
            }

            write_volatile(
                core::ptr::addr_of_mut!((*descriptor).length),
                wire_length as u16,
            );
            write_volatile(core::ptr::addr_of_mut!((*descriptor).command), 0x0b);
            write_volatile(core::ptr::addr_of_mut!((*descriptor).status), 0);
            compiler_fence(Ordering::Release);
            self.write_reg(REG_TDT, ((index + 1) % TX_COUNT) as u32);
        }

        self.tx_index = (index + 1) % TX_COUNT;
        true
    }
}

impl Device for E1000 {
    type RxToken<'a>
        = E1000RxToken
    where
        Self: 'a;
    type TxToken<'a>
        = E1000TxToken<'a>
    where
        Self: 'a;

    fn receive(&mut self, _timestamp: Instant) -> Option<(Self::RxToken<'_>, Self::TxToken<'_>)> {
        let mut frame = [0; BUFFER_SIZE];
        let length = self.receive_frame(&mut frame)?;
        Some((
            E1000RxToken { frame, length },
            E1000TxToken { device: self },
        ))
    }

    fn transmit(&mut self, _timestamp: Instant) -> Option<Self::TxToken<'_>> {
        Some(E1000TxToken { device: self })
    }

    fn capabilities(&self) -> DeviceCapabilities {
        let mut capabilities = DeviceCapabilities::default();
        capabilities.medium = Medium::Ethernet;
        capabilities.max_transmission_unit = 1500;
        capabilities
    }
}

pub(crate) struct E1000RxToken {
    frame: [u8; BUFFER_SIZE],
    length: usize,
}

impl RxToken for E1000RxToken {
    fn consume<R, F>(self, f: F) -> R
    where
        F: FnOnce(&[u8]) -> R,
    {
        f(&self.frame[..self.length])
    }
}

pub(crate) struct E1000TxToken<'a> {
    device: &'a mut E1000,
}

impl TxToken for E1000TxToken<'_> {
    fn consume<R, F>(self, length: usize, f: F) -> R
    where
        F: FnOnce(&mut [u8]) -> R,
    {
        let mut frame = [0; BUFFER_SIZE];
        let requested_length = length.min(BUFFER_SIZE);
        let result = f(&mut frame[..requested_length]);
        if length > BUFFER_SIZE || !self.device.transmit_frame(&frame[..requested_length]) {
            self.device.tx_failed = true;
        }
        result
    }
}

fn allocate_dma_pool(boot_info: &mut BootInfo) -> Result<u64, &'static str> {
    let size = (DMA_POOL_SIZE as u64)
        .checked_add(PAGE_SIZE - 1)
        .ok_or("E1000 DMA pool size overflow")?
        & !(PAGE_SIZE - 1);
    for region in boot_info.memory_regions.iter_mut() {
        if region.kind != MemoryRegionKind::Usable {
            continue;
        }
        let start = region
            .start
            .max(MIN_DMA_PHYS_ADDR)
            .checked_add(PAGE_SIZE - 1)
            .ok_or("usable memory region address overflow")?
            & !(PAGE_SIZE - 1);
        let end = start
            .checked_add(size)
            .ok_or("E1000 DMA pool address overflow")?;
        if end <= region.end && end <= u64::from(u32::MAX) {
            region.start = end;
            return Ok(start);
        }
    }
    Err("no contiguous usable low memory is available for the E1000 DMA pool")
}

fn find_qemu_e1000() -> Option<(u16, u8, u8)> {
    for bus in 0..=255 {
        for device in 0..32 {
            let header = pci_read(bus, device, 0, 0x0c) as u8;
            let function_count = if header & 0x80 != 0 { 8 } else { 1 };
            for function in 0..function_count {
                let id = pci_read(bus, device, function, 0x00);
                if id as u16 == VENDOR_INTEL && (id >> 16) as u16 == DEVICE_82540EM {
                    return Some((bus, device, function));
                }
            }
        }
    }
    None
}

fn pci_read(bus: u16, device: u8, function: u8, offset: u8) -> u32 {
    let address = (1 << 31)
        | (u32::from(bus) << 16)
        | (u32::from(device) << 11)
        | (u32::from(function) << 8)
        | (u32::from(offset) & 0xfc);
    unsafe {
        port_write_u32(0xcf8, address);
        port_read_u32(0xcfc)
    }
}

fn pci_write_u16(bus: u16, device: u8, function: u8, offset: u8, value: u16) {
    let address = (1 << 31)
        | (u32::from(bus) << 16)
        | (u32::from(device) << 11)
        | (u32::from(function) << 8)
        | (u32::from(offset) & 0xfc);
    unsafe {
        port_write_u32(0xcf8, address);
        core::arch::asm!(
            "out dx, ax",
            in("dx") (0xcfc + u16::from(offset & 2)),
            in("ax") value,
            options(nomem, nostack, preserves_flags)
        );
    }
}
