#![no_std]
#![no_main]

extern crate alloc;

mod address_space;
mod block_device;
mod e1000;
mod elf;
mod filesystem;
mod heap;
mod memory;
mod network;
mod scheduler;
mod storage;
mod syscall;
mod task;
mod task_bundle;
mod telemetry;
mod timer;
mod virtual_memory;

use bootloader_api::{BootInfo, BootloaderConfig, config::Mapping, entry_point};
use core::fmt::{self, Write};

pub static BOOTLOADER_CONFIG: BootloaderConfig = {
    let mut config = BootloaderConfig::new_default();
    config.mappings.kernel_base = Mapping::FixedAddress(0xffff_8000_0000_0000);
    config.mappings.physical_memory = Some(Mapping::Dynamic);
    config
};

entry_point!(kernel_main, config = &BOOTLOADER_CONFIG);

pub(crate) struct Serial;

impl Serial {
    pub(crate) fn initialize() {
        unsafe {
            port_write(0x3f9, 0x00);
            port_write(0x3fb, 0x80);
            port_write(0x3f8, 0x03);
            port_write(0x3f9, 0x00);
            port_write(0x3fb, 0x03);
            port_write(0x3fa, 0xc7);
            port_write(0x3fc, 0x0b);
        }
    }

    pub(crate) fn write_byte(byte: u8) {
        unsafe {
            while port_read(0x3fd) & 0x20 == 0 {
                core::hint::spin_loop();
            }
            port_write(0x3f8, byte);
        }
    }
}

impl Write for Serial {
    fn write_str(&mut self, text: &str) -> fmt::Result {
        for byte in text.bytes() {
            if byte == b'\n' {
                Self::write_byte(b'\r');
            }
            Self::write_byte(byte);
        }
        Ok(())
    }
}

fn kernel_main(boot_info: &'static mut BootInfo) -> ! {
    Serial::initialize();
    let _ = writeln!(Serial, "Network OS prototype: booted in x86_64 QEMU.");
    timer::initialize();
    timer::wait_for_ticks(10);
    let _ = writeln!(
        Serial,
        "PIT timer verified: {} ticks at {} ms.",
        timer::ticks(),
        timer::milliseconds()
    );
    match storage::verify_persistent_record() {
        Ok(generation) => {
            let _ = writeln!(
                Serial,
                "Block device verified: 4096 sectors; persistent test record generation {}.",
                generation
            );
        }
        Err(error) => {
            let _ = writeln!(Serial, "Storage initialization failed: {error}");
            exit_qemu(0x11);
        }
    }
    match storage::verify_filesystem_record() {
        Ok(()) => {
            let _ = writeln!(
                Serial,
                "Filesystem verified: NOSFS v2 persisted BOOT.JSON and a 24-KiB RUNTIME.TEST file."
            );
        }
        Err(error) => {
            let _ = writeln!(Serial, "Filesystem initialization failed: {error}");
            exit_qemu(0x11);
        }
    }
    let mut telemetry = telemetry::Telemetry::new();
    match telemetry.initialize(timer::ticks()) {
        Ok(()) => {
            let _ = writeln!(
                Serial,
                "Guest checkpoints active: boot {}, log generation {}, checkpoint generation {}.",
                telemetry.boot_count(),
                telemetry.log_generation(),
                telemetry.checkpoint_generation()
            );
        }
        Err(error) => {
            let _ = writeln!(
                Serial,
                "Guest analytics disabled; kernel continues without telemetry: {error}"
            );
        }
    }
    match network::run(boot_info, &mut telemetry) {
        Ok(()) => exit_qemu(0x10),
        Err(error) => {
            if let Err(telemetry_error) = telemetry.record(
                telemetry::STAGE_BOOT_FAILED,
                telemetry::STATUS_FAILED,
                timer::ticks(),
            ) {
                let _ = writeln!(
                    Serial,
                    "Could not persist guest failure checkpoint: {telemetry_error}"
                );
            }
            let _ = writeln!(Serial, "Network initialization failed: {error}");
            exit_qemu(0x11)
        }
    }
}

pub(crate) fn exit_qemu(code: u32) -> ! {
    unsafe { port_write_u32(0xf4, code) };
    loop {
        core::hint::spin_loop();
    }
}

pub(crate) unsafe fn port_write(port: u16, value: u8) {
    unsafe {
        core::arch::asm!(
            "out dx, al",
            in("dx") port,
            in("al") value,
            options(nomem, nostack, preserves_flags)
        );
    }
}

pub(crate) unsafe fn port_read(port: u16) -> u8 {
    let value: u8;
    unsafe {
        core::arch::asm!(
            "in al, dx",
            in("dx") port,
            out("al") value,
            options(nomem, nostack, preserves_flags)
        );
    }
    value
}

pub(crate) unsafe fn port_write_u16(port: u16, value: u16) {
    unsafe {
        core::arch::asm!(
            "out dx, ax",
            in("dx") port,
            in("ax") value,
            options(nomem, nostack, preserves_flags)
        );
    }
}

pub(crate) unsafe fn port_read_u16(port: u16) -> u16 {
    let value: u16;
    unsafe {
        core::arch::asm!(
            "in ax, dx",
            in("dx") port,
            out("ax") value,
            options(nomem, nostack, preserves_flags)
        );
    }
    value
}

pub(crate) unsafe fn port_write_u32(port: u16, value: u32) {
    unsafe {
        core::arch::asm!(
            "out dx, eax",
            in("dx") port,
            in("eax") value,
            options(nomem, nostack, preserves_flags)
        );
    }
}

pub(crate) unsafe fn port_read_u32(port: u16) -> u32 {
    let value: u32;
    unsafe {
        core::arch::asm!(
            "in eax, dx",
            in("dx") port,
            out("eax") value,
            options(nomem, nostack, preserves_flags)
        );
    }
    value
}

#[panic_handler]
fn panic(info: &core::panic::PanicInfo) -> ! {
    Serial::initialize();
    let _ = writeln!(Serial, "KERNEL PANIC: {info}");
    exit_qemu(0x11)
}
/*
 * Copyright (c) 2026 Chase Allen Ringquist. All rights reserved.
 *
 * This file is part of an operating system, software, and network Work
 * conceived and authored by Chase Allen Ringquist. It is the intellectual and
 * digital property of the Author, except where an open-source license
 * accompanying this file expressly grants other rights.
 *
 * Do not remove or alter this notice or any record of origin.
 * See NOTICE.md in the project root for full terms.
 * See LICENSE for the applicable license.
 *
 * Contact:  ringquistchase@gmail.com  |  (918) 845-0940
 *            Bixby, OK, United States
 */
