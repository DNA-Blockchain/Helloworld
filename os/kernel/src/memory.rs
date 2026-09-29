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

use bootloader_api::{BootInfo, info::MemoryRegionKind};
use core::{
    cell::UnsafeCell,
    hint::spin_loop,
    ptr::{read_volatile, write_volatile},
    sync::atomic::{AtomicBool, AtomicU64, Ordering},
};

const PAGE_SIZE: u64 = 4096;
const MAX_PHYSICAL_ADDRESS: u64 = 1 << 32;
const FIRST_MANAGED_ADDRESS: u64 = 1 << 20;
const FRAME_COUNT: usize = (MAX_PHYSICAL_ADDRESS / PAGE_SIZE) as usize;
const BITMAP_WORDS: usize = FRAME_COUNT / u64::BITS as usize;
const MAX_USABLE_RANGES: usize = 128;

#[derive(Clone, Copy)]
struct FrameRange {
    start: usize,
    end: usize,
}

impl FrameRange {
    const EMPTY: Self = Self { start: 0, end: 0 };
}

struct StaticBitmap(UnsafeCell<[u64; BITMAP_WORDS]>);
struct StaticRanges(UnsafeCell<[FrameRange; MAX_USABLE_RANGES]>);

// Metadata is protected by the allocator lock; initialization runs once at boot.
unsafe impl Sync for StaticBitmap {}
unsafe impl Sync for StaticRanges {}

static BITMAP: StaticBitmap = StaticBitmap(UnsafeCell::new([u64::MAX; BITMAP_WORDS]));
static RANGES: StaticRanges = StaticRanges(UnsafeCell::new([FrameRange::EMPTY; MAX_USABLE_RANGES]));
static RANGE_COUNT: AtomicU64 = AtomicU64::new(0);
static PHYSICAL_MEMORY_OFFSET: AtomicU64 = AtomicU64::new(0);
static INITIALIZED: AtomicBool = AtomicBool::new(false);
static ALLOCATOR_LOCK: AtomicBool = AtomicBool::new(false);

struct AllocatorGuard {
    interrupts_were_enabled: bool,
}

impl Drop for AllocatorGuard {
    fn drop(&mut self) {
        ALLOCATOR_LOCK.store(false, Ordering::Release);
        if self.interrupts_were_enabled {
            unsafe {
                core::arch::asm!("sti", options(nomem, nostack, preserves_flags));
            }
        }
    }
}

pub(crate) fn initialize(boot_info: &BootInfo) -> Result<(), &'static str> {
    let _guard = lock_allocator();
    if INITIALIZED.load(Ordering::Relaxed) {
        return Err("physical frame allocator was initialized more than once");
    }
    let memory_offset = boot_info
        .physical_memory_offset
        .into_option()
        .ok_or("bootloader did not map physical memory for the frame allocator")?;

    let mut ranges = 0;
    for region in boot_info.memory_regions.iter() {
        if region.kind != MemoryRegionKind::Usable {
            continue;
        }
        let start_address = region
            .start
            .max(FIRST_MANAGED_ADDRESS)
            .checked_add(PAGE_SIZE - 1)
            .ok_or("usable memory region start overflow")?
            & !(PAGE_SIZE - 1);
        let end_address = region.end.min(MAX_PHYSICAL_ADDRESS) & !(PAGE_SIZE - 1);
        if start_address >= end_address {
            continue;
        }
        if ranges == MAX_USABLE_RANGES {
            return Err("too many usable memory regions for the frame allocator");
        }
        let start = (start_address / PAGE_SIZE) as usize;
        let end = (end_address / PAGE_SIZE) as usize;
        unsafe {
            let bitmap = &mut *BITMAP.0.get();
            for frame in start..end {
                set_frame(bitmap, frame, false);
            }
            (*RANGES.0.get())[ranges] = FrameRange { start, end };
        }
        ranges += 1;
    }
    if ranges == 0 {
        return Err("bootloader reported no usable physical memory below 4 GiB");
    }

    PHYSICAL_MEMORY_OFFSET.store(memory_offset, Ordering::Relaxed);
    RANGE_COUNT.store(ranges as u64, Ordering::Relaxed);
    INITIALIZED.store(true, Ordering::Release);
    Ok(())
}

