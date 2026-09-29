use core::{
    cell::UnsafeCell,
    mem::size_of,
    sync::atomic::{AtomicU64, Ordering},
};

use crate::port_write;

const TIMER_VECTOR: usize = 32;
const PIT_INPUT_HZ: u32 = 1_193_182;
const TICK_HZ: u32 = 100;
const TICKS_PER_SECOND: u64 = TICK_HZ as u64;
const PIC1_COMMAND: u16 = 0x20;
const PIC1_DATA: u16 = 0x21;
const PIC2_COMMAND: u16 = 0xa0;
const PIC2_DATA: u16 = 0xa1;
const PIT_CHANNEL_0: u16 = 0x40;
const PIT_COMMAND: u16 = 0x43;

#[repr(C, packed)]
#[derive(Clone, Copy)]
struct IdtEntry {
    offset_low: u16,
    selector: u16,
    ist: u8,
    attributes: u8,
    offset_middle: u16,
    offset_high: u32,
    reserved: u32,
}

impl IdtEntry {
    const MISSING: Self = Self {
        offset_low: 0,
        selector: 0,
        ist: 0,
        attributes: 0,
        offset_middle: 0,
        offset_high: 0,
        reserved: 0,
    };

    fn interrupt_gate(handler: usize, selector: u16) -> Self {
        Self {
            offset_low: handler as u16,
            selector,
            ist: 0,
            attributes: 0x8e,
            offset_middle: (handler >> 16) as u16,
            offset_high: (handler >> 32) as u32,
            reserved: 0,
        }
    }
}

#[repr(C, packed)]
struct Idtr {
    limit: u16,
    base: u64,
}

struct StaticIdt(UnsafeCell<[IdtEntry; 256]>);

// The IDT is initialized once before interrupts are enabled and is read-only afterward.
unsafe impl Sync for StaticIdt {}

static IDT: StaticIdt = StaticIdt(UnsafeCell::new([IdtEntry::MISSING; 256]));
static TICKS: AtomicU64 = AtomicU64::new(0);

#[unsafe(no_mangle)]
extern "C" fn timer_interrupt_handler(code_segment: u64) {
    TICKS.fetch_add(1, Ordering::Relaxed);
    unsafe {
        port_write(PIC1_COMMAND, 0x20);
    }
    crate::syscall::user_timer_tick(code_segment);
}

#[unsafe(no_mangle)]
pub(crate) extern "C" fn unexpected_interrupt_handler() -> ! {
    for byte in b"UNHANDLED EXCEPTION OR INTERRUPT\n" {
        crate::Serial::write_byte(*byte);
    }
    loop {
        unsafe {
            core::arch::asm!("cli", "hlt", options(nomem, nostack));
        }
    }
}

#[unsafe(no_mangle)]
pub(crate) extern "C" fn unexpected_page_fault_handler(
    error_code: u64,
    address: u64,
    code_segment: u64,
) -> ! {
    use core::fmt::Write;

    let _ = writeln!(
        crate::Serial,
        "UNHANDLED PAGE FAULT: address={address:#018x} error={error_code:#x} cs={code_segment:#x}"
    );
    loop {
        unsafe {
            core::arch::asm!("cli", "hlt", options(nomem, nostack));
        }
    }
}

core::arch::global_asm!(
    ".global unexpected_interrupt_stub",
    "unexpected_interrupt_stub:",
    "cli",
    "and rsp, -16",
    "call unexpected_interrupt_handler",
    "ud2",
);

core::arch::global_asm!(
    ".global invalid_opcode_interrupt_stub",
    "invalid_opcode_interrupt_stub:",
    "cli",
    "cld",
    "mov rdi, 6",
    "mov rsi, [rsp + 8]",
    "and rsp, -16",
    "call user_exception_dispatch",
    "ud2",
);

core::arch::global_asm!(
    ".global page_fault_interrupt_stub",
    "page_fault_interrupt_stub:",
    "cli",
    "cld",
    "mov rdi, [rsp]",
    "mov rsi, cr2",
    "mov rdx, [rsp + 16]",
    "and rsp, -16",
    "call page_fault_dispatch",
    "ud2",
);

core::arch::global_asm!(
    ".global timer_interrupt_stub",
    "timer_interrupt_stub:",
    "push rax",
    "push rcx",
    "push rdx",
    "push rbx",
    "push rbp",
    "push rsi",
    "push rdi",
    "push r8",
    "push r9",
    "push r10",
    "push r11",
    "push r12",
    "push r13",
    "push r14",
    "push r15",
    "mov r12, rsp",
    "mov rdi, [r12 + 128]",
    "and rsp, -16",
    "sub rsp, 32",
    "call timer_interrupt_handler",
    "mov rsp, r12",
    "pop r15",
    "pop r14",
    "pop r13",
    "pop r12",
    "pop r11",
    "pop r10",
    "pop r9",
    "pop r8",
    "pop rdi",
    "pop rsi",
    "pop rbp",
    "pop rbx",
    "pop rdx",
    "pop rcx",
    "pop rax",
    "iretq",
);

