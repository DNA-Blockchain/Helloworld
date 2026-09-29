use alloc::vec::Vec;
use core::{
    cell::UnsafeCell,
    mem::size_of,
    sync::atomic::{AtomicBool, AtomicU64, Ordering},
};

const KERNEL_CODE_SELECTOR: u16 = 0x08;
const SYSCALL_EXIT: u64 = 1;
const SYSCALL_READ_FILE: u64 = 2;
const SYSCALL_WRITE: u64 = 3;
const SYSCALL_DNS_LOOKUP: u64 = 4;
const SYSCALL_TCP_CONNECT: u64 = 5;
const SYSCALL_TCP_SEND: u64 = 6;
const SYSCALL_TCP_RECEIVE: u64 = 7;
const SYSCALL_TCP_CLOSE: u64 = 8;
const SYSCALL_UDP_BIND: u64 = 9;
const SYSCALL_UDP_SEND: u64 = 10;
const SYSCALL_UDP_RECEIVE: u64 = 11;
const SYSCALL_UDP_CLOSE: u64 = 12;
const SYSCALL_WRITE_FILE: u64 = 13;
const SYSCALL_TASK_ENTRYPOINT: u64 = 14;
const SYSCALL_ERROR: u64 = u64::MAX - 1;
const MAX_FILENAME_BYTES: usize = 16;
const MAX_WRITE_BYTES: usize = 4096;
const WRITE_CHUNK_BYTES: usize = 128;
const MAX_DNS_NAME_BYTES: usize = 253;
const MAX_SOCKET_IO_BYTES: usize = 1024;
const EXIT_NOT_CALLED: u64 = u64::MAX;
const EXIT_SYSCALL_RETURN: u64 = u64::MAX;
const MAX_TASK_FILES: usize = 8;
const MAX_TASK_OUTPUT_BYTES: usize = 16 * 1024;

struct StaticGdt(UnsafeCell<[u64; 7]>);
struct StaticTss(UnsafeCell<[u8; 104]>);

unsafe impl Sync for StaticGdt {}
unsafe impl Sync for StaticTss {}

struct FileList {
    names: [[u8; MAX_FILENAME_BYTES]; MAX_TASK_FILES],
    lengths: [usize; MAX_TASK_FILES],
    count: usize,
}

impl FileList {
    const EMPTY: Self = Self {
        names: [[0; MAX_FILENAME_BYTES]; MAX_TASK_FILES],
        lengths: [0; MAX_TASK_FILES],
        count: 0,
    };

    fn set(&mut self, names: &[&str]) -> Result<(), &'static str> {
        if names.len() > MAX_TASK_FILES {
            return Err("workflow task declares too many files");
        }
        self.count = 0;
        for name in names {
            let bytes = name.as_bytes();
            if bytes.is_empty() || bytes.len() >= MAX_FILENAME_BYTES {
                return Err("workflow task file name is outside its bounds");
            }
            self.names[self.count] = [0; MAX_FILENAME_BYTES];
            self.names[self.count][..bytes.len()].copy_from_slice(bytes);
            self.lengths[self.count] = bytes.len();
            self.count += 1;
        }
        Ok(())
    }

    fn position(&self, name: &str) -> Option<usize> {
        (0..self.count).find(|index| &self.names[*index][..self.lengths[*index]] == name.as_bytes())
    }
}

/// What the running workflow task may touch. Only consulted while
/// TASK_POLICY_ACTIVE; `written` records which outputs were written.
struct TaskPolicy {
    readable: FileList,
    writable: FileList,
    entrypoint: FileList,
    written: u8,
}

pub(crate) struct TaskRunResult {
    pub(crate) exit_code: u64,
    pub(crate) outputs_written: bool,
}

struct StaticTaskPolicy(UnsafeCell<TaskPolicy>);

unsafe impl Sync for StaticTaskPolicy {}

#[repr(C, packed)]
struct DescriptorTablePointer {
    limit: u16,
    base: u64,
}

