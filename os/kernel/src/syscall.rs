use core::{
    cell::UnsafeCell,
    mem::size_of,
    sync::atomic::{AtomicBool, AtomicU64, Ordering},
};

const KERNEL_CODE_SELECTOR: u16 = 0x08;
const SYSCALL_EXIT: u64 = 1;
const SYSCALL_READ_BOOT_JSON: u64 = 2;
const EXIT_NOT_CALLED: u64 = u64::MAX;
const EXIT_SYSCALL_RETURN: u64 = u64::MAX;
const EXPECTED_USER_READ_PROTECTION_FAULT: u64 = 0b101;

struct StaticGdt(UnsafeCell<[u64; 7]>);
struct StaticTss(UnsafeCell<[u8; 104]>);

unsafe impl Sync for StaticGdt {}
unsafe impl Sync for StaticTss {}

#[repr(C, packed)]
struct DescriptorTablePointer {
    limit: u16,
    base: u64,
}

static GDT: StaticGdt = StaticGdt(UnsafeCell::new([0; 7]));
static TSS: StaticTss = StaticTss(UnsafeCell::new([0; 104]));
static EXIT_CODE: AtomicU64 = AtomicU64::new(EXIT_NOT_CALLED);
static EXPECTED_PAGE_FAULT_ADDRESS: AtomicU64 = AtomicU64::new(0);
static OBSERVED_PAGE_FAULT_ADDRESS: AtomicU64 = AtomicU64::new(0);
static OBSERVED_PAGE_FAULT_ERROR: AtomicU64 = AtomicU64::new(0);
static INITIALIZED: AtomicBool = AtomicBool::new(false);

#[unsafe(no_mangle)]
static mut USER_TEST_RESUME_RSP: usize = 0;

core::arch::global_asm!(
    ".global load_kernel_gdt",
    "load_kernel_gdt:",
    "lgdt [rdi]",
    "push 0x08",
    "lea rax, [rip + 2f]",
    "push rax",
    "retfq",
    "2:",
    "mov ax, 0x10",
    "mov ds, ax",
    "mov es, ax",
    "mov ss, ax",
    "mov ax, 0x28",
    "ltr ax",
    "ret",
);

core::arch::global_asm!(
    ".global enter_user_mode",
    "enter_user_mode:",
    "push rbx",
    "mov rbx, rsp",
    "mov [rip + USER_TEST_RESUME_RSP], rsp",
    "mov rax, 0x1b",
    "push rax",
    "push rsi",
    "pushfq",
    "pop rax",
    "and rax, 0xffffffffffffcfff",
    "or rax, 0x202",
    "push rax",
    "mov rax, 0x23",
    "push rax",
    "push rdi",
    "iretq",
);

core::arch::global_asm!(
    ".global syscall_interrupt_stub",
    "syscall_interrupt_stub:",
    "cld",
    "push r12",
    "mov r12, rsp",
    "mov rsi, rdi",
    "mov rdi, rax",
    "and rsp, -16",
    "call syscall_dispatch",
    "cmp rax, -1",
    "je user_test_resume",
    "mov rsp, r12",
    "pop r12",
    "iretq",
    ".global user_test_resume",
    "user_test_resume:",
    "mov rsp, [rip + USER_TEST_RESUME_RSP]",
    "pop rbx",
    "sti",
    "ret",
);

unsafe extern "C" {
    fn load_kernel_gdt(pointer: *const DescriptorTablePointer);
    fn enter_user_mode(entry: usize, user_stack: usize);
    fn syscall_interrupt_stub();
    fn user_test_resume() -> !;
}

