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
    alloc::{GlobalAlloc, Layout},
    cell::UnsafeCell,
    mem::MaybeUninit,
    ptr::{NonNull, null_mut},
    sync::atomic::{AtomicBool, AtomicUsize, Ordering},
};
use linked_list_allocator::Heap;

const INITIAL_HEAP_PAGES: usize = 16;
const MAX_HEAP_PAGES: usize = 128;
const PAGE_SIZE: usize = 4096;

struct KernelHeap {
    lock: AtomicBool,
    initialized: AtomicBool,
    heap: UnsafeCell<MaybeUninit<Heap>>,
}

unsafe impl Sync for KernelHeap {}

struct HeapGuard {
    interrupts_were_enabled: bool,
}

impl Drop for HeapGuard {
    fn drop(&mut self) {
        HEAP.lock.store(false, Ordering::Release);
        if self.interrupts_were_enabled {
            unsafe {
                core::arch::asm!("sti", options(nomem, nostack, preserves_flags));
            }
        }
    }
}

#[global_allocator]
static HEAP: KernelHeap = KernelHeap {
    lock: AtomicBool::new(false),
    initialized: AtomicBool::new(false),
    heap: UnsafeCell::new(MaybeUninit::uninit()),
};
static HEAP_BASE: AtomicUsize = AtomicUsize::new(0);
static HEAP_PAGE_COUNT: AtomicUsize = AtomicUsize::new(0);

unsafe impl GlobalAlloc for KernelHeap {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let _guard = self.lock_heap();
        if !self.initialized.load(Ordering::Acquire) {
            return null_mut();
        }
        let heap = unsafe { (*self.heap.get()).assume_init_mut() };
        loop {
            if let Ok(allocation) = heap.allocate_first_fit(layout) {
                return allocation.as_ptr();
            }
            if !grow_heap(heap) {
                return null_mut();
            }
        }
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        let _guard = self.lock_heap();
        if !self.initialized.load(Ordering::Acquire) {
            return;
        }
        let pointer = NonNull::new(pointer).expect("global allocator deallocated a null pointer");
        unsafe {
            (*self.heap.get())
                .assume_init_mut()
                .deallocate(pointer, layout);
        }
    }
}

impl KernelHeap {
    fn lock_heap(&self) -> HeapGuard {
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
        while self
            .lock
            .compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
            .is_err()
        {
            core::hint::spin_loop();
        }
        HeapGuard {
            interrupts_were_enabled: flags & (1 << 9) != 0,
        }
    }
}

pub(crate) fn initialize() -> Result<(), &'static str> {
    let _guard = HEAP.lock_heap();
    if HEAP.initialized.load(Ordering::Relaxed) {
        return Err("kernel heap was initialized more than once");
    }

    let mut base = None;
    let mut allocated_pages = 0;
    for index in 0..INITIAL_HEAP_PAGES {
        let address = match super::virtual_memory::allocate_page() {
            Ok(address) => address,
            Err(error) => {
                release_pages(base, allocated_pages)?;
                return Err(error);
            }
        };
        if let Some(base_address) = base {
            let expected = base_address + (index * PAGE_SIZE) as u64;
            if address != expected {
                super::virtual_memory::deallocate_page(address)?;
                release_pages(base, allocated_pages)?;
                return Err("kernel heap pages are not virtually contiguous");
            }
        } else {
            base = Some(address);
        }
        allocated_pages += 1;
    }

    let base = base.ok_or("kernel heap has no mapped pages")?;
    let heap_size = INITIAL_HEAP_PAGES * PAGE_SIZE;
    unsafe {
        HEAP.heap
            .get()
            .write(MaybeUninit::new(Heap::new(base as *mut u8, heap_size)));
    }
    HEAP_BASE.store(base as usize, Ordering::Relaxed);
    HEAP_PAGE_COUNT.store(INITIAL_HEAP_PAGES, Ordering::Relaxed);
    HEAP.initialized.store(true, Ordering::Release);
    Ok(())
}

pub(crate) fn verify_allocation_lifecycle() -> Result<usize, &'static str> {
    if !HEAP.initialized.load(Ordering::Acquire) {
        return Err("kernel heap has not been initialized");
    }

    let mut values = alloc::vec::Vec::with_capacity(40_000);
    for value in 0..40_000u64 {
        values.push(value * 3);
    }
    if values
        .iter()
        .enumerate()
        .any(|(index, value)| *value != index as u64 * 3)
    {
        return Err("kernel heap vector contents did not survive allocation");
    }
    let allocated_pages = HEAP_PAGE_COUNT.load(Ordering::Relaxed);
    if allocated_pages <= INITIAL_HEAP_PAGES {
        return Err("kernel heap did not grow for the large vector allocation");
    }
    drop(values);

    let value = alloc::boxed::Box::new(0x4845_4150_4f53_3031u64);
    if *value != 0x4845_4150_4f53_3031 {
        return Err("kernel heap box contents did not survive allocation");
    }
    drop(value);
    Ok(allocated_pages)
}

fn grow_heap(heap: &mut Heap) -> bool {
    let current_pages = HEAP_PAGE_COUNT.load(Ordering::Relaxed);
    if current_pages >= MAX_HEAP_PAGES {
        return false;
    }
    let Some(expected_address) = HEAP_BASE
        .load(Ordering::Relaxed)
        .checked_add(current_pages * PAGE_SIZE)
    else {
        return false;
    };
    let Ok(address) = super::virtual_memory::allocate_page() else {
        return false;
    };
    if address as usize != expected_address {
        if let Err(error) = super::virtual_memory::deallocate_page(address) {
            panic!("could not release non-contiguous heap page: {error}");
        }
        return false;
    }

    unsafe {
        heap.extend(PAGE_SIZE);
    }
    HEAP_PAGE_COUNT.store(current_pages + 1, Ordering::Relaxed);
    true
}

fn release_pages(base: Option<u64>, pages: usize) -> Result<(), &'static str> {
    let Some(base) = base else {
        return Ok(());
    };
    for index in (0..pages).rev() {
        super::virtual_memory::deallocate_page(base + (index * PAGE_SIZE) as u64)?;
    }
    Ok(())
}
