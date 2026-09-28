use core::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

const TASK_STACK_PAGES: usize = 4;
const PAGE_SIZE: usize = 4096;
static TASK_STACK_BASE: AtomicUsize = AtomicUsize::new(0);
static TASK_STACK_LIMIT: AtomicUsize = AtomicUsize::new(0);
static TASK_CHECK_PASSED: AtomicBool = AtomicBool::new(false);

core::arch::global_asm!(
    ".global kernel_stack_switch",
    "kernel_stack_switch:",
    "push r12",
    "mov r12, rsp",
    "mov rsp, rdi",
    "and rsp, -16",
    "call rsi",
    "mov rsp, r12",
    "pop r12",
    "ret",
);

unsafe extern "C" {
    fn kernel_stack_switch(stack_top: usize, entry: extern "C" fn());
}

pub(crate) fn verify_separate_kernel_stack() -> Result<(), &'static str> {
    let mut stack_base = None;
    let mut allocated_pages = 0;

    for index in 0..TASK_STACK_PAGES {
        let address = match super::virtual_memory::allocate_page() {
            Ok(address) => address as usize,
            Err(error) => {
                release_stack(stack_base, allocated_pages)?;
                return Err(error);
            }
        };
        if let Some(base) = stack_base {
            if address != base + index * PAGE_SIZE {
                super::virtual_memory::deallocate_page(address as u64)?;
                release_stack(stack_base, allocated_pages)?;
                return Err("kernel task stack pages are not virtually contiguous");
            }
        } else {
            stack_base = Some(address);
        }
        allocated_pages += 1;
    }

    let base = stack_base.ok_or("kernel task stack has no pages")?;
    let limit = base + TASK_STACK_PAGES * PAGE_SIZE;
    TASK_STACK_BASE.store(base, Ordering::Relaxed);
    TASK_STACK_LIMIT.store(limit, Ordering::Relaxed);
    TASK_CHECK_PASSED.store(false, Ordering::Relaxed);

    run_on_stack(limit, task_stack_entry);

    let result = if TASK_CHECK_PASSED.load(Ordering::Acquire) {
        Ok(())
    } else {
        Err("kernel task did not execute and allocate on its separate stack")
    };
    release_stack(stack_base, allocated_pages)?;
    result
}

pub(crate) fn run_on_stack(stack_top: usize, entry: extern "C" fn()) {
    unsafe {
        kernel_stack_switch(stack_top, entry);
    }
}

extern "C" fn task_stack_entry() {
    let stack_pointer: usize;
    unsafe {
        core::arch::asm!(
            "mov {}, rsp",
            out(reg) stack_pointer,
            options(nomem, nostack, preserves_flags)
        );
    }
    let on_task_stack = stack_pointer >= TASK_STACK_BASE.load(Ordering::Relaxed)
        && stack_pointer < TASK_STACK_LIMIT.load(Ordering::Relaxed);
    if !on_task_stack {
        return;
    }

    let values: alloc::vec::Vec<u64> = (0..256).map(|value| value * 7).collect();
    if values
        .iter()
        .enumerate()
        .all(|(index, value)| *value == index as u64 * 7)
    {
        TASK_CHECK_PASSED.store(true, Ordering::Release);
    }
}

fn release_stack(base: Option<usize>, pages: usize) -> Result<(), &'static str> {
    let Some(base) = base else {
        return Ok(());
    };
    for index in (0..pages).rev() {
        super::virtual_memory::deallocate_page((base + index * PAGE_SIZE) as u64)?;
    }
    Ok(())
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
