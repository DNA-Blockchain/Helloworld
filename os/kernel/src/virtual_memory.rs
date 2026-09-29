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

use core::{
    cell::UnsafeCell,
    mem::size_of,
    ptr::{read_volatile, write_volatile},
    sync::atomic::{AtomicBool, AtomicU64, Ordering},
};

const PAGE_SIZE: u64 = 4096;
const ENTRY_PRESENT: u64 = 1;
const ENTRY_WRITABLE: u64 = 1 << 1;
const ENTRY_HUGE: u64 = 1 << 7;
const ENTRY_ADDRESS_MASK: u64 = 0x000f_ffff_ffff_f000;
const FIRST_KERNEL_PML4_INDEX: usize = 256;
const LAST_KERNEL_PML4_INDEX: usize = 512;
const MAX_VIRTUAL_PAGES: usize = 128;

#[derive(Clone, Copy)]
struct PageRecord {
    virtual_address: u64,
    physical_address: u64,
    allocated: bool,
}

impl PageRecord {
    const EMPTY: Self = Self {
        virtual_address: 0,
        physical_address: 0,
        allocated: false,
    };
}

struct StaticRecords(UnsafeCell<[PageRecord; MAX_VIRTUAL_PAGES]>);

// Records are accessed only while the single-core kernel has interrupts disabled.
unsafe impl Sync for StaticRecords {}

static RECORDS: StaticRecords =
    StaticRecords(UnsafeCell::new([PageRecord::EMPTY; MAX_VIRTUAL_PAGES]));
static PHYSICAL_MEMORY_OFFSET: AtomicU64 = AtomicU64::new(0);
static PAGE_TABLE_ROOT: AtomicU64 = AtomicU64::new(0);
static VIRTUAL_ARENA_BASE: AtomicU64 = AtomicU64::new(0);
static INITIALIZED: AtomicBool = AtomicBool::new(false);

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
        return Err("virtual memory manager was initialized more than once");
    }
    if physical_memory_offset % PAGE_SIZE != 0 {
        return Err("physical memory mapping offset is not page-aligned");
    }

    let root = read_cr3() & ENTRY_ADDRESS_MASK;
    let root_virtual = physical_to_virtual(physical_memory_offset, root)?;
    let root_table = root_virtual as *const u64;
    let mut arena_base = None;
    for pml4_index in FIRST_KERNEL_PML4_INDEX..LAST_KERNEL_PML4_INDEX {
        let entry = unsafe { read_volatile(root_table.add(pml4_index)) };
        if entry == 0 {
            arena_base = Some(canonical_pml4_base(pml4_index));
            break;
        }
    }
    let arena_base = arena_base.ok_or("no unused canonical kernel PML4 slot is available")?;

    for index in 0..MAX_VIRTUAL_PAGES {
        unsafe {
            (*RECORDS.0.get())[index] = PageRecord {
                virtual_address: arena_base + (index as u64) * PAGE_SIZE,
                ..PageRecord::EMPTY
            };
        }
    }
    PHYSICAL_MEMORY_OFFSET.store(physical_memory_offset, Ordering::Relaxed);
    PAGE_TABLE_ROOT.store(root, Ordering::Relaxed);
    VIRTUAL_ARENA_BASE.store(arena_base, Ordering::Relaxed);
    INITIALIZED.store(true, Ordering::Release);
    Ok(())
}

pub(crate) fn allocate_page() -> Result<u64, &'static str> {
    let _guard = disable_interrupts();
    ensure_initialized()?;
    let record_index = unsafe {
        (&*RECORDS.0.get())
            .iter()
            .position(|record| !record.allocated)
    }
    .ok_or("virtual page arena is full")?;
    let physical_address = super::memory::allocate(1, 1)?;
    if let Err(error) = zero_physical_page(physical_address) {
        super::memory::deallocate(physical_address, 1)?;
        return Err(error);
    }

    let virtual_address = unsafe { (*RECORDS.0.get())[record_index].virtual_address };
    if let Err(error) = map_page(virtual_address, physical_address) {
        super::memory::deallocate(physical_address, 1)?;
        return Err(error);
    }
    unsafe {
        (*RECORDS.0.get())[record_index] = PageRecord {
            virtual_address,
            physical_address,
            allocated: true,
        };
    }
    Ok(virtual_address)
}

pub(crate) fn deallocate_page(virtual_address: u64) -> Result<(), &'static str> {
    if virtual_address % PAGE_SIZE != 0 {
        return Err("virtual page address is not page-aligned");
    }
    let _guard = disable_interrupts();
    ensure_initialized()?;
    let record_index = unsafe {
        (&*RECORDS.0.get())
            .iter()
            .position(|record| record.allocated && record.virtual_address == virtual_address)
    }
    .ok_or("virtual address is not an allocated page from this arena")?;

    let physical_address = unsafe { (*RECORDS.0.get())[record_index].physical_address };
    unmap_page(virtual_address)?;
    super::memory::deallocate(physical_address, 1)?;
    unsafe {
        (*RECORDS.0.get())[record_index].physical_address = 0;
        (*RECORDS.0.get())[record_index].allocated = false;
    }
    Ok(())
}

