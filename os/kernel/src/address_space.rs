use core::{
    cell::UnsafeCell,
    ptr::{read_volatile, write_volatile},
    sync::atomic::{AtomicBool, AtomicU64, Ordering},
};

const PAGE_SIZE: u64 = 4096;
const ENTRY_PRESENT: u64 = 1;
const ENTRY_WRITABLE: u64 = 1 << 1;
const ENTRY_USER: u64 = 1 << 2;
const ENTRY_HUGE: u64 = 1 << 7;
const ENTRY_NO_EXECUTE: u64 = 1 << 63;
const ENTRY_ADDRESS_MASK: u64 = 0x000f_ffff_ffff_f000;
const USER_PML4_LIMIT: usize = 256;
const USER_TEST_OFFSET: u64 = 0x0040_0000;
const MAX_USER_PAGES: usize = 512;
const KERNEL_SYSCALL_STACK_PAGES: usize = 4;
const PAGE_SIZE_BYTES: usize = PAGE_SIZE as usize;

#[derive(Clone, Copy)]
struct UserPage {
    virtual_address: u64,
    physical_address: u64,
}

impl UserPage {
    const EMPTY: Self = Self {
        virtual_address: 0,
        physical_address: 0,
    };
}

struct PageRecords(UnsafeCell<[[UserPage; MAX_USER_PAGES]; 2]>);

unsafe impl Sync for PageRecords {}

static USER_PAGES: PageRecords =
    PageRecords(UnsafeCell::new([[UserPage::EMPTY; MAX_USER_PAGES]; 2]));
static SPACE_IN_USE: [AtomicBool; 2] = [AtomicBool::new(false), AtomicBool::new(false)];
static PHYSICAL_MEMORY_OFFSET: AtomicU64 = AtomicU64::new(0);
static USER_PML4_INDEX: AtomicU64 = AtomicU64::new(u64::MAX);
static INITIALIZED: AtomicBool = AtomicBool::new(false);

pub(crate) struct AddressSpace {
    root_physical: u64,
    record_index: usize,
}

pub(crate) fn copy_to_user(destination: u64, source: &[u8]) -> Result<(), &'static str> {
    validate_user_range(destination, source.len(), true)?;
    unsafe {
        core::ptr::copy_nonoverlapping(source.as_ptr(), destination as *mut u8, source.len());
    }
    Ok(())
}

pub(crate) fn copy_from_user(source: u64, destination: &mut [u8]) -> Result<(), &'static str> {
    validate_user_range(source, destination.len(), false)?;
    unsafe {
        core::ptr::copy_nonoverlapping(
            source as *const u8,
            destination.as_mut_ptr(),
            destination.len(),
        );
    }
    Ok(())
}

pub(crate) fn validate_user_buffer(
    address: u64,
    length: usize,
    require_write: bool,
) -> Result<(), &'static str> {
    validate_user_range(address, length, require_write)
}

pub(crate) fn zero_user_range(destination: u64, length: usize) -> Result<(), &'static str> {
    if length == 0 {
        return Ok(());
    }
    validate_user_range(destination, length, true)?;
    unsafe {
        core::ptr::write_bytes(destination as *mut u8, 0, length);
    }
    Ok(())
}

fn validate_user_range(
    destination: u64,
    length: usize,
    require_write: bool,
) -> Result<(), &'static str> {
    if length == 0 || destination >= (1 << 47) {
        return Err("user memory range is empty or outside the lower canonical address space");
    }
    let end = destination
        .checked_add(length as u64)
        .ok_or("user memory range overflow")?;
    if end > (1 << 47) {
        return Err("user memory range crosses the lower canonical address-space limit");
    }
    let root = read_cr3() & ENTRY_ADDRESS_MASK;
    let first_page = destination & !(PAGE_SIZE - 1);
    let last_page = (end - 1) & !(PAGE_SIZE - 1);
    let mut page = first_page;
    loop {
        let mut table_physical = root;
        for (level, index) in page_table_indices(page).into_iter().enumerate() {
            let entry = unsafe { read_volatile(table_entry_pointer(table_physical, index)?) };
            if entry & ENTRY_PRESENT == 0 || entry & ENTRY_USER == 0 {
                return Err("user memory range is not fully user-mapped");
            }
            if require_write && entry & ENTRY_WRITABLE == 0 {
                return Err("user memory range is not writable");
            }
            if level < 3 && entry & ENTRY_HUGE != 0 {
                return Err("user memory range uses an unsupported huge-page mapping");
            }
            table_physical = entry & ENTRY_ADDRESS_MASK;
        }
        if page == last_page {
            break;
        }
        page = page
            .checked_add(PAGE_SIZE)
            .ok_or("user memory page range overflow")?;
    }
    Ok(())
}

