use core::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

const TASK_COUNT: usize = 2;
const STACK_PAGES: usize = 4;
const PAGE_SIZE: usize = 4096;
const EXPECTED_TRACE: [usize; 5] = [1, 2, 1, 2, 1];

static CURRENT_STACK_BASE: AtomicUsize = AtomicUsize::new(0);
static CURRENT_STACK_LIMIT: AtomicUsize = AtomicUsize::new(0);
static TRACE_LENGTH: AtomicUsize = AtomicUsize::new(0);
static TRACE: [AtomicUsize; EXPECTED_TRACE.len()] =
    [const { AtomicUsize::new(0) }; EXPECTED_TRACE.len()];
static STACK_CHECKS_PASSED: AtomicBool = AtomicBool::new(true);

struct Task {
    stack_base: usize,
    stack_top: usize,
    remaining_steps: usize,
    step: extern "C" fn(),
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
    STACK_CHECKS_PASSED.store(true, Ordering::Relaxed);
    let mut tasks = [
        Task {
            stack_base: stacks[0].expect("first scheduler stack is allocated"),
            stack_top: stacks[0].expect("first scheduler stack is allocated")
                + STACK_PAGES * PAGE_SIZE,
            remaining_steps: 3,
            step: task_a_step,
        },
        Task {
            stack_base: stacks[1].expect("second scheduler stack is allocated"),
            stack_top: stacks[1].expect("second scheduler stack is allocated")
                + STACK_PAGES * PAGE_SIZE,
            remaining_steps: 2,
            step: task_b_step,
        },
    ];

    let mut cursor = 0;
    while tasks.iter().any(|task| task.remaining_steps > 0) {
        let task = &mut tasks[cursor];
        if task.remaining_steps > 0 {
            CURRENT_STACK_BASE.store(task.stack_base, Ordering::Relaxed);
            CURRENT_STACK_LIMIT.store(task.stack_top, Ordering::Relaxed);
            super::task::run_on_stack(task.stack_top, task.step);
            task.remaining_steps -= 1;
            super::timer::wait_for_ticks(super::timer::ticks().saturating_add(1));
        }
        cursor = (cursor + 1) % TASK_COUNT;
    }

    let trace_length = TRACE_LENGTH.load(Ordering::Acquire);
    let valid_trace = trace_length == EXPECTED_TRACE.len()
        && EXPECTED_TRACE
            .iter()
            .enumerate()
            .all(|(index, expected)| TRACE[index].load(Ordering::Relaxed) == *expected);
    let stack_checks = STACK_CHECKS_PASSED.load(Ordering::Acquire);
    for base in stacks.into_iter().flatten() {
        release_stack(base)?;
    }
    if !valid_trace {
        return Err("cooperative scheduler did not execute the expected round-robin trace");
    }
    if !stack_checks {
        return Err("a scheduled task did not run on its own kernel stack");
    }
    Ok(trace_length)
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

fn record_step(task_id: usize) {
    let stack_pointer: usize;
    unsafe {
        core::arch::asm!(
            "mov {}, rsp",
            out(reg) stack_pointer,
            options(nomem, nostack, preserves_flags)
        );
    }
    if stack_pointer < CURRENT_STACK_BASE.load(Ordering::Relaxed)
        || stack_pointer >= CURRENT_STACK_LIMIT.load(Ordering::Relaxed)
    {
        STACK_CHECKS_PASSED.store(false, Ordering::Relaxed);
    }
    let index = TRACE_LENGTH.fetch_add(1, Ordering::AcqRel);
    if let Some(entry) = TRACE.get(index) {
        entry.store(task_id, Ordering::Relaxed);
    } else {
        STACK_CHECKS_PASSED.store(false, Ordering::Relaxed);
    }
}

extern "C" fn task_a_step() {
    record_step(1);
}

extern "C" fn task_b_step() {
    record_step(2);
}