static GDT: StaticGdt = StaticGdt(UnsafeCell::new([0; 7]));
static TSS: StaticTss = StaticTss(UnsafeCell::new([0; 104]));
static EXIT_CODE: AtomicU64 = AtomicU64::new(EXIT_NOT_CALLED);
static USER_MODE_ACTIVE: AtomicBool = AtomicBool::new(false);
static USER_PAGE_FAULTED: AtomicBool = AtomicBool::new(false);
static EXPECTED_PAGE_FAULT_ADDRESS: AtomicU64 = AtomicU64::new(0);
static EXPECTED_PAGE_FAULT_ERROR: AtomicU64 = AtomicU64::new(0);
static OBSERVED_PAGE_FAULT_ADDRESS: AtomicU64 = AtomicU64::new(0);
static OBSERVED_PAGE_FAULT_ERROR: AtomicU64 = AtomicU64::new(0);
static USER_EXCEPTION_VECTOR: AtomicU64 = AtomicU64::new(0);
static INITIALIZED: AtomicBool = AtomicBool::new(false);
static TASK_POLICY: StaticTaskPolicy = StaticTaskPolicy(UnsafeCell::new(TaskPolicy {
    readable: FileList::EMPTY,
    writable: FileList::EMPTY,
    entrypoint: FileList::EMPTY,
    written: 0,
}));
static TASK_POLICY_ACTIVE: AtomicBool = AtomicBool::new(false);
static TASK_DEADLINE_MS: AtomicU64 = AtomicU64::new(0);
static USER_TIMED_OUT: AtomicBool = AtomicBool::new(false);

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
    "mov rcx, rdx",
    "mov rdx, rsi",
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
    fn invalid_opcode_interrupt_stub();
    fn user_test_resume() -> !;
}

pub(crate) fn invalid_opcode_stub_address() -> usize {
    invalid_opcode_interrupt_stub as *const () as usize
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

pub(crate) fn enable_user_memory_protections() -> Result<(), &'static str> {
    let extended_max = core::arch::x86_64::__cpuid(0x8000_0000).eax;
    if extended_max < 0x8000_0001 {
        return Err("CPU does not report extended features required for user NX protection");
    }
    let features = core::arch::x86_64::__cpuid(0x8000_0001);
    if features.edx & (1 << 20) == 0 {
        return Err("CPU does not support NX page protections required for user execution");
    }

    let efer: u64;
    unsafe {
        let eax: u32;
        let edx: u32;
        core::arch::asm!(
            "rdmsr",
            in("ecx") 0xc000_0080u32,
            out("eax") eax,
            out("edx") edx,
            options(nostack, preserves_flags)
        );
        efer = (u64::from(edx) << 32) | u64::from(eax);
        let updated = efer | (1 << 11);
        core::arch::asm!(
            "wrmsr",
            in("ecx") 0xc000_0080u32,
            in("eax") updated as u32,
            in("edx") (updated >> 32) as u32,
            options(nostack, preserves_flags)
        );

        let cr0: u64;
        core::arch::asm!("mov {}, cr0", out(reg) cr0, options(nostack, preserves_flags));
        core::arch::asm!(
            "mov cr0, {}",
            in(reg) cr0 | (1 << 16),
            options(nostack, preserves_flags)
        );
    }
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
    USER_PAGE_FAULTED.store(false, Ordering::Relaxed);
    USER_EXCEPTION_VECTOR.store(0, Ordering::Relaxed);
    USER_TIMED_OUT.store(false, Ordering::Relaxed);
    USER_MODE_ACTIVE.store(true, Ordering::Release);
    unsafe {
        enter_user_mode(entry, user_stack);
    }
    USER_MODE_ACTIVE.store(false, Ordering::Release);
    if USER_TIMED_OUT.swap(false, Ordering::AcqRel) {
        return Err("ring-3 task exceeded its runtime limit");
    }
    if USER_PAGE_FAULTED.swap(false, Ordering::AcqRel) {
        return Err("ring-3 process terminated after an unhandled user page fault");
    }
    let exception_vector = USER_EXCEPTION_VECTOR.swap(0, Ordering::AcqRel);
    if exception_vector != 0 {
        return Err("ring-3 process terminated after an unhandled user exception");
    }
    let exit_code = EXIT_CODE.load(Ordering::Acquire);
    if exit_code == EXIT_NOT_CALLED {
        return Err("user test returned without invoking the exit syscall");
    }
    Ok(exit_code)
}

