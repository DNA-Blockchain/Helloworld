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
