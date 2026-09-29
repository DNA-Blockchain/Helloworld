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
    ptr,
    sync::atomic::{AtomicBool, AtomicU8, AtomicUsize, Ordering},
};

const TASK_COUNT: usize = 2;
const CONTEXT_COUNT: usize = TASK_COUNT + 1;
const ROOT_CONTEXT: usize = 0;
const TASK_A_CONTEXT: usize = 1;
const TASK_B_CONTEXT: usize = 2;
const STACK_PAGES: usize = 4;
const PAGE_SIZE: usize = 4096;
const EXPECTED_TRACE: [usize; 5] = [1, 2, 1, 2, 1];
const TASK_READY: u8 = 0;
const TASK_RUNNING: u8 = 1;
const TASK_BLOCKED: u8 = 2;
const TASK_EXITED: u8 = 3;

struct TaskContexts(UnsafeCell<[usize; CONTEXT_COUNT]>);

unsafe impl Sync for TaskContexts {}

static CONTEXTS: TaskContexts = TaskContexts(UnsafeCell::new([0; CONTEXT_COUNT]));
static ACTIVE_CONTEXT: AtomicUsize = AtomicUsize::new(ROOT_CONTEXT);
static STACK_BASES: [AtomicUsize; TASK_COUNT] = [const { AtomicUsize::new(0) }; TASK_COUNT];
static STACK_LIMITS: [AtomicUsize; TASK_COUNT] = [const { AtomicUsize::new(0) }; TASK_COUNT];
static TRACE_LENGTH: AtomicUsize = AtomicUsize::new(0);
static TRACE: [AtomicUsize; EXPECTED_TRACE.len()] =
    [const { AtomicUsize::new(0) }; EXPECTED_TRACE.len()];
static CHECKS_PASSED: AtomicBool = AtomicBool::new(true);
static TASK_STATES: [AtomicU8; TASK_COUNT] = [const { AtomicU8::new(TASK_READY) }; TASK_COUNT];
static TASK_A_WAITED: AtomicBool = AtomicBool::new(false);
static TASK_A_WOKEN: AtomicBool = AtomicBool::new(false);

core::arch::global_asm!(
    ".global task_context_switch",
    "task_context_switch:",
    "push rbx",
    "push rbp",
    "push r12",
    "push r13",
    "push r14",
    "push r15",
    "mov [rdi], rsp",
    "mov rsp, rsi",
    "pop r15",
    "pop r14",
    "pop r13",
    "pop r12",
    "pop rbp",
    "pop rbx",
    "ret",
);

unsafe extern "C" {
    fn task_context_switch(current_stack: *mut usize, next_stack: usize);
}