/// Runs a workflow task in ring 3 under a restricted policy: the read-file
/// syscall only accepts `readable_files`, the write-file syscall only
/// `writable_files`, every network syscall fails, and the timer interrupt
/// stops the task once `runtime_seconds` have elapsed.
pub(crate) fn run_task_with_policy(
    entry: usize,
    user_stack: usize,
    readable_files: &[&str],
    writable_files: &[&str],
    entrypoint: &str,
    runtime_seconds: u64,
) -> Result<TaskRunResult, &'static str> {
    if TASK_POLICY_ACTIVE.load(Ordering::Acquire) {
        return Err("a workflow task policy is already active");
    }
    if runtime_seconds == 0 {
        return Err("workflow task runtime limit must be positive");
    }
    let policy = unsafe { &mut *TASK_POLICY.0.get() };
    policy.readable.set(readable_files)?;
    policy.writable.set(writable_files)?;
    policy.entrypoint.set(&[entrypoint])?;
    policy.written = 0;
    let deadline =
        super::timer::milliseconds().saturating_add(runtime_seconds.saturating_mul(1_000));
    TASK_DEADLINE_MS.store(deadline, Ordering::Release);
    TASK_POLICY_ACTIVE.store(true, Ordering::Release);
    let result = verify_user_exit(entry, user_stack);
    TASK_POLICY_ACTIVE.store(false, Ordering::Release);
    TASK_DEADLINE_MS.store(0, Ordering::Release);
    let all_outputs = ((1u16 << policy.writable.count) - 1) as u8;
    Ok(TaskRunResult {
        exit_code: result?,
        outputs_written: policy.written == all_outputs,
    })
}

/// Called on every timer tick. Abandons a ring-3 workflow task that is past
/// its deadline, returning to the harness exactly like a user page fault.
pub(crate) fn user_timer_tick(code_segment: u64) {
    let deadline = TASK_DEADLINE_MS.load(Ordering::Acquire);
    if code_segment & 0b11 != 0b11 || deadline == 0 || super::timer::milliseconds() < deadline {
        return;
    }
    if USER_MODE_ACTIVE.swap(false, Ordering::AcqRel) {
        USER_TIMED_OUT.store(true, Ordering::Release);
        unsafe {
            user_test_resume();
        }
    }
}

fn task_may_read(filename: &str) -> bool {
    if !TASK_POLICY_ACTIVE.load(Ordering::Acquire) {
        return true;
    }
    let policy = unsafe { &*TASK_POLICY.0.get() };
    policy.readable.position(filename).is_some()
}

fn copy_user_filename(pointer: u64, buffer: &mut [u8; MAX_FILENAME_BYTES]) -> Option<&str> {
    let mut length = None;
    for index in 0..MAX_FILENAME_BYTES {
        let address = pointer.checked_add(index as u64)?;
        super::address_space::copy_from_user(address, core::slice::from_mut(&mut buffer[index]))
            .ok()?;
        if buffer[index] == 0 {
            length = Some(index);
            break;
        }
    }
    let name = core::str::from_utf8(&buffer[..length?]).ok()?;
    (!name.is_empty()).then_some(name)
}

pub(crate) fn verify_user_exception(
    entry: usize,
    user_stack: usize,
    expected_vector: u64,
) -> Result<(), &'static str> {
    if !INITIALIZED.load(Ordering::Acquire) {
        return Err("user syscall support has not been initialized");
    }
    if entry == 0 || user_stack == 0 || user_stack % 16 != 0 || expected_vector != 6 {
        return Err("user exception test requires valid addresses and the supported vector");
    }

    USER_EXCEPTION_VECTOR.store(0, Ordering::Relaxed);
    USER_MODE_ACTIVE.store(true, Ordering::Release);
    unsafe {
        enter_user_mode(entry, user_stack);
    }
    USER_MODE_ACTIVE.store(false, Ordering::Release);

    if USER_EXCEPTION_VECTOR.swap(0, Ordering::AcqRel) != expected_vector {
        return Err("ring-3 invalid-opcode exception did not return to the harness");
    }
    Ok(())
}