pub(crate) fn initialize(kernel_stack_top: usize) -> Result<(), &'static str> {
    if INITIALIZED.load(Ordering::Acquire) {
        return Err("user syscall support was initialized more than once");
    }
    if kernel_stack_top == 0 || kernel_stack_top % 16 != 0 {
        return Err("ring-0 syscall stack must be nonzero and 16-byte aligned");
    }

    let tss = unsafe { &mut *TSS.0.get() };
    unsafe {
        core::ptr::write_bytes(tss.as_mut_ptr(), 0, tss.len());
        core::ptr::write_unaligned(tss.as_mut_ptr().add(4) as *mut u64, kernel_stack_top as u64);
        core::ptr::write_unaligned(tss.as_mut_ptr().add(102) as *mut u16, 104);
    }

    let gdt = unsafe { &mut *GDT.0.get() };
    gdt[0] = 0;
    gdt[1] = 0x00af_9a00_0000_ffff;
    gdt[2] = 0x00cf_9200_0000_ffff;
    gdt[3] = 0x00cf_f200_0000_ffff;
    gdt[4] = 0x00af_fa00_0000_ffff;
    let tss_base = tss.as_ptr() as u64;
    let tss_limit = (size_of::<[u8; 104]>() - 1) as u64;
    gdt[5] = (tss_limit & 0xffff)
        | ((tss_base & 0x00ff_ffff) << 16)
        | (0x89 << 40)
        | (((tss_limit >> 16) & 0x0f) << 48)
        | (((tss_base >> 24) & 0xff) << 56);
    gdt[6] = tss_base >> 32;

    let pointer = DescriptorTablePointer {
        limit: (size_of::<[u64; 7]>() - 1) as u16,
        base: gdt.as_ptr() as u64,
    };
    unsafe {
        load_kernel_gdt(&pointer);
    }
    super::timer::install_syscall_gate(
        syscall_interrupt_stub as *const () as usize,
        KERNEL_CODE_SELECTOR,
    );
    INITIALIZED.store(true, Ordering::Release);
    Ok(())
}

pub(crate) fn verify_user_exit(entry: usize, user_stack: usize) -> Result<u64, &'static str> {
    if !INITIALIZED.load(Ordering::Acquire) {
        return Err("user syscall support has not been initialized");
    }
    if entry == 0 || user_stack == 0 || user_stack % 16 != 0 {
        return Err("user program entry and stack must be valid and aligned");
    }

    EXIT_CODE.store(EXIT_NOT_CALLED, Ordering::Relaxed);
    unsafe {
        enter_user_mode(entry, user_stack);
    }
    let exit_code = EXIT_CODE.load(Ordering::Acquire);
    if exit_code == EXIT_NOT_CALLED {
        return Err("user test returned without invoking the exit syscall");
    }
    Ok(exit_code)
}

pub(crate) fn verify_user_page_fault(
    entry: usize,
    user_stack: usize,
    protected_address: u64,
) -> Result<(), &'static str> {
    if !INITIALIZED.load(Ordering::Acquire) {
        return Err("user syscall support has not been initialized");
    }
    if entry == 0 || user_stack == 0 || user_stack % 16 != 0 || protected_address == 0 {
        return Err("user fault test entry, stack, and protected address must be valid");
    }

    OBSERVED_PAGE_FAULT_ADDRESS.store(0, Ordering::Relaxed);
    OBSERVED_PAGE_FAULT_ERROR.store(0, Ordering::Relaxed);
    EXPECTED_PAGE_FAULT_ADDRESS.store(protected_address, Ordering::Release);
    unsafe {
        enter_user_mode(entry, user_stack);
    }
    EXPECTED_PAGE_FAULT_ADDRESS.store(0, Ordering::Release);

    if OBSERVED_PAGE_FAULT_ADDRESS.load(Ordering::Acquire) != protected_address
        || OBSERVED_PAGE_FAULT_ERROR.load(Ordering::Acquire) != EXPECTED_USER_READ_PROTECTION_FAULT
    {
        return Err("ring-3 protected-memory access did not produce the expected page fault");
    }
    Ok(())
}

#[unsafe(no_mangle)]
extern "C" fn syscall_dispatch(number: u64, argument: u64) -> u64 {
    if number == SYSCALL_EXIT {
        EXIT_CODE.store(argument, Ordering::Release);
        return EXIT_SYSCALL_RETURN;
    }
    if number == SYSCALL_READ_BOOT_JSON {
        let mut file = [0; 512];
        let length = match super::storage::read_boot_json(&mut file) {
            Ok(length) => length,
            Err(_) => return u64::MAX - 1,
        };
        if super::address_space::copy_to_user(argument, &file[..length]).is_err() {
            return u64::MAX - 1;
        }
        return length as u64;
    }
    u64::MAX - 1
}

#[unsafe(no_mangle)]
extern "C" fn page_fault_dispatch(error_code: u64, address: u64, code_segment: u64) -> ! {
    let expected_address = EXPECTED_PAGE_FAULT_ADDRESS.load(Ordering::Acquire);
    if expected_address != 0
        && code_segment & 0b11 == 0b11
        && address == expected_address
        && error_code == EXPECTED_USER_READ_PROTECTION_FAULT
    {
        OBSERVED_PAGE_FAULT_ADDRESS.store(address, Ordering::Release);
        OBSERVED_PAGE_FAULT_ERROR.store(error_code, Ordering::Release);
        unsafe {
            user_test_resume();
        }
    }
    super::timer::unexpected_page_fault_handler(error_code, address, code_segment)
}