pub(crate) fn verify_cooperative_round_robin() -> Result<usize, &'static str> {
    let mut stacks = [None; TASK_COUNT];
    for index in 0..TASK_COUNT {
        match allocate_stack() {
            Ok(base) => stacks[index] = Some(base),
            Err(error) => {
                for base in stacks.iter().copied().flatten() {
                    release_stack(base)?;
                }
                return Err(error);
            }
        }
    }

    TRACE_LENGTH.store(0, Ordering::Relaxed);
    CHECKS_PASSED.store(true, Ordering::Relaxed);
    ACTIVE_CONTEXT.store(ROOT_CONTEXT, Ordering::Relaxed);
    TASK_STATES[TASK_A_CONTEXT - 1].store(TASK_READY, Ordering::Relaxed);
    TASK_STATES[TASK_B_CONTEXT - 1].store(TASK_READY, Ordering::Relaxed);
    TASK_A_WAITED.store(false, Ordering::Relaxed);
    TASK_A_WOKEN.store(false, Ordering::Relaxed);

    let stack_a = stacks[0].ok_or("task A stack is missing")?;
    let stack_b = stacks[1].ok_or("task B stack is missing")?;
    STACK_BASES[0].store(stack_a, Ordering::Relaxed);
    STACK_LIMITS[0].store(stack_a + STACK_PAGES * PAGE_SIZE, Ordering::Relaxed);
    STACK_BASES[1].store(stack_b, Ordering::Relaxed);
    STACK_LIMITS[1].store(stack_b + STACK_PAGES * PAGE_SIZE, Ordering::Relaxed);

    unsafe {
        initialize_context(TASK_A_CONTEXT, stack_a, task_bootstrap);
        initialize_context(TASK_B_CONTEXT, stack_b, task_bootstrap);
        switch_to(TASK_A_CONTEXT);
    }

    let trace_length = TRACE_LENGTH.load(Ordering::Acquire);
    let valid_trace = trace_length == EXPECTED_TRACE.len()
        && EXPECTED_TRACE
            .iter()
            .enumerate()
            .all(|(index, expected)| TRACE[index].load(Ordering::Relaxed) == *expected);
    let checks_passed = CHECKS_PASSED.load(Ordering::Acquire);
    let lifecycle_passed = TASK_A_WAITED.load(Ordering::Acquire)
        && TASK_A_WOKEN.load(Ordering::Acquire)
        && TASK_STATES[TASK_A_CONTEXT - 1].load(Ordering::Acquire) == TASK_EXITED
        && TASK_STATES[TASK_B_CONTEXT - 1].load(Ordering::Acquire) == TASK_READY;
    for base in stacks.into_iter().flatten() {
        release_stack(base)?;
    }
    if !valid_trace {
        return Err("cooperative context switch did not produce the expected A/B/A/B/A trace");
    }
    if !checks_passed {
        return Err("a resumed task failed its stack or continuation check");
    }
    if !lifecycle_passed {
        return Err("cooperative task block/wake lifecycle reached an unexpected state");
    }
    Ok(trace_length)
}

unsafe fn initialize_context(context_index: usize, stack_base: usize, entry: extern "C" fn() -> !) {
    let stack_top = (stack_base + STACK_PAGES * PAGE_SIZE) & !0xf;
    let saved_stack = stack_top - 8 - 7 * size_of::<usize>();
    let frame = saved_stack as *mut usize;
    for index in 0..6 {
        unsafe {
            frame.add(index).write(0);
        }
    }
    unsafe {
        frame.add(6).write(entry as *const () as usize);
        context_slot(context_index).write(saved_stack);
    }
}

fn allocate_stack() -> Result<usize, &'static str> {
    let mut base = None;
    let mut allocated = 0;
    for index in 0..STACK_PAGES {
        let address = match super::virtual_memory::allocate_page() {
            Ok(address) => address as usize,
            Err(error) => {
                release_partial_stack(base, allocated)?;
                return Err(error);
            }
        };
        if let Some(stack_base) = base {
            if address != stack_base + index * PAGE_SIZE {
                super::virtual_memory::deallocate_page(address as u64)?;
                release_partial_stack(base, allocated)?;
                return Err("cooperative task stack pages are not contiguous");
            }
        } else {
            base = Some(address);
        }
        allocated += 1;
    }
    base.ok_or("cooperative task stack has no pages")
}

fn release_partial_stack(base: Option<usize>, pages: usize) -> Result<(), &'static str> {
    let Some(base) = base else {
        return Ok(());
    };
    for index in (0..pages).rev() {
        super::virtual_memory::deallocate_page((base + index * PAGE_SIZE) as u64)?;
    }
    Ok(())
}

fn release_stack(base: usize) -> Result<(), &'static str> {
    release_partial_stack(Some(base), STACK_PAGES)
}

fn context_slot(index: usize) -> *mut usize {
    unsafe { ptr::addr_of_mut!((*CONTEXTS.0.get())[index]) }
}