struct InterruptGuard {
    restore_interrupts: bool,
}

impl Drop for InterruptGuard {
    fn drop(&mut self) {
        if self.restore_interrupts {
            unsafe {
                core::arch::asm!("sti", options(nomem, nostack, preserves_flags));
            }
        }
    }
}

pub(crate) fn initialize(physical_memory_offset: u64) -> Result<(), &'static str> {
    let _guard = disable_interrupts();
    if INITIALIZED.load(Ordering::Relaxed) {
        return Err("address-space manager was initialized more than once");
    }
    super::syscall::enable_user_memory_protections()?;
    if physical_memory_offset % PAGE_SIZE != 0 {
        return Err("physical memory mapping offset is not page-aligned");
    }
    let root = read_cr3() & ENTRY_ADDRESS_MASK;
    let root_table = table_pointer_with_offset(physical_memory_offset, root)?;
    let user_index = (1..USER_PML4_LIMIT)
        .find(|index| unsafe { read_volatile(root_table.add(*index)) == 0 })
        .ok_or("kernel page table has no empty lower-half PML4 slot for user mappings")?;
    PHYSICAL_MEMORY_OFFSET.store(physical_memory_offset, Ordering::Relaxed);
    USER_PML4_INDEX.store(user_index as u64, Ordering::Relaxed);
    INITIALIZED.store(true, Ordering::Release);
    Ok(())
}

pub(crate) fn verify_isolation() -> Result<(), &'static str> {
    if !INITIALIZED.load(Ordering::Acquire) {
        return Err("address-space manager has not been initialized");
    }
    let mut first = create()?;
    let mut second = match create() {
        Ok(space) => space,
        Err(error) => {
            destroy(&mut first)?;
            return Err(error);
        }
    };
    let user_address = user_test_address()?;
    if let Err(error) = map_user_page(&mut first, user_address)
        .and_then(|()| map_user_page(&mut second, user_address))
    {
        destroy(&mut first)?;
        destroy(&mut second)?;
        return Err(error);
    }
    let permissions_result = (|| {
        if !mapping_is_user_accessible(&first, user_address)?
            || !mapping_is_user_accessible(&second, user_address)?
            || !kernel_mapping_is_supervisor(&first)?
        {
            return Err("address-space user/kernel page permissions are incorrect");
        }
        Ok(())
    })();
    if let Err(error) = permissions_result {
        destroy(&mut first)?;
        destroy(&mut second)?;
        return Err(error);
    }

    let kernel_root = read_cr3() & ENTRY_ADDRESS_MASK;
    let verification = (|| {
        for page_index in 1..16 {
            let address = user_address
                .checked_add((page_index as u64) * PAGE_SIZE)
                .ok_or("user mapping stress-test address overflow")?;
            map_user_page(&mut first, address)?;
        }
        activate(&first)?;
        unsafe {
            write_volatile(user_address as *mut u64, 0x4652_4f4d_5f41_0001);
        }
        activate(&second)?;
        unsafe {
            write_volatile(user_address as *mut u64, 0x4652_4f4d_5f42_0002);
        }
        activate(&first)?;
        if unsafe { read_volatile(user_address as *const u64) } != 0x4652_4f4d_5f41_0001 {
            return Err("first address space did not retain its private user mapping");
        }
        let mapped_user_pages = unsafe { &(*USER_PAGES.0.get())[first.record_index] };
        if mapped_user_pages
            .iter()
            .filter(|page| page.physical_address != 0)
            .count()
            != 16
        {
            return Err("address space did not track all mapped user pages");
        }

        activate(&second)?;
        if unsafe { read_volatile(user_address as *const u64) } != 0x4652_4f4d_5f42_0002 {
            return Err("second address space did not retain its private user mapping");
        }
        Ok(())
    })();

    let restore_result = activate_root(kernel_root);
    if let Err(error) = restore_result {
        return Err(error);
    }
    destroy(&mut second)?;
    destroy(&mut first)?;
    verification
}

