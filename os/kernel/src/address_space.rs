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
const ENTRY_ADDRESS_MASK: u64 = 0x000f_ffff_ffff_f000;
const USER_PML4_LIMIT: usize = 256;
const USER_TEST_OFFSET: u64 = 0x0040_0000;
const MAX_USER_PAGES: usize = 4;
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
    if source.is_empty() || destination >= (1 << 47) {
        return Err("user destination range is empty or outside the lower canonical address space");
    }
    let end = destination
        .checked_add(source.len() as u64)
        .ok_or("user destination range overflow")?;
    if end > (1 << 47) {
        return Err("user destination range crosses the lower canonical address-space limit");
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
                return Err("user destination is not mapped with user permissions");
            }
            if entry & ENTRY_WRITABLE == 0 {
                return Err("user destination mapping is not writable");
            }
            if level < 3 && entry & ENTRY_HUGE != 0 {
                return Err("user destination uses an unsupported huge-page mapping");
            }
            table_physical = entry & ENTRY_ADDRESS_MASK;
        }
        if page == last_page {
            break;
        }
        page = page
            .checked_add(PAGE_SIZE)
            .ok_or("user destination page range overflow")?;
    }

    unsafe {
        core::ptr::copy_nonoverlapping(source.as_ptr(), destination as *mut u8, source.len());
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
    if let Err(error) = map_user_page(&mut space, user_code)
        .and_then(|()| map_user_page(&mut space, user_stack))
        .and_then(|()| map_user_page(&mut space, user_buffer))
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

        let mut file_read_code = [
            0xb8, 0x02, 0x00, 0x00, 0x00, 0x48, 0xbf, 0, 0, 0, 0, 0, 0, 0, 0, 0xcd, 0x80, 0x48,
            0x89, 0xc7, 0xb8, 0x01, 0x00, 0x00, 0x00, 0xcd, 0x80, 0x0f, 0x0b,
        ];
        file_read_code[7..15].copy_from_slice(&user_buffer.to_le_bytes());
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
            return Err("ring-3 filesystem syscall returned an unexpected file length");
        }
        let user_file =
            unsafe { core::slice::from_raw_parts(user_buffer as *const u8, file_length as usize) };
        if user_file != super::storage::expected_boot_json() {
            return Err("ring-3 filesystem syscall returned unexpected file contents");
        }

        let protected_address = verify_isolation as *const () as u64;
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
        )?;
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
                physical_address | ENTRY_PRESENT | ENTRY_WRITABLE | ENTRY_USER,
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

fn activate(space: &AddressSpace) -> Result<(), &'static str> {
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

fn destroy(space: &mut AddressSpace) -> Result<(), &'static str> {
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