pub(crate) fn verify_user_page_fault(
    entry: usize,
    user_stack: usize,
    protected_address: u64,
    expected_error: u64,
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
    EXPECTED_PAGE_FAULT_ERROR.store(expected_error, Ordering::Release);
    USER_PAGE_FAULTED.store(false, Ordering::Relaxed);
    USER_MODE_ACTIVE.store(true, Ordering::Release);
    unsafe {
        enter_user_mode(entry, user_stack);
    }
    USER_MODE_ACTIVE.store(false, Ordering::Release);
    EXPECTED_PAGE_FAULT_ADDRESS.store(0, Ordering::Release);
    EXPECTED_PAGE_FAULT_ERROR.store(0, Ordering::Release);

    if OBSERVED_PAGE_FAULT_ADDRESS.load(Ordering::Acquire) != protected_address
        || OBSERVED_PAGE_FAULT_ERROR.load(Ordering::Acquire) != expected_error
    {
        return Err("ring-3 protected-memory access did not produce the expected page fault");
    }
    Ok(())
}

#[unsafe(no_mangle)]
extern "C" fn user_exception_dispatch(vector: u64, code_segment: u64) -> ! {
    if vector == 6 && code_segment & 0b11 == 0b11 && USER_MODE_ACTIVE.swap(false, Ordering::AcqRel)
    {
        USER_EXCEPTION_VECTOR.store(vector, Ordering::Release);
        unsafe {
            user_test_resume();
        }
    }
    super::timer::unexpected_interrupt_handler()
}