pub(crate) fn verify_user_syscall() -> Result<u64, &'static str> {
    let user_code = user_test_address()?;
    let user_stack = user_code
        .checked_add(PAGE_SIZE)
        .ok_or("user stack address overflow")?;
    let user_buffer = user_code
        .checked_add(PAGE_SIZE * 2)
        .ok_or("user data buffer address overflow")?;
    let elf_load_base = user_code
        .checked_add(PAGE_SIZE * 3)
        .ok_or("ELF load address overflow")?;
    let process_stack = elf_load_base
        .checked_add(PAGE_SIZE)
        .ok_or("ELF stack address overflow")?;
    let kernel_root = read_cr3() & ENTRY_ADDRESS_MASK;
    let mut kernel_stack_base = None;
    let mut kernel_stack_pages = 0;
    for index in 0..KERNEL_SYSCALL_STACK_PAGES {
        let address = match super::virtual_memory::allocate_page() {
            Ok(address) => address as usize,
            Err(error) => {
                release_kernel_stack(kernel_stack_base, kernel_stack_pages)?;
                return Err(error);
            }
        };
        if let Some(base) = kernel_stack_base {
            if address != base + index * PAGE_SIZE_BYTES {
                super::virtual_memory::deallocate_page(address as u64)?;
                release_kernel_stack(kernel_stack_base, kernel_stack_pages)?;
                return Err("ring-0 syscall stack pages are not virtually contiguous");
            }
        } else {
            kernel_stack_base = Some(address);
        }
        kernel_stack_pages += 1;
    }
    let Some(kernel_stack_base_address) = kernel_stack_base else {
        return Err("ring-0 syscall stack has no pages");
    };
    let kernel_stack_top = kernel_stack_base_address
        .checked_add(KERNEL_SYSCALL_STACK_PAGES * PAGE_SIZE_BYTES)
        .ok_or("ring-0 syscall stack top overflow")?;

    let mut space = match create() {
        Ok(space) => space,
        Err(error) => {
            release_kernel_stack(kernel_stack_base, kernel_stack_pages)?;
            return Err(error);
        }
    };
    if let Err(error) =
        map_user_page(&mut space, user_stack).and_then(|()| map_user_page(&mut space, user_buffer))
    {
        destroy(&mut space)?;
        release_kernel_stack(kernel_stack_base, kernel_stack_pages)?;
        return Err(error);
    }

    if let Err(error) = super::syscall::initialize(kernel_stack_top) {
        release_kernel_stack(kernel_stack_base, kernel_stack_pages)?;
        destroy(&mut space)?;
        return Err(error);
    }

    let result = (|| {
        activate(&space)?;
        map_user_page(&mut space, user_code)?;
        set_user_page_permissions(user_code, true, true)?;
        if !kernel_mapping_is_supervisor(&space)? {
            return Err("ring-3 fault test requires a supervisor-only kernel mapping");
        }

        let code: [u8; 14] = [
            0xb8, 0x01, 0x00, 0x00, 0x00, 0xbf, 0x2a, 0x00, 0x00, 0x00, 0xcd, 0x80, 0x0f, 0x0b,
        ];
        unsafe {
            core::ptr::copy_nonoverlapping(code.as_ptr(), user_code as *mut u8, code.len());
        }
        let user_stack_top = (user_stack + PAGE_SIZE - 16) as usize;
        let exit_code = super::syscall::verify_user_exit(user_code as usize, user_stack_top)?;
        if exit_code != 42 {
            return Err("ring-3 test program returned an unexpected syscall exit value");
        }

        copy_to_user(user_buffer, b"BOOT.JSON\0")?;
        let file_output = user_buffer + 128;
        let file_capacity = PAGE_SIZE_BYTES - 128;
        let mut file_read_code = [0; 49];
        file_read_code[..5].copy_from_slice(&[0xb8, 0x02, 0, 0, 0]);
        file_read_code[5..7].copy_from_slice(&[0x48, 0xbf]);
        file_read_code[15..17].copy_from_slice(&[0x48, 0xbe]);
        file_read_code[25..27].copy_from_slice(&[0x48, 0xba]);
        file_read_code[35..37].copy_from_slice(&[0xcd, 0x80]);
        file_read_code[37..40].copy_from_slice(&[0x48, 0x89, 0xc7]);
        file_read_code[40..45].copy_from_slice(&[0xb8, 0x01, 0, 0, 0]);
        file_read_code[45..47].copy_from_slice(&[0xcd, 0x80]);
        file_read_code[47..49].copy_from_slice(&[0x0f, 0x0b]);
        file_read_code[7..15].copy_from_slice(&user_buffer.to_le_bytes());
        file_read_code[17..25].copy_from_slice(&(file_output as u64).to_le_bytes());
        file_read_code[27..35].copy_from_slice(&(file_capacity as u64).to_le_bytes());
        unsafe {
            core::ptr::copy_nonoverlapping(
                file_read_code.as_ptr(),
                user_code as *mut u8,
                file_read_code.len(),
            );
        }
        let file_length = super::storage::expected_boot_json().len() as u64;
        let read_exit_code = super::syscall::verify_user_exit(user_code as usize, user_stack_top)?;
        if read_exit_code != file_length {
            return Err("ring-3 named-file syscall returned an unexpected file length");
        }
        let user_file =
            unsafe { core::slice::from_raw_parts(file_output as *const u8, file_length as usize) };
        if user_file != super::storage::expected_boot_json() {
            return Err("ring-3 named-file syscall returned unexpected file contents");
        }

        let protected_address = verify_isolation as *const () as u64;
        file_read_code[7..15].copy_from_slice(&user_buffer.to_le_bytes());
        file_read_code[17..25].copy_from_slice(&protected_address.to_le_bytes());
        file_read_code[27..35].copy_from_slice(&(file_capacity as u64).to_le_bytes());
        unsafe {
            core::ptr::copy_nonoverlapping(
                file_read_code.as_ptr(),
                user_code as *mut u8,
                file_read_code.len(),
            );
        }
        if super::syscall::verify_user_exit(user_code as usize, user_stack_top)? != u64::MAX - 1 {
            return Err("ring-3 named-file syscall accepted a supervisor output pointer");
        }
        file_read_code[7..15].copy_from_slice(&protected_address.to_le_bytes());
        file_read_code[17..25].copy_from_slice(&(file_output as u64).to_le_bytes());
        unsafe {
            core::ptr::copy_nonoverlapping(
                file_read_code.as_ptr(),
                user_code as *mut u8,
                file_read_code.len(),
            );
        }
        if super::syscall::verify_user_exit(user_code as usize, user_stack_top)? != u64::MAX - 1 {
            return Err("ring-3 named-file syscall accepted a supervisor filename pointer");
        }

        let mut fault_code = [
            0x48, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0, 0x48, 0x8b, 0x00, 0xb8, 0x2a, 0x00, 0x00, 0x00,
            0xcd, 0x80, 0x0f, 0x0b,
        ];
        fault_code[2..10].copy_from_slice(&protected_address.to_le_bytes());
        unsafe {
            core::ptr::copy_nonoverlapping(
                fault_code.as_ptr(),
                user_code as *mut u8,
                fault_code.len(),
            );
        }
        super::syscall::verify_user_page_fault(
            user_code as usize,
            user_stack_top,
            protected_address,
            0b101,
        )?;

        let mut elf_image = [0; 512];
        let elf_length = super::storage::read_test_elf(&mut elf_image)?;
        let mut malformed_image = elf_image;
        malformed_image[0] = 0;
        let mut process_space = create()?;
        if let Err(error) = map_user_page(&mut process_space, process_stack) {
            destroy(&mut process_space)?;
            return Err(error);
        }
        let process_result = (|| {
            activate(&process_space)?;
            if super::elf::load(
                &mut process_space,
                &malformed_image[..elf_length],
                elf_load_base,
            )
            .is_ok()
            {
                return Err("ELF loader accepted an image with an invalid signature");
            }
            let loaded =
                super::elf::load(&mut process_space, &elf_image[..elf_length], elf_load_base)?;
            if loaded.entry != elf_load_base || loaded.load_bias != elf_load_base {
                return Err("ELF loader returned an unexpected process entry point");
            }
            let process_stack_top = (process_stack + PAGE_SIZE - 16) as usize;
            let process_exit =
                super::syscall::verify_user_exit(loaded.entry as usize, process_stack_top)?;
            if process_exit != 42 {
                return Err("ELF user process exited with an unexpected status");
            }

            let mut nx_fault_code = [0x48, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0, 0xff, 0xe0];
            nx_fault_code[2..10].copy_from_slice(&process_stack.to_le_bytes());
            set_user_page_permissions(loaded.entry, true, true)?;
            copy_to_user(loaded.entry, &nx_fault_code)?;
            set_user_page_permissions(loaded.entry, false, true)?;
            super::syscall::verify_user_page_fault(
                loaded.entry as usize,
                process_stack_top,
                process_stack,
                0b1_0101,
            )?;

            let mut write_fault_code = [0x48, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0, 0xc7, 0x00, 0, 0, 0, 0];
            write_fault_code[2..10].copy_from_slice(&loaded.entry.to_le_bytes());
            set_user_page_permissions(loaded.entry, true, true)?;
            copy_to_user(loaded.entry, &write_fault_code)?;
            set_user_page_permissions(loaded.entry, false, true)?;
            super::syscall::verify_user_page_fault(
                loaded.entry as usize,
                process_stack_top,
                loaded.entry,
                0b111,
            )?;
            Ok(process_exit)
        })();
        let restore_process_root = activate(&space);
        if let Err(error) = restore_process_root {
            return Err(error);
        }
        destroy(&mut process_space)?;
        let process_exit = process_result?;
        if process_exit != 42 {
            return Err("ELF process lifecycle returned an unexpected exit status");
        }
        Ok(exit_code)
    })();

    let restore_result = activate_root(kernel_root);
    if let Err(error) = restore_result {
        return Err(error);
    }
    destroy(&mut space)?;
    release_kernel_stack(kernel_stack_base, kernel_stack_pages)?;
    let exit_code = result?;
    Ok(exit_code)
}

