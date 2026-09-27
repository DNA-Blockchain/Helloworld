#![no_std]
#![no_main]

use bootloader_api::{BootInfo, entry_point};
use core::fmt::{self, Write};

entry_point!(kernel_main);

struct Serial;

impl Serial {
    fn initialize() {
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

    fn write_byte(byte: u8) {
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

fn kernel_main(_boot_info: &'static mut BootInfo) -> ! {
    Serial::initialize();
    let _ = writeln!(Serial, "Network OS prototype: booted in x86_64 QEMU.");
    let _ = writeln!(
        Serial,
        "PCI scan: looking for class 02 (network controllers)."
    );

    let mut found = 0;
    for bus in 0..=255 {
        for device in 0..32 {
            let vendor = pci_read(bus, device, 0, 0x00) as u16;
            if vendor == 0xffff {
                continue;
            }

            let header = (pci_read(bus, device, 0, 0x0c) >> 16) as u8;
            let function_count = if header & 0x80 != 0 { 8 } else { 1 };
            for function in 0..function_count {
                let id = pci_read(bus, device, function, 0x00);
                let vendor = id as u16;
                if vendor == 0xffff {
                    continue;
                }
                let device_id = (id >> 16) as u16;
                let class_info = pci_read(bus, device, function, 0x08);
                let class = (class_info >> 24) as u8;
                let subclass = (class_info >> 16) as u8;
                let programming_interface = (class_info >> 8) as u8;
                if class == 0x02 {
                    found += 1;
                    let _ = writeln!(
                        Serial,
                        "network controller: {:04x}:{:04x} class={:02x}:{:02x}:{:02x} at {:02x}:{:02x}.{}",
                        vendor,
                        device_id,
                        class,
                        subclass,
                        programming_interface,
                        bus,
                        device,
                        function,
                    );
                }
            }
        }
    }

    if found == 0 {
        let _ = writeln!(Serial, "No PCI network controller found.");
    } else {
        let _ = writeln!(Serial, "Detected {found} PCI network controller(s).");
    }
    let _ = writeln!(
        Serial,
        "Device discovery only: no NIC driver, DHCP, TCP/IP, or internet access yet."
    );
    exit_qemu(0x10)
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

fn exit_qemu(code: u32) -> ! {
    unsafe { port_write_u32(0xf4, code) };
    loop {
        core::hint::spin_loop();
    }
}

unsafe fn port_write(port: u16, value: u8) {
    unsafe {
        core::arch::asm!(
            "out dx, al",
            in("dx") port,
            in("al") value,
            options(nomem, nostack, preserves_flags)
        );
    }
}

unsafe fn port_read(port: u16) -> u8 {
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

unsafe fn port_write_u32(port: u16, value: u32) {
    unsafe {
        core::arch::asm!(
            "out dx, eax",
            in("dx") port,
            in("eax") value,
            options(nomem, nostack, preserves_flags)
        );
    }
}

unsafe fn port_read_u32(port: u16) -> u32 {
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
fn panic(_info: &core::panic::PanicInfo) -> ! {
    Serial::initialize();
    let _ = writeln!(Serial, "KERNEL PANIC");
    exit_qemu(0x11)
}