pub(crate) fn verify_mapping_lifecycle() -> Result<(), &'static str> {
    let virtual_address = allocate_page()?;
    let pointer = usize::try_from(virtual_address)
        .map_err(|_| "test virtual address does not fit the kernel pointer width")?
        as *mut u64;
    unsafe {
        if read_volatile(pointer) != 0 {
            deallocate_page(virtual_address)?;
            return Err("newly mapped virtual page was not zero-initialized");
        }
        write_volatile(pointer, 0x5649_5254_5541_4c31);
        if read_volatile(pointer) != 0x5649_5254_5541_4c31 {
            deallocate_page(virtual_address)?;
            return Err("virtual page read/write verification failed");
        }
    }

    deallocate_page(virtual_address)?;
    if mapped_leaf_entry(virtual_address)? != 0 {
        return Err("virtual page-table entry remained present after unmapping");
    }
    if deallocate_page(virtual_address).is_ok() {
        return Err("virtual page was deallocated twice without an error");
    }
    let reused_virtual_address = allocate_page()?;
    if reused_virtual_address != virtual_address {
        deallocate_page(reused_virtual_address)?;
        return Err("released virtual arena slot was not reused");
    }
    deallocate_page(reused_virtual_address)?;
    Ok(())
}

fn map_page(virtual_address: u64, physical_address: u64) -> Result<(), &'static str> {
    if virtual_address % PAGE_SIZE != 0 || physical_address % PAGE_SIZE != 0 {
        return Err("page mappings require aligned virtual and physical addresses");
    }
    if virtual_address >> 39 & 0x1ff != (VIRTUAL_ARENA_BASE.load(Ordering::Relaxed) >> 39) & 0x1ff {
        return Err("virtual address is outside the managed PML4 slot");
    }

    let indices = page_table_indices(virtual_address);
    let offset = PHYSICAL_MEMORY_OFFSET.load(Ordering::Relaxed);
    let mut table_physical = PAGE_TABLE_ROOT.load(Ordering::Relaxed);
    let mut created_tables = [(0u64, core::ptr::null_mut::<u64>()); 3];
    let mut created_count = 0;
    let mapping_result = (|| {
        for index in indices.iter().take(3) {
            let entry_pointer = table_entry_pointer(offset, table_physical, *index)?;
            let mut entry = unsafe { read_volatile(entry_pointer) };
            if entry & ENTRY_PRESENT == 0 {
                let next_table = super::memory::allocate(1, 1)?;
                if let Err(error) = zero_physical_page(next_table) {
                    super::memory::deallocate(next_table, 1)?;
                    return Err(error);
                }
                entry = next_table | ENTRY_PRESENT | ENTRY_WRITABLE;
                unsafe {
                    write_volatile(entry_pointer, entry);
                }
                created_tables[created_count] = (next_table, entry_pointer);
                created_count += 1;
            } else if entry & ENTRY_HUGE != 0 {
                return Err("cannot descend through an existing huge-page mapping");
            } else if entry & ENTRY_WRITABLE == 0 {
                entry |= ENTRY_WRITABLE;
                unsafe {
                    write_volatile(entry_pointer, entry);
                }
            }
            table_physical = entry & ENTRY_ADDRESS_MASK;
        }

        let leaf_pointer = table_entry_pointer(offset, table_physical, indices[3])?;
        if unsafe { read_volatile(leaf_pointer) } & ENTRY_PRESENT != 0 {
            return Err("virtual address is already mapped");
        }
        Ok(leaf_pointer)
    })();
    let leaf_pointer = match mapping_result {
        Ok(pointer) => pointer,
        Err(error) => {
            for (table, parent_entry) in created_tables[..created_count].iter().rev() {
                unsafe {
                    write_volatile(*parent_entry, 0);
                }
                super::memory::deallocate(*table, 1)?;
            }
            return Err(error);
        }
    };
    unsafe {
        write_volatile(
            leaf_pointer,
            physical_address | ENTRY_PRESENT | ENTRY_WRITABLE,
        );
    }
    invalidate_page(virtual_address);
    Ok(())
}