fn user_test_address() -> Result<u64, &'static str> {
    (USER_PML4_INDEX.load(Ordering::Relaxed) << 39)
        .checked_add(USER_TEST_OFFSET)
        .ok_or("user test address overflow")
}

fn release_kernel_stack(base: Option<usize>, pages: usize) -> Result<(), &'static str> {
    let Some(base) = base else {
        return Ok(());
    };
    for index in (0..pages).rev() {
        super::virtual_memory::deallocate_page((base + index * PAGE_SIZE_BYTES) as u64)?;
    }
    Ok(())
}

fn mapping_is_user_accessible(
    space: &AddressSpace,
    virtual_address: u64,
) -> Result<bool, &'static str> {
    let indices = page_table_indices(virtual_address);
    let mut table_physical = space.root_physical;
    for index in indices {
        let entry = unsafe { read_volatile(table_entry_pointer(table_physical, index)?) };
        if entry & ENTRY_PRESENT == 0 || entry & ENTRY_USER == 0 {
            return Ok(false);
        }
        table_physical = entry & ENTRY_ADDRESS_MASK;
    }
    Ok(true)
}

fn kernel_mapping_is_supervisor(space: &AddressSpace) -> Result<bool, &'static str> {
    let stack_pointer: u64;
    unsafe {
        core::arch::asm!(
            "mov {}, rsp",
            out(reg) stack_pointer,
            options(nomem, nostack, preserves_flags)
        );
    }
    for address in [verify_isolation as *const () as u64, stack_pointer] {
        let index = ((address >> 39) & 0x1ff) as usize;
        if index == USER_PML4_INDEX.load(Ordering::Relaxed) as usize {
            return Ok(false);
        }
        let entry = unsafe { read_volatile(table_entry_pointer(space.root_physical, index)?) };
        if entry & ENTRY_PRESENT == 0 || entry & ENTRY_USER != 0 {
            return Ok(false);
        }
    }
    Ok(true)
}