unsafe extern "C" {
    fn unexpected_interrupt_stub();
    fn page_fault_interrupt_stub();
    fn timer_interrupt_stub();
}

pub(crate) fn initialize() {
    unsafe {
        core::arch::asm!("cli", options(nomem, nostack, preserves_flags));
    }

    let code_selector: u16;
    unsafe {
        core::arch::asm!(
            "mov {0:x}, cs",
            out(reg) code_selector,
            options(nomem, nostack, preserves_flags)
        );
        let unexpected = IdtEntry::interrupt_gate(
            unexpected_interrupt_stub as *const () as usize,
            code_selector,
        );
        (*IDT.0.get()).fill(unexpected);
        (*IDT.0.get())[TIMER_VECTOR] =
            IdtEntry::interrupt_gate(timer_interrupt_stub as *const () as usize, code_selector);
    }

    let idtr = Idtr {
        limit: (size_of::<[IdtEntry; 256]>() - 1) as u16,
        base: IDT.0.get() as u64,
    };
    unsafe {
        core::arch::asm!("lidt [{}]", in(reg) &idtr, options(readonly, nostack, preserves_flags));
    }

    remap_pic();
    configure_pit();

    unsafe {
        core::arch::asm!("sti", options(nomem, nostack, preserves_flags));
    }
}

pub(crate) fn install_syscall_gate(handler: usize, kernel_code_selector: u16) {
    let _guard = disable_interrupts();
    unsafe {
        let idt = &mut *IDT.0.get();
        for entry in idt.iter_mut() {
            entry.selector = kernel_code_selector;
        }
        idt[0x80] = IdtEntry::interrupt_gate(handler, kernel_code_selector);
        idt[0x80].attributes = 0xee;
        idt[6] = IdtEntry::interrupt_gate(
            super::syscall::invalid_opcode_stub_address(),
            kernel_code_selector,
        );
        idt[14] = IdtEntry::interrupt_gate(
            page_fault_interrupt_stub as *const () as usize,
            kernel_code_selector,
        );
    }
}

pub(crate) fn ticks() -> u64 {
    TICKS.load(Ordering::Relaxed)
}

pub(crate) fn milliseconds() -> u64 {
    ticks().saturating_mul(1_000) / TICKS_PER_SECOND
}

pub(crate) fn wait_for_ticks(target: u64) {
    while ticks() < target {
        unsafe {
            core::arch::asm!("hlt", options(nomem, nostack));
        }
    }
}

fn disable_interrupts() -> InterruptGuard {
    let flags: usize;
    unsafe {
        core::arch::asm!(
            "pushfq",
            "pop {flags}",
            "cli",
            flags = out(reg) flags,
            options(nomem)
        );
    }
    InterruptGuard {
        interrupts_were_enabled: flags & (1 << 9) != 0,
    }
}

struct InterruptGuard {
    interrupts_were_enabled: bool,
}

impl Drop for InterruptGuard {
    fn drop(&mut self) {
        if self.interrupts_were_enabled {
            unsafe {
                core::arch::asm!("sti", options(nomem, nostack, preserves_flags));
            }
        }
    }
}

fn remap_pic() {
    unsafe {
        port_write(PIC1_COMMAND, 0x11);
        io_wait();
        port_write(PIC2_COMMAND, 0x11);
        io_wait();
        port_write(PIC1_DATA, 0x20);
        io_wait();
        port_write(PIC2_DATA, 0x28);
        io_wait();
        port_write(PIC1_DATA, 0x04);
        io_wait();
        port_write(PIC2_DATA, 0x02);
        io_wait();
        port_write(PIC1_DATA, 0x01);
        io_wait();
        port_write(PIC2_DATA, 0x01);
        io_wait();
        port_write(PIC1_DATA, 0xfe);
        port_write(PIC2_DATA, 0xff);
    }
}

fn configure_pit() {
    let divisor = (PIT_INPUT_HZ / TICK_HZ) as u16;
    unsafe {
        port_write(PIT_COMMAND, 0x36);
        port_write(PIT_CHANNEL_0, divisor as u8);
        port_write(PIT_CHANNEL_0, (divisor >> 8) as u8);
    }
}

fn io_wait() {
    unsafe {
        port_write(0x80, 0);
    }
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