fn unmap_page(virtual_address: u64) -> Result<(), &'static str> {
    let indices = page_table_indices(virtual_address);
    let offset = PHYSICAL_MEMORY_OFFSET.load(Ordering::Relaxed);
    let mut table_physical = PAGE_TABLE_ROOT.load(Ordering::Relaxed);
    let mut table_frames = [0u64; 3];
    let mut parent_entries = [core::ptr::null_mut::<u64>(); 3];
    for (level, index) in indices.iter().take(3).enumerate() {
        let entry_pointer = table_entry_pointer(offset, table_physical, *index)?;
        let entry = unsafe { read_volatile(entry_pointer) };
        if entry & ENTRY_PRESENT == 0 || entry & ENTRY_HUGE != 0 {
            return Err("virtual page does not have a managed 4-KiB mapping");
        }
        table_frames[level] = entry & ENTRY_ADDRESS_MASK;
        parent_entries[level] = entry_pointer;
        table_physical = entry & ENTRY_ADDRESS_MASK;
    }
    let leaf_pointer = table_entry_pointer(offset, table_physical, indices[3])?;
    let entry = unsafe { read_volatile(leaf_pointer) };
    if entry & ENTRY_PRESENT == 0 {
        return Err("virtual page is not mapped");
    }
    unsafe {
        write_volatile(leaf_pointer, 0);
    }
    invalidate_page(virtual_address);
    for level in (0..3).rev() {
        if table_is_empty(offset, table_frames[level])? {
            unsafe {
                write_volatile(parent_entries[level], 0);
            }
            super::memory::deallocate(table_frames[level], 1)?;
        } else {
            break;
        }
    }
    Ok(())
}

fn mapped_leaf_entry(virtual_address: u64) -> Result<u64, &'static str> {
    let indices = page_table_indices(virtual_address);
    let offset = PHYSICAL_MEMORY_OFFSET.load(Ordering::Relaxed);
    let mut table_physical = PAGE_TABLE_ROOT.load(Ordering::Relaxed);
    for index in indices.iter().take(3) {
        let pointer = table_entry_pointer(offset, table_physical, *index)?;
        let entry = unsafe { read_volatile(pointer) };
        if entry & ENTRY_PRESENT == 0 {
            return Ok(0);
        }
        if entry & ENTRY_HUGE != 0 {
            return Err("virtual address resolves through an unexpected huge page");
        }
        table_physical = entry & ENTRY_ADDRESS_MASK;
    }
    let pointer = table_entry_pointer(offset, table_physical, indices[3])?;
    Ok(unsafe { read_volatile(pointer) })
}

fn table_is_empty(physical_memory_offset: u64, table_physical: u64) -> Result<bool, &'static str> {
    let table_virtual = physical_to_virtual(physical_memory_offset, table_physical)?;
    let table_pointer = usize::try_from(table_virtual)
        .map(|address| address as *const u64)
        .map_err(|_| "page-table address does not fit the kernel pointer width")?;
    for index in 0..512 {
        if unsafe { read_volatile(table_pointer.add(index)) } & ENTRY_PRESENT != 0 {
            return Ok(false);
        }
    }
    Ok(true)
}

fn zero_physical_page(physical_address: u64) -> Result<(), &'static str> {
    let offset = PHYSICAL_MEMORY_OFFSET.load(Ordering::Relaxed);
    let virtual_address = physical_to_virtual(offset, physical_address)?;
    let pointer = virtual_address as *mut u8;
    unsafe {
        core::ptr::write_bytes(pointer, 0, PAGE_SIZE as usize);
    }
    Ok(())
}

fn physical_to_virtual(offset: u64, physical_address: u64) -> Result<u64, &'static str> {
    offset
        .checked_add(physical_address)
        .ok_or("physical-to-virtual address overflow")
}

fn table_entry_pointer(
    physical_memory_offset: u64,
    table_physical: u64,
    index: usize,
) -> Result<*mut u64, &'static str> {
    let table_virtual = physical_to_virtual(physical_memory_offset, table_physical)?;
    let entry_virtual = table_virtual
        .checked_add((index as u64) * size_of::<u64>() as u64)
        .ok_or("page-table entry address overflow")?;
    usize::try_from(entry_virtual)
        .map(|address| address as *mut u64)
        .map_err(|_| "page-table address does not fit the kernel pointer width")
}

fn page_table_indices(virtual_address: u64) -> [usize; 4] {
    [
        ((virtual_address >> 39) & 0x1ff) as usize,
        ((virtual_address >> 30) & 0x1ff) as usize,
        ((virtual_address >> 21) & 0x1ff) as usize,
        ((virtual_address >> 12) & 0x1ff) as usize,
    ]
}

fn canonical_pml4_base(index: usize) -> u64 {
    ((index as u64) << 39) | 0xffff_0000_0000_0000
}

fn ensure_initialized() -> Result<(), &'static str> {
    if INITIALIZED.load(Ordering::Acquire) {
        Ok(())
    } else {
        Err("virtual memory manager has not been initialized")
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

fn invalidate_page(virtual_address: u64) {
    unsafe {
        core::arch::asm!(
            "invlpg [{}]",
            in(reg) virtual_address as usize,
            options(nostack, preserves_flags)
        );
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