fn create() -> Result<AddressSpace, &'static str> {
    let _guard = disable_interrupts();
    ensure_initialized()?;
    let record_index = SPACE_IN_USE
        .iter()
        .position(|slot| {
            slot.compare_exchange(false, true, Ordering::AcqRel, Ordering::Relaxed)
                .is_ok()
        })
        .ok_or("address-space test slots are exhausted")?;
    let root_physical = match super::memory::allocate(1, 1) {
        Ok(address) => address,
        Err(error) => {
            SPACE_IN_USE[record_index].store(false, Ordering::Release);
            return Err(error);
        }
    };
    if let Err(error) = zero_frame(root_physical) {
        super::memory::deallocate(root_physical, 1)?;
        SPACE_IN_USE[record_index].store(false, Ordering::Release);
        return Err(error);
    }

    let kernel_root = read_cr3() & ENTRY_ADDRESS_MASK;
    let kernel_table = match table_pointer(kernel_root) {
        Ok(table) => table,
        Err(error) => {
            super::memory::deallocate(root_physical, 1)?;
            SPACE_IN_USE[record_index].store(false, Ordering::Release);
            return Err(error);
        }
    };
    let user_table = match table_pointer(root_physical) {
        Ok(table) => table,
        Err(error) => {
            super::memory::deallocate(root_physical, 1)?;
            SPACE_IN_USE[record_index].store(false, Ordering::Release);
            return Err(error);
        }
    };
    let user_index = USER_PML4_INDEX.load(Ordering::Relaxed) as usize;
    for index in 0..512 {
        if index == user_index {
            continue;
        }
        let entry = unsafe { read_volatile(kernel_table.add(index)) };
        if entry & ENTRY_PRESENT != 0 && entry & ENTRY_USER != 0 {
            super::memory::deallocate(root_physical, 1)?;
            SPACE_IN_USE[record_index].store(false, Ordering::Release);
            return Err("kernel page table contains a user-accessible root mapping");
        }
        unsafe {
            write_volatile(user_table.add(index), entry);
        }
    }

    Ok(AddressSpace {
        root_physical,
        record_index,
    })
}