#[unsafe(no_mangle)]
extern "C" fn syscall_dispatch(number: u64, argument1: u64, argument2: u64, argument3: u64) -> u64 {
    if number == SYSCALL_EXIT {
        EXIT_CODE.store(argument1, Ordering::Release);
        return EXIT_SYSCALL_RETURN;
    }
    if TASK_POLICY_ACTIVE.load(Ordering::Acquire)
        && (SYSCALL_DNS_LOOKUP..=SYSCALL_UDP_CLOSE).contains(&number)
    {
        return SYSCALL_ERROR;
    }
    if number == SYSCALL_READ_FILE {
        let Ok(capacity) = usize::try_from(argument3) else {
            return SYSCALL_ERROR;
        };
        if capacity == 0 || capacity > super::filesystem::MAX_FILE_SIZE {
            return SYSCALL_ERROR;
        }
        if super::address_space::validate_user_buffer(argument2, capacity, true).is_err() {
            return SYSCALL_ERROR;
        }
        let mut filename_buffer = [0; MAX_FILENAME_BYTES];
        let Some(filename) = copy_user_filename(argument1, &mut filename_buffer) else {
            return SYSCALL_ERROR;
        };
        if !task_may_read(filename) {
            return SYSCALL_ERROR;
        }
        let output = unsafe { core::slice::from_raw_parts_mut(argument2 as *mut u8, capacity) };
        return super::storage::read_named_file(filename, output)
            .map(|length| length as u64)
            .unwrap_or(SYSCALL_ERROR);
    }
    if number == SYSCALL_TASK_ENTRYPOINT {
        if !TASK_POLICY_ACTIVE.load(Ordering::Acquire) {
            return SYSCALL_ERROR;
        }
        let policy = unsafe { &*TASK_POLICY.0.get() };
        let name = &policy.entrypoint.names[0][..policy.entrypoint.lengths[0]];
        let Ok(capacity) = usize::try_from(argument2) else {
            return SYSCALL_ERROR;
        };
        if policy.entrypoint.count != 1
            || name.len() > capacity
            || super::address_space::validate_user_buffer(argument1, name.len(), true).is_err()
            || super::address_space::copy_to_user(argument1, name).is_err()
        {
            return SYSCALL_ERROR;
        }
        return name.len() as u64;
    }
    if number == SYSCALL_WRITE_FILE {
        if !TASK_POLICY_ACTIVE.load(Ordering::Acquire) {
            return SYSCALL_ERROR;
        }
        let Ok(length) = usize::try_from(argument3) else {
            return SYSCALL_ERROR;
        };
        if length == 0
            || length > MAX_TASK_OUTPUT_BYTES
            || super::address_space::validate_user_buffer(argument2, length, false).is_err()
        {
            return SYSCALL_ERROR;
        }
        let mut filename_buffer = [0; MAX_FILENAME_BYTES];
        let Some(filename) = copy_user_filename(argument1, &mut filename_buffer) else {
            return SYSCALL_ERROR;
        };
        let policy = unsafe { &mut *TASK_POLICY.0.get() };
        let Some(index) = policy.writable.position(filename) else {
            return SYSCALL_ERROR;
        };
        let mut contents = Vec::new();
        if contents.try_reserve_exact(length).is_err() {
            return SYSCALL_ERROR;
        }
        contents.resize(length, 0);
        if super::address_space::copy_from_user(argument2, &mut contents).is_err()
            || super::storage::write_named_file(filename, &contents).is_err()
        {
            return SYSCALL_ERROR;
        }
        policy.written |= 1 << index;
        return length as u64;
    }
    if number == SYSCALL_WRITE {
        let Ok(length) = usize::try_from(argument2) else {
            return SYSCALL_ERROR;
        };
        if length == 0
            || length > MAX_WRITE_BYTES
            || super::address_space::validate_user_buffer(argument1, length, false).is_err()
        {
            return SYSCALL_ERROR;
        }

        let mut chunk = [0; WRITE_CHUNK_BYTES];
        let mut offset = 0;
        while offset < length {
            let chunk_length = (length - offset).min(chunk.len());
            let Some(address) = argument1.checked_add(offset as u64) else {
                return SYSCALL_ERROR;
            };
            if super::address_space::copy_from_user(address, &mut chunk[..chunk_length]).is_err() {
                return SYSCALL_ERROR;
            }
            for byte in &chunk[..chunk_length] {
                if *byte == b'\n' {
                    crate::Serial::write_byte(b'\r');
                }
                crate::Serial::write_byte(*byte);
            }
            offset += chunk_length;
        }
        return length as u64;
    }
    if number == SYSCALL_DNS_LOOKUP {
        let Ok(name_length) = usize::try_from(argument2) else {
            return SYSCALL_ERROR;
        };
        if name_length == 0
            || name_length > MAX_DNS_NAME_BYTES
            || super::address_space::validate_user_buffer(argument1, name_length, false).is_err()
            || super::address_space::validate_user_buffer(argument3, 4, true).is_err()
        {
            return SYSCALL_ERROR;
        }
        let mut name = [0; MAX_DNS_NAME_BYTES];
        if super::address_space::copy_from_user(argument1, &mut name[..name_length]).is_err() {
            return SYSCALL_ERROR;
        }
        let Ok(name) = core::str::from_utf8(&name[..name_length]) else {
            return SYSCALL_ERROR;
        };
        let Ok(address) = super::network::resolve_user_dns(name) else {
            return SYSCALL_ERROR;
        };
        return super::address_space::copy_to_user(argument3, &address)
            .map(|()| 4)
            .unwrap_or(SYSCALL_ERROR);
    }
    if number == SYSCALL_TCP_CONNECT {
        let Ok(port) = u16::try_from(argument2) else {
            return SYSCALL_ERROR;
        };
        let Ok(address) = u32::try_from(argument1) else {
            return SYSCALL_ERROR;
        };
        return super::network::user_tcp_connect(address.to_be_bytes(), port)
            .map(|()| 0)
            .unwrap_or(SYSCALL_ERROR);
    }
    if number == SYSCALL_TCP_SEND {
        let Ok(length) = usize::try_from(argument2) else {
            return SYSCALL_ERROR;
        };
        if length == 0
            || length > MAX_SOCKET_IO_BYTES
            || super::address_space::validate_user_buffer(argument1, length, false).is_err()
        {
            return SYSCALL_ERROR;
        }
        let mut data = [0; MAX_SOCKET_IO_BYTES];
        if super::address_space::copy_from_user(argument1, &mut data[..length]).is_err() {
            return SYSCALL_ERROR;
        }
        return super::network::user_tcp_send(&data[..length])
            .map(|sent| sent as u64)
            .unwrap_or(SYSCALL_ERROR);
    }
    if number == SYSCALL_TCP_RECEIVE {
        let Ok(capacity) = usize::try_from(argument2) else {
            return SYSCALL_ERROR;
        };
        if capacity == 0
            || capacity > MAX_SOCKET_IO_BYTES
            || super::address_space::validate_user_buffer(argument1, capacity, true).is_err()
        {
            return SYSCALL_ERROR;
        }
        let mut data = [0; MAX_SOCKET_IO_BYTES];
        let Ok(length) = super::network::user_tcp_receive(&mut data[..capacity]) else {
            return SYSCALL_ERROR;
        };
        return super::address_space::copy_to_user(argument1, &data[..length])
            .map(|()| length as u64)
            .unwrap_or(SYSCALL_ERROR);
    }
    if number == SYSCALL_TCP_CLOSE {
        return super::network::user_tcp_close()
            .map(|()| 0)
            .unwrap_or(SYSCALL_ERROR);
    }
    if number == SYSCALL_UDP_BIND {
        let Ok(port) = u16::try_from(argument1) else {
            return SYSCALL_ERROR;
        };
        return super::network::user_udp_bind(port)
            .map(|()| 0)
            .unwrap_or(SYSCALL_ERROR);
    }
    if number == SYSCALL_UDP_SEND {
        let Ok(length) = usize::try_from(argument2) else {
            return SYSCALL_ERROR;
        };
        if length == 0
            || length > MAX_SOCKET_IO_BYTES
            || argument3 >> 48 != 0
            || super::address_space::validate_user_buffer(argument1, length, false).is_err()
        {
            return SYSCALL_ERROR;
        }
        let mut data = [0; MAX_SOCKET_IO_BYTES];
        if super::address_space::copy_from_user(argument1, &mut data[..length]).is_err() {
            return SYSCALL_ERROR;
        }
        let address = (argument3 as u32).to_be_bytes();
        let port = (argument3 >> 32) as u16;
        return super::network::user_udp_send(&data[..length], address, port)
            .map(|sent| sent as u64)
            .unwrap_or(SYSCALL_ERROR);
    }
    if number == SYSCALL_UDP_RECEIVE {
        let Ok(capacity) = usize::try_from(argument2) else {
            return SYSCALL_ERROR;
        };
        if capacity == 0
            || capacity > MAX_SOCKET_IO_BYTES
            || super::address_space::validate_user_buffer(argument1, capacity, true).is_err()
            || super::address_space::validate_user_buffer(argument3, 6, true).is_err()
        {
            return SYSCALL_ERROR;
        }
        let mut data = [0; MAX_SOCKET_IO_BYTES];
        let Ok((length, address, port)) = super::network::user_udp_receive(&mut data[..capacity])
        else {
            return SYSCALL_ERROR;
        };
        if super::address_space::copy_to_user(argument1, &data[..length]).is_err() {
            return SYSCALL_ERROR;
        }
        let mut endpoint = [0; 6];
        endpoint[..4].copy_from_slice(&address);
        endpoint[4..].copy_from_slice(&port.to_be_bytes());
        return super::address_space::copy_to_user(argument3, &endpoint)
            .map(|()| length as u64)
            .unwrap_or(SYSCALL_ERROR);
    }
    if number == SYSCALL_UDP_CLOSE {
        return super::network::user_udp_close()
            .map(|()| 0)
            .unwrap_or(SYSCALL_ERROR);
    }
    SYSCALL_ERROR
}

#[unsafe(no_mangle)]
extern "C" fn page_fault_dispatch(error_code: u64, address: u64, code_segment: u64) -> ! {
    let expected_address = EXPECTED_PAGE_FAULT_ADDRESS.load(Ordering::Acquire);
    let expected_error = EXPECTED_PAGE_FAULT_ERROR.load(Ordering::Acquire);
    if expected_address != 0
        && code_segment & 0b11 == 0b11
        && address == expected_address
        && error_code == expected_error
    {
        OBSERVED_PAGE_FAULT_ADDRESS.store(address, Ordering::Release);
        OBSERVED_PAGE_FAULT_ERROR.store(error_code, Ordering::Release);
        unsafe {
            user_test_resume();
        }
    }
    if code_segment & 0b11 == 0b11 && USER_MODE_ACTIVE.swap(false, Ordering::AcqRel) {
        USER_PAGE_FAULTED.store(true, Ordering::Release);
        unsafe {
            user_test_resume();
        }
    }
    super::timer::unexpected_page_fault_handler(error_code, address, code_segment)
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