unsafe fn switch_to(next_context: usize) {
    let current_context = ACTIVE_CONTEXT.load(Ordering::Relaxed);
    if current_context != ROOT_CONTEXT {
        let current_state = &TASK_STATES[current_context - 1];
        if current_state.load(Ordering::Acquire) == TASK_RUNNING
            && current_state
                .compare_exchange(
                    TASK_RUNNING,
                    TASK_READY,
                    Ordering::AcqRel,
                    Ordering::Relaxed,
                )
                .is_err()
        {
            CHECKS_PASSED.store(false, Ordering::Release);
        }
    }
    if next_context != ROOT_CONTEXT {
        if TASK_STATES[next_context - 1]
            .compare_exchange(
                TASK_READY,
                TASK_RUNNING,
                Ordering::AcqRel,
                Ordering::Relaxed,
            )
            .is_err()
        {
            CHECKS_PASSED.store(false, Ordering::Release);
        }
    }
    ACTIVE_CONTEXT.store(next_context, Ordering::Relaxed);
    let next_stack = unsafe { context_slot(next_context).read() };
    unsafe {
        task_context_switch(context_slot(current_context), next_stack);
    }
}

extern "C" fn task_bootstrap() -> ! {
    match ACTIVE_CONTEXT.load(Ordering::Acquire) {
        TASK_A_CONTEXT => task_a(),
        TASK_B_CONTEXT => task_b(),
        _ => {
            CHECKS_PASSED.store(false, Ordering::Release);
            loop {
                unsafe {
                    core::arch::asm!("cli", "hlt", options(nomem, nostack));
                }
            }
        }
    }
}

extern "C" fn task_a() -> ! {
    loop {
        record_step(1);
        wait_one_tick();
        let next = if TRACE_LENGTH.load(Ordering::Acquire) == EXPECTED_TRACE.len() {
            TASK_STATES[TASK_A_CONTEXT - 1].store(TASK_EXITED, Ordering::Release);
            ROOT_CONTEXT
        } else {
            if !TASK_A_WAITED.swap(true, Ordering::AcqRel) {
                TASK_STATES[TASK_A_CONTEXT - 1].store(TASK_BLOCKED, Ordering::Release);
            }
            TASK_B_CONTEXT
        };
        unsafe {
            switch_to(next);
        }
    }
}

extern "C" fn task_b() -> ! {
    loop {
        record_step(2);
        wait_one_tick();
        if TASK_STATES[TASK_A_CONTEXT - 1]
            .compare_exchange(
                TASK_BLOCKED,
                TASK_READY,
                Ordering::AcqRel,
                Ordering::Relaxed,
            )
            .is_ok()
        {
            TASK_A_WOKEN.store(true, Ordering::Release);
        }
        unsafe {
            switch_to(TASK_A_CONTEXT);
        }
    }
}

fn wait_one_tick() {
    super::timer::wait_for_ticks(super::timer::ticks().saturating_add(1));
}

fn record_step(task_id: usize) {
    let stack_pointer: usize;
    unsafe {
        core::arch::asm!(
            "mov {}, rsp",
            out(reg) stack_pointer,
            options(nomem, nostack, preserves_flags)
        );
    }
    let context_index = ACTIVE_CONTEXT.load(Ordering::Relaxed);
    let task_index = context_index.saturating_sub(1);
    if task_index >= TASK_COUNT
        || stack_pointer < STACK_BASES[task_index].load(Ordering::Relaxed)
        || stack_pointer >= STACK_LIMITS[task_index].load(Ordering::Relaxed)
        || TASK_STATES[task_index].load(Ordering::Acquire) != TASK_RUNNING
    {
        CHECKS_PASSED.store(false, Ordering::Relaxed);
    }

    let index = TRACE_LENGTH.fetch_add(1, Ordering::AcqRel);
    if let Some(entry) = TRACE.get(index) {
        entry.store(task_id, Ordering::Relaxed);
    } else {
        CHECKS_PASSED.store(false, Ordering::Relaxed);
    }
}