fn map_user_page(space: &mut AddressSpace, virtual_address: u64) -> Result<(), &'static str> {
    let _guard = disable_interrupts();
    if virtual_address % PAGE_SIZE != 0
        || virtual_address >= 0x0000_8000_0000_0000
        || page_table_indices(virtual_address)[0]
            != USER_PML4_INDEX.load(Ordering::Relaxed) as usize
    {
        return Err("user mapping address is unaligned or outside the canonical user range");
    }

    let pages = unsafe { &mut (*USER_PAGES.0.get())[space.record_index] };
    let slot = pages
        .iter()
        .position(|page| page.physical_address == 0)
        .ok_or("address space has reached its user-page limit")?;
    let physical_address = super::memory::allocate(1, 1)?;
    if let Err(error) = zero_frame(physical_address) {
        super::memory::deallocate(physical_address, 1)?;
        return Err(error);
    }

    let indices = page_table_indices(virtual_address);
    let mut table_physical = space.root_physical;
    let mut created_tables = [(0u64, core::ptr::null_mut::<u64>()); 3];
    let mut created_count = 0;
    let result = (|| {
        for index in indices.iter().take(3) {
            let entry_pointer = table_entry_pointer(table_physical, *index)?;
            let mut entry = unsafe { read_volatile(entry_pointer) };
            if entry & ENTRY_PRESENT == 0 {
                let next_table = super::memory::allocate(1, 1)?;
                if let Err(error) = zero_frame(next_table) {
                    super::memory::deallocate(next_table, 1)?;
                    return Err(error);
                }
                entry = next_table | ENTRY_PRESENT | ENTRY_WRITABLE | ENTRY_USER;
                unsafe {
                    write_volatile(entry_pointer, entry);
                }
                created_tables[created_count] = (next_table, entry_pointer);
                created_count += 1;
            } else if entry & ENTRY_HUGE != 0 {
                return Err("user mapping intersects an existing huge-page entry");
            } else if entry & ENTRY_USER == 0 {
                entry |= ENTRY_USER;
                unsafe {
                    write_volatile(entry_pointer, entry);
                }
            }
            table_physical = entry & ENTRY_ADDRESS_MASK;
        }

        let leaf = table_entry_pointer(table_physical, indices[3])?;
        if unsafe { read_volatile(leaf) } & ENTRY_PRESENT != 0 {
            return Err("user virtual address is already mapped");
        }
        unsafe {
            write_volatile(
                leaf,
                physical_address | ENTRY_PRESENT | ENTRY_WRITABLE | ENTRY_USER | ENTRY_NO_EXECUTE,
            );
        }
        Ok(())
    })();

    if let Err(error) = result {
        for (table, parent_entry) in created_tables[..created_count].iter().rev() {
            unsafe {
                write_volatile(*parent_entry, 0);
            }
            super::memory::deallocate(*table, 1)?;
        }
        super::memory::deallocate(physical_address, 1)?;
        return Err(error);
    }

    pages[slot] = UserPage {
        virtual_address,
        physical_address,
    };
    Ok(())
}