pub(crate) fn allocate(pages: usize, alignment_pages: usize) -> Result<u64, &'static str> {
    if pages == 0 || alignment_pages == 0 || !alignment_pages.is_power_of_two() {
        return Err("frame allocation requires a positive page count and power-of-two alignment");
    }
    let _guard = lock_allocator();
    ensure_initialized()?;
    let bitmap = unsafe { &mut *BITMAP.0.get() };
    let ranges = unsafe { &*RANGES.0.get() };
    let range_count = RANGE_COUNT.load(Ordering::Relaxed) as usize;

    for range in ranges.iter().take(range_count) {
        let mut candidate =
            align_up(range.start, alignment_pages).ok_or("frame allocation alignment overflow")?;
        while candidate
            .checked_add(pages)
            .is_some_and(|end| end <= range.end)
        {
            if (candidate..candidate + pages).all(|frame| !frame_is_set(bitmap, frame)) {
                for frame in candidate..candidate + pages {
                    set_frame(bitmap, frame, true);
                }
                return Ok((candidate as u64) * PAGE_SIZE);
            }
            candidate = candidate
                .checked_add(alignment_pages)
                .ok_or("frame allocation search overflow")?;
        }
    }
    Err("no contiguous usable physical frames satisfy the allocation")
}

pub(crate) fn deallocate(physical_address: u64, pages: usize) -> Result<(), &'static str> {
    if pages == 0 || physical_address % PAGE_SIZE != 0 {
        return Err("frame deallocation requires an aligned address and positive page count");
    }
    let start = usize::try_from(physical_address / PAGE_SIZE)
        .map_err(|_| "physical frame address does not fit the allocator")?;
    let end = start
        .checked_add(pages)
        .ok_or("frame deallocation range overflow")?;
    if end > FRAME_COUNT {
        return Err("frame deallocation exceeds the managed physical range");
    }

    let _guard = lock_allocator();
    ensure_initialized()?;
    let ranges = unsafe { &*RANGES.0.get() };
    let range_count = RANGE_COUNT.load(Ordering::Relaxed) as usize;
    if !ranges
        .iter()
        .take(range_count)
        .any(|range| start >= range.start && end <= range.end)
    {
        return Err("cannot free frames outside a usable memory region");
    }

    let bitmap = unsafe { &mut *BITMAP.0.get() };
    if !(start..end).all(|frame| frame_is_set(bitmap, frame)) {
        return Err("cannot free a frame that is already available");
    }
    for frame in start..end {
        set_frame(bitmap, frame, false);
    }
    Ok(())
}

pub(crate) fn verify_allocate_and_release() -> Result<(), &'static str> {
    let physical_address = allocate(1, 1)?;
    let virtual_address = PHYSICAL_MEMORY_OFFSET
        .load(Ordering::Relaxed)
        .checked_add(physical_address)
        .ok_or("frame test virtual address overflow")?;
    let pointer = usize::try_from(virtual_address)
        .map_err(|_| "frame test virtual address does not fit the kernel pointer width")?
        as *mut u64;
    unsafe {
        write_volatile(pointer, 0x4e45_5457_4f53_4f53);
        if read_volatile(pointer) != 0x4e45_5457_4f53_4f53 {
            return Err("physical frame allocation read/write verification failed");
        }
    }
    deallocate(physical_address, 1)?;
    let reused_address = allocate(1, 1)?;
    if reused_address != physical_address {
        return Err("released physical frame was not reusable");
    }
    deallocate(reused_address, 1)?;
    Ok(())
}

fn lock_allocator() -> AllocatorGuard {
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
    while ALLOCATOR_LOCK
        .compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
        .is_err()
    {
        spin_loop();
    }
    AllocatorGuard {
        interrupts_were_enabled: flags & (1 << 9) != 0,
    }
}

fn ensure_initialized() -> Result<(), &'static str> {
    if INITIALIZED.load(Ordering::Acquire) {
        Ok(())
    } else {
        Err("physical frame allocator has not been initialized")
    }
}

fn frame_is_set(bitmap: &[u64; BITMAP_WORDS], frame: usize) -> bool {
    bitmap[frame / u64::BITS as usize] & (1 << (frame % u64::BITS as usize)) != 0
}

fn set_frame(bitmap: &mut [u64; BITMAP_WORDS], frame: usize, allocated: bool) {
    let mask = 1 << (frame % u64::BITS as usize);
    let word = &mut bitmap[frame / u64::BITS as usize];
    if allocated {
        *word |= mask;
    } else {
        *word &= !mask;
    }
}

fn align_up(value: usize, alignment: usize) -> Option<usize> {
    value
        .checked_add(alignment - 1)
        .map(|aligned| aligned & !(alignment - 1))
}