pub(crate) fn map_user_page_for_elf(
    space: &mut AddressSpace,
    virtual_address: u64,
) -> Result<(), &'static str> {
    map_user_page(space, virtual_address)
}

pub(crate) fn set_user_page_permissions(
    virtual_address: u64,
    writable: bool,
    executable: bool,
) -> Result<(), &'static str> {
    if virtual_address % PAGE_SIZE != 0 || virtual_address >= (1 << 47) {
        return Err("user permission address must be an aligned lower-half page");
    }
    let root = read_cr3() & ENTRY_ADDRESS_MASK;
    let indices = page_table_indices(virtual_address);
    let mut table_physical = root;
    for (level, index) in indices.iter().enumerate() {
        let entry_pointer = table_entry_pointer(table_physical, *index)?;
        let mut entry = unsafe { read_volatile(entry_pointer) };
        if entry & ENTRY_PRESENT == 0 || entry & ENTRY_USER == 0 {
            return Err("cannot set permissions on a non-user mapping");
        }
        if level == 3 {
            if writable {
                entry |= ENTRY_WRITABLE;
            } else {
                entry &= !ENTRY_WRITABLE;
            }
            if executable {
                entry &= !ENTRY_NO_EXECUTE;
            } else {
                entry |= ENTRY_NO_EXECUTE;
            }
            unsafe {
                write_volatile(entry_pointer, entry);
                core::arch::asm!(
                    "invlpg [{}]",
                    in(reg) virtual_address,
                    options(nostack, preserves_flags)
                );
            }
            return Ok(());
        }
        if entry & ENTRY_HUGE != 0 {
            return Err("cannot set permissions through a huge-page mapping");
        }
        table_physical = entry & ENTRY_ADDRESS_MASK;
    }
    Err("user mapping permission walk did not reach a leaf")
}

pub(crate) fn activate(space: &AddressSpace) -> Result<(), &'static str> {
    activate_root(space.root_physical)
}

fn activate_root(root_physical: u64) -> Result<(), &'static str> {
    if root_physical % PAGE_SIZE != 0 || root_physical > ENTRY_ADDRESS_MASK {
        return Err("address-space root is not a valid aligned page-table frame");
    }
    let _guard = disable_interrupts();
    unsafe {
        core::arch::asm!(
            "mov cr3, {}",
            in(reg) root_physical,
            options(nostack, preserves_flags)
        );
    }
    Ok(())
}

pub(crate) fn destroy(space: &mut AddressSpace) -> Result<(), &'static str> {
    let _guard = disable_interrupts();
    let pages = unsafe { &(*USER_PAGES.0.get())[space.record_index] };
    for page in pages {
        if page.physical_address != 0
            && mapped_frame(space.root_physical, page.virtual_address)? != page.physical_address
        {
            return Err("address-space page record does not match its page-table mapping");
        }
    }
    let user_index = USER_PML4_INDEX.load(Ordering::Relaxed) as usize;
    for index in 0..USER_PML4_LIMIT {
        if index != user_index {
            continue;
        }
        let entry_pointer = table_entry_pointer(space.root_physical, index)?;
        let entry = unsafe { read_volatile(entry_pointer) };
        if entry & ENTRY_PRESENT != 0 {
            if entry & ENTRY_USER == 0 || entry & ENTRY_HUGE != 0 {
                return Err("address-space user root contains an unexpected entry");
            }
            destroy_table(entry & ENTRY_ADDRESS_MASK, 3)?;
            unsafe {
                write_volatile(entry_pointer, 0);
            }
        }
    }
    super::memory::deallocate(space.root_physical, 1)?;
    space.root_physical = 0;
    unsafe {
        (*USER_PAGES.0.get())[space.record_index] = [UserPage::EMPTY; MAX_USER_PAGES];
    }
    SPACE_IN_USE[space.record_index].store(false, Ordering::Release);
    Ok(())
}

fn mapped_frame(root_physical: u64, virtual_address: u64) -> Result<u64, &'static str> {
    let mut table_physical = root_physical;
    for index in page_table_indices(virtual_address) {
        let entry = unsafe { read_volatile(table_entry_pointer(table_physical, index)?) };
        if entry & ENTRY_PRESENT == 0 || entry & ENTRY_USER == 0 {
            return Err("tracked user page is absent or lacks the user permission bit");
        }
        table_physical = entry & ENTRY_ADDRESS_MASK;
    }
    Ok(table_physical)
}

fn destroy_table(table_physical: u64, level: usize) -> Result<(), &'static str> {
    if level == 0 {
        return Err("cannot destroy a page-table leaf as a table");
    }
    let table = table_pointer(table_physical)?;
    for index in 0..512 {
        let entry_pointer = unsafe { table.add(index) };
        let entry = unsafe { read_volatile(entry_pointer) };
        if entry & ENTRY_PRESENT == 0 {
            continue;
        }
        if entry & ENTRY_USER == 0 || entry & ENTRY_HUGE != 0 {
            return Err("address space contains an unexpected user page-table entry");
        }
        let child = entry & ENTRY_ADDRESS_MASK;
        if level == 1 {
            super::memory::deallocate(child, 1)?;
        } else {
            destroy_table(child, level - 1)?;
        }
        unsafe {
            write_volatile(entry_pointer, 0);
        }
    }
    super::memory::deallocate(table_physical, 1)
}

fn page_table_indices(virtual_address: u64) -> [usize; 4] {
    [
        ((virtual_address >> 39) & 0x1ff) as usize,
        ((virtual_address >> 30) & 0x1ff) as usize,
        ((virtual_address >> 21) & 0x1ff) as usize,
        ((virtual_address >> 12) & 0x1ff) as usize,
    ]
}

fn table_pointer(table_physical: u64) -> Result<*mut u64, &'static str> {
    table_pointer_with_offset(
        PHYSICAL_MEMORY_OFFSET.load(Ordering::Relaxed),
        table_physical,
    )
}

fn table_pointer_with_offset(
    physical_memory_offset: u64,
    table_physical: u64,
) -> Result<*mut u64, &'static str> {
    let virtual_address = physical_memory_offset
        .checked_add(table_physical)
        .ok_or("physical page-table address overflow")?;
    usize::try_from(virtual_address)
        .map(|address| address as *mut u64)
        .map_err(|_| "page-table pointer does not fit the kernel pointer width")
}

fn table_entry_pointer(table_physical: u64, index: usize) -> Result<*mut u64, &'static str> {
    let table = table_pointer(table_physical)?;
    Ok(unsafe { table.add(index) })
}

fn zero_frame(physical_address: u64) -> Result<(), &'static str> {
    let virtual_address = PHYSICAL_MEMORY_OFFSET
        .load(Ordering::Relaxed)
        .checked_add(physical_address)
        .ok_or("physical frame address overflow")?;
    let pointer = usize::try_from(virtual_address)
        .map_err(|_| "physical frame pointer does not fit the kernel pointer width")?
        as *mut u8;
    unsafe {
        core::ptr::write_bytes(pointer, 0, PAGE_SIZE as usize);
    }
    Ok(())
}

fn ensure_initialized() -> Result<(), &'static str> {
    if INITIALIZED.load(Ordering::Acquire) {
        Ok(())
    } else {
        Err("address-space manager has not been initialized")
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
        restore_interrupts: flags & (1 << 9) != 0,
    }
}

fn read_cr3() -> u64 {
    let value: u64;
    unsafe {
        core::arch::asm!(
            "mov {}, cr3",
            out(reg) value,
            options(nomem, nostack, preserves_flags)
        );
    }
    value
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
