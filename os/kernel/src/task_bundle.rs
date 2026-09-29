use super::syscall::TaskRunResult;
use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::fmt;
use serde::{
    Deserialize, Deserializer,
    de::{Error as _, MapAccess, SeqAccess, Visitor},
};
use serde_json::Value;

const MAX_MANIFEST_SIZE: usize = 4096;
/// Ring-3 MicroPython interpreter built by os/micropython/build.sh. It is part
/// of the kernel image, so `micropython` tasks trust it like kernel code; the
/// task's own script is still digest-checked from its manifest.
static MICROPYTHON_RUNTIME: &[u8] = include_bytes!("../../micropython/MPY.ELF");
const MAX_TASK_FILES: usize = 14;
const MAX_WORKFLOW_BLOCKS: usize = 8;
const MAX_WORKFLOW_EVENTS: usize = MAX_WORKFLOW_BLOCKS * 3;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum BlockStatus {
    Waiting,
    Ready,
    Succeeded,
    Failed,
    Skipped,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TaskRuntime {
    MicroPython,
    Elf,
}

impl TaskRuntime {
    fn entrypoint_role(self) -> &'static str {
        match self {
            Self::MicroPython => "python",
            Self::Elf => "elf",
        }
    }
}

/// What the dispatcher needs from a validated task manifest. The entrypoint
/// digest lets the runner re-check the exact bytes it is about to execute.
pub(crate) struct TaskManifestSummary {
    pub(crate) runtime: TaskRuntime,
    pub(crate) entrypoint: String,
    pub(crate) entrypoint_size: usize,
    pub(crate) entrypoint_sha256: [u8; 32],
    pub(crate) network_requested: bool,
    pub(crate) runtime_seconds: u64,
}

#[derive(Clone, Copy)]
struct WorkflowEvent {
    block_index: usize,
    status: BlockStatus,
}

pub(crate) struct WorkflowDispatcher {
    manifest: Value,
    block_count: usize,
    plan_order: [usize; MAX_WORKFLOW_BLOCKS],
    statuses: [BlockStatus; MAX_WORKFLOW_BLOCKS],
    events: [Option<WorkflowEvent>; MAX_WORKFLOW_EVENTS],
    event_count: usize,
    stop_on_failure: bool,
}

impl WorkflowDispatcher {
    pub(crate) fn prepare(
        input: &[u8],
        available_task_manifests: &[&str],
        available_files: &[&str],
    ) -> Result<Self, &'static str> {
        validate_workflow_manifest(input, available_task_manifests, available_files)?;
        let manifest = parse_manifest(input)?;
        let blocks = manifest
            .get("blocks")
            .and_then(Value::as_array)
            .ok_or("workflow blocks must be an array")?;
        let block_count = blocks.len();
        let mut plan_order = [0; MAX_WORKFLOW_BLOCKS];
        let mut statuses = [BlockStatus::Waiting; MAX_WORKFLOW_BLOCKS];
        let mut planned = [false; MAX_WORKFLOW_BLOCKS];
        let mut plan_length = 0;

        while plan_length < block_count {
            let mut made_progress = false;
            for index in 0..block_count {
                if planned[index] {
                    continue;
                }
                let dependencies = blocks[index]
                    .get("dependsOn")
                    .and_then(Value::as_array)
                    .ok_or("workflow dependencies must be an array")?;
                let ready = dependencies.iter().all(|dependency| {
                    let Some(dependency) = dependency.as_str() else {
                        return false;
                    };
                    blocks
                        .iter()
                        .position(|block| {
                            block.get("blockId").and_then(Value::as_str) == Some(dependency)
                        })
                        .is_some_and(|dependency_index| planned[dependency_index])
                });
                if ready {
                    planned[index] = true;
                    plan_order[plan_length] = index;
                    plan_length += 1;
                    made_progress = true;
                }
            }
            if !made_progress {
                return Err("workflow plan could not resolve its dependency order");
            }
        }

        for index in 0..block_count {
            let dependencies = blocks[index]
                .get("dependsOn")
                .and_then(Value::as_array)
                .ok_or("workflow dependencies must be an array")?;
            statuses[index] = if dependencies.is_empty() {
                BlockStatus::Ready
            } else {
                BlockStatus::Waiting
            };
        }
        let stop_on_failure = manifest
            .get("failurePolicy")
            .and_then(Value::as_str)
            .ok_or("workflow failure policy must be a string")?
            == "stop";
        let mut dispatcher = Self {
            manifest,
            block_count,
            plan_order,
            statuses,
            events: [None; MAX_WORKFLOW_EVENTS],
            event_count: 0,
            stop_on_failure,
        };
        for index in 0..block_count {
            dispatcher.record_event(index)?;
        }
        Ok(dispatcher)
    }

    pub(crate) fn block_id(&self, index: usize) -> Option<&str> {
        self.manifest
            .get("blocks")?
            .as_array()?
            .get(index)?
            .get("blockId")?
            .as_str()
    }

    pub(crate) fn planned_block_id(&self, position: usize) -> Option<&str> {
        let index = *self.plan_order.get(position)?;
        self.block_id(index)
    }

    pub(crate) fn next_ready_block(&self) -> Option<&str> {
        (0..self.block_count)
            .map(|position| self.plan_order[position])
            .find(|index| self.statuses[*index] == BlockStatus::Ready)
            .and_then(|index| self.block_id(index))
    }

    pub(crate) fn status(&self, block_id: &str) -> Option<BlockStatus> {
        (0..self.block_count)
            .find(|index| self.block_id(*index) == Some(block_id))
            .map(|index| self.statuses[index])
    }

    fn block_index(&self, block_id: &str) -> Option<usize> {
        (0..self.block_count).find(|index| self.block_id(*index) == Some(block_id))
    }

    fn block_field(&self, index: usize, field: &str) -> Option<&Value> {
        self.manifest
            .get("blocks")?
            .as_array()?
            .get(index)?
            .get(field)
    }

    pub(crate) fn event_count(&self) -> usize {
        self.event_count
    }

    pub(crate) fn event_at(&self, position: usize) -> Option<(&str, BlockStatus)> {
        let event = self.events.get(position)?.as_ref()?;
        Some((self.block_id(event.block_index)?, event.status))
    }

    pub(crate) fn record_runtime_result(
        &mut self,
        block_id: &str,
        succeeded: bool,
    ) -> Result<(), &'static str> {
        let index = (0..self.block_count)
            .find(|index| self.block_id(*index) == Some(block_id))
            .ok_or("workflow result references an unknown block")?;
        if self.statuses[index] != BlockStatus::Ready {
            return Err("workflow result references a block that is not ready");
        }

        self.statuses[index] = if succeeded {
            BlockStatus::Succeeded
        } else {
            BlockStatus::Failed
        };
        self.record_event(index)?;
        if !succeeded && self.stop_on_failure {
            for pending in 0..self.block_count {
                if matches!(
                    self.statuses[pending],
                    BlockStatus::Ready | BlockStatus::Waiting
                ) {
                    self.statuses[pending] = BlockStatus::Skipped;
                    self.record_event(pending)?;
                }
            }
            return Ok(());
        }
        self.refresh_waiting()
    }

    fn refresh_waiting(&mut self) -> Result<(), &'static str> {
        loop {
            let mut changed = false;
            for index in 0..self.block_count {
                if self.statuses[index] != BlockStatus::Waiting {
                    continue;
                }
                let block = self
                    .manifest
                    .get("blocks")
                    .and_then(Value::as_array)
                    .and_then(|blocks| blocks.get(index))
                    .ok_or("workflow block state is invalid")?;
                let dependencies = block
                    .get("dependsOn")
                    .and_then(Value::as_array)
                    .ok_or("workflow dependencies must be an array")?;
                let mut dependency_failed = false;
                let mut dependencies_succeeded = true;
                for dependency in dependencies {
                    let dependency = dependency
                        .as_str()
                        .ok_or("workflow dependency must be a block ID")?;
                    let dependency_index = (0..self.block_count)
                        .find(|dependency_index| {
                            self.block_id(*dependency_index) == Some(dependency)
                        })
                        .ok_or("workflow dependency references an unknown block")?;
                    dependency_failed |= matches!(
                        self.statuses[dependency_index],
                        BlockStatus::Failed | BlockStatus::Skipped
                    );
                    dependencies_succeeded &=
                        self.statuses[dependency_index] == BlockStatus::Succeeded;
                }
                if dependency_failed {
                    self.statuses[index] = BlockStatus::Skipped;
                    self.record_event(index)?;
                    changed = true;
                } else if dependencies_succeeded {
                    self.statuses[index] = BlockStatus::Ready;
                    self.record_event(index)?;
                    changed = true;
                }
            }
            if !changed {
                return Ok(());
            }
        }
    }

    fn record_event(&mut self, index: usize) -> Result<(), &'static str> {
        let event = WorkflowEvent {
            block_index: index,
            status: self.statuses[index],
        };
        let slot = self
            .events
            .get_mut(self.event_count)
            .ok_or("workflow event log capacity was exceeded")?;
        *slot = Some(event);
        self.event_count += 1;
        Ok(())
    }
}

pub(crate) fn verify_dispatcher_smoke(
    workflow_manifest: &[u8],
    available_task_manifests: &[&str],
    available_files: &[&str],
) -> Result<usize, &'static str> {
    let mut dispatcher =
        WorkflowDispatcher::prepare(workflow_manifest, available_task_manifests, available_files)?;
    if dispatcher.planned_block_id(0) != Some("inspect-input")
        || dispatcher.planned_block_id(1) != Some("summarize-input")
        || dispatcher.status("inspect-input") != Some(BlockStatus::Ready)
        || dispatcher.status("summarize-input") != Some(BlockStatus::Waiting)
        || dispatcher.event_at(0) != Some(("inspect-input", BlockStatus::Ready))
        || dispatcher.event_at(1) != Some(("summarize-input", BlockStatus::Waiting))
        || dispatcher.next_ready_block() != Some("inspect-input")
    {
        return Err("workflow dispatcher produced an unexpected initial plan");
    }
    dispatcher.record_runtime_result("inspect-input", true)?;
    if dispatcher.status("summarize-input") != Some(BlockStatus::Ready)
        || dispatcher.next_ready_block() != Some("summarize-input")
    {
        return Err("workflow dispatcher did not unblock a dependent task");
    }
    dispatcher.record_runtime_result("summarize-input", true)?;
    if dispatcher.status("inspect-input") != Some(BlockStatus::Succeeded)
        || dispatcher.status("summarize-input") != Some(BlockStatus::Succeeded)
    {
        return Err("workflow dispatcher did not record simulated successful outcomes");
    }
    let success_events = dispatcher.event_count();

    const STOP_ON_FAILURE: &[u8] = br#"{"schemaVersion":"nosfs.workflow.v1","workflowId":"stop-check","failurePolicy":"stop","blocks":[{"blockId":"first","taskManifest":"TASK.MF","dependsOn":[],"inputFiles":[],"outputFiles":[]},{"blockId":"second","taskManifest":"TASK.MF","dependsOn":[],"inputFiles":[],"outputFiles":[]}]}"#;
    let mut stop_dispatcher =
        WorkflowDispatcher::prepare(STOP_ON_FAILURE, available_task_manifests, available_files)?;
    stop_dispatcher.record_runtime_result("first", false)?;
    if stop_dispatcher.status("second") != Some(BlockStatus::Skipped)
        || stop_dispatcher.next_ready_block().is_some()
    {
        return Err("stop-on-failure policy did not skip remaining ready tasks");
    }

    const CONTINUE_ON_FAILURE: &[u8] = br#"{"schemaVersion":"nosfs.workflow.v1","workflowId":"continue-check","failurePolicy":"continue","blocks":[{"blockId":"first","taskManifest":"TASK.MF","dependsOn":[],"inputFiles":[],"outputFiles":[]},{"blockId":"dependent","taskManifest":"TASK.MF","dependsOn":["first"],"inputFiles":[],"outputFiles":[]},{"blockId":"independent","taskManifest":"TASK.MF","dependsOn":[],"inputFiles":[],"outputFiles":[]}]}"#;
    let mut continue_dispatcher = WorkflowDispatcher::prepare(
        CONTINUE_ON_FAILURE,
        available_task_manifests,
        available_files,
    )?;
    continue_dispatcher.record_runtime_result("first", false)?;
    if continue_dispatcher.status("dependent") != Some(BlockStatus::Skipped)
        || continue_dispatcher.status("independent") != Some(BlockStatus::Ready)
        || continue_dispatcher.next_ready_block() != Some("independent")
    {
        return Err("continue-on-failure policy did not preserve independent work");
    }
    Ok(success_events)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum BlockOutcome {
    NotRun,
    Exited(u64),
    /// The block was refused before running or stopped without a usable
    /// exit (fault, runtime limit, missing declared output).
    Refused(&'static str),
}

/// What a running task is allowed to do. `entrypoint` is what syscall 14
/// reports, so the MicroPython runtime knows which script to run.
pub(crate) struct TaskGrant<'a> {
    pub(crate) readable: &'a [&'a str],
    pub(crate) writable: &'a [&'a str],
    pub(crate) entrypoint: &'a str,
    pub(crate) runtime_seconds: u64,
}

pub(crate) struct WorkflowRun {
    dispatcher: WorkflowDispatcher,
    outcomes: [BlockOutcome; MAX_WORKFLOW_BLOCKS],
}

impl WorkflowRun {
    fn outcome(&self, block_id: &str) -> Option<(BlockOutcome, BlockStatus)> {
        let index = self.dispatcher.block_index(block_id)?;
        Some((self.outcomes[index], self.dispatcher.statuses[index]))
    }

    fn executed_count(&self) -> usize {
        self.outcomes
            .iter()
            .filter(|outcome| matches!(outcome, BlockOutcome::Exited(_)))
            .count()
    }
}

/// Runs every block in dependency order. A block succeeds only when its ELF
/// entrypoint exits with status 0 after writing every declared output file.
/// Each block's manifest and file digests are re-validated immediately before
/// it runs, the bytes handed to the loader are hashed again, and tasks that
/// need an unavailable runtime or request network access are refused
/// (recorded as failed) instead of run. `run_elf` receives the image and the
/// block's grant: its declared input files are the only files it may read,
/// its declared output files the only ones it may write, and the manifest's
/// `runtimeSeconds` its time limit.
pub(crate) fn execute_workflow(
    workflow_manifest: &[u8],
    available_task_manifests: &[&str],
    available_files: &[&str],
    mut read_file: impl FnMut(&str, &mut [u8]) -> Result<usize, &'static str>,
    mut run_elf: impl FnMut(&[u8], &TaskGrant) -> Result<TaskRunResult, &'static str>,
) -> Result<WorkflowRun, &'static str> {
    let mut dispatcher =
        WorkflowDispatcher::prepare(workflow_manifest, available_task_manifests, available_files)?;
    let mut outcomes = [BlockOutcome::NotRun; MAX_WORKFLOW_BLOCKS];
    while let Some(block_id) = dispatcher.next_ready_block() {
        let block_id = String::from(block_id);
        let index = dispatcher
            .block_index(&block_id)
            .ok_or("workflow ready block has no index")?;
        let task_manifest = String::from(
            dispatcher
                .block_field(index, "taskManifest")
                .and_then(Value::as_str)
                .ok_or("workflow block task manifest must be a string")?,
        );
        let input_files = block_file_names(&dispatcher, index, "inputFiles")?;
        let output_files = block_file_names(&dispatcher, index, "outputFiles")?;
        let input_names: Vec<&str> = input_files.iter().map(String::as_str).collect();
        let output_names: Vec<&str> = output_files.iter().map(String::as_str).collect();
        outcomes[index] = match run_block(
            &task_manifest,
            &input_names,
            &output_names,
            &mut read_file,
            &mut run_elf,
        ) {
            Ok(exit_code) => BlockOutcome::Exited(exit_code),
            Err(reason) => BlockOutcome::Refused(reason),
        };
        dispatcher.record_runtime_result(&block_id, outcomes[index] == BlockOutcome::Exited(0))?;
    }
    Ok(WorkflowRun {
        dispatcher,
        outcomes,
    })
}

fn block_file_names(
    dispatcher: &WorkflowDispatcher,
    index: usize,
    field: &str,
) -> Result<Vec<String>, &'static str> {
    let mut names = Vec::new();
    for file in dispatcher
        .block_field(index, field)
        .and_then(Value::as_array)
        .ok_or("workflow file references must be arrays")?
    {
        names.push(String::from(
            file.as_str()
                .ok_or("workflow file reference must be a filename")?,
        ));
    }
    Ok(names)
}

fn run_block(
    task_manifest: &str,
    input_files: &[&str],
    output_files: &[&str],
    read_file: &mut impl FnMut(&str, &mut [u8]) -> Result<usize, &'static str>,
    run_elf: &mut impl FnMut(&[u8], &TaskGrant) -> Result<TaskRunResult, &'static str>,
) -> Result<u64, &'static str> {
    let mut manifest = [0; MAX_MANIFEST_SIZE];
    let length = read_file(task_manifest, &mut manifest)?;
    let summary = validate_task_manifest(&manifest[..length], &mut *read_file)?;
    if summary.network_requested {
        return Err("task requests network access, which task execution does not grant");
    }
    let mut readable = Vec::from(input_files);
    let mut image = Vec::new();
    let image: &[u8] = match summary.runtime {
        TaskRuntime::Elf => {
            image
                .try_reserve_exact(summary.entrypoint_size)
                .map_err(|_| "not enough kernel memory to load a task entrypoint")?;
            image.resize(summary.entrypoint_size, 0);
            let image_length = read_file(&summary.entrypoint, &mut image)?;
            if image_length != image.len() || sha256(&image) != summary.entrypoint_sha256 {
                return Err("task entrypoint changed after validation");
            }
            &image
        }
        TaskRuntime::MicroPython => {
            if !readable.contains(&summary.entrypoint.as_str()) {
                readable.push(&summary.entrypoint);
            }
            MICROPYTHON_RUNTIME
        }
    };
    let result = run_elf(
        image,
        &TaskGrant {
            readable: &readable,
            writable: output_files,
            entrypoint: &summary.entrypoint,
            runtime_seconds: summary.runtime_seconds,
        },
    )?;
    if result.exit_code == 0 && !result.outputs_written {
        return Err("task exited without writing its declared output files");
    }
    Ok(result.exit_code)
}

/// Builds an ELF-runtime task manifest whose single file is the entrypoint.
pub(crate) fn elf_task_manifest(
    task_id: &str,
    entrypoint: &str,
    image: &[u8],
    dns: bool,
    runtime_seconds: u64,
) -> String {
    single_file_manifest(
        task_id,
        "elf",
        entrypoint,
        "elf",
        image,
        dns,
        runtime_seconds,
    )
}

fn single_file_manifest(
    task_id: &str,
    runtime: &str,
    entrypoint: &str,
    role: &str,
    image: &[u8],
    dns: bool,
    runtime_seconds: u64,
) -> String {
    let digest = sha256(image);
    let mut hex = String::with_capacity(64);
    for byte in digest {
        hex.push(hex_digit(byte >> 4) as char);
        hex.push(hex_digit(byte & 0x0f) as char);
    }
    format!(
        r#"{{"schemaVersion":"nosfs.task-bundle.v1","taskId":"{task_id}","runtime":"{runtime}","entrypoint":"{entrypoint}","files":[{{"name":"{entrypoint}","role":"{role}","sizeBytes":{size},"sha256":"{hex}"}}],"capabilities":{{"network":{{"dns":{dns},"udpDestinations":[],"tcpDestinations":[],"tlsHosts":[]}}}},"limits":{{"memoryBytes":65536,"runtimeSeconds":{runtime_seconds}}}}}"#,
        size = image.len(),
    )
}

/// Compares a synthetic sample to its reference in MicroPython, mirroring
/// remission_core.py's position-7 G->A demo; raises if the result is wrong.
const DNA_COMPARE_SCRIPT: &[u8] = b"reference = 'ACGTACGTACGT'
sample = 'ACGTACATACGT'
bits = {'A': '00', 'C': '01', 'G': '10', 'T': '11'}
diff = [i + 1 for i in range(len(reference)) if reference[i] != sample[i]]
if diff != [7] or bits[reference[6]] + bits[sample[6]] != '1000':
    raise AssertionError('unexpected comparison')
print('MicroPython task: position', diff[0], reference[6], '->', sample[6])
";

/// Task manifests of the embedded bundles (os/tasks, generated by
/// build_task_bundles.py); the kernel reads them through the overlay so they
/// need no directory slot.
const REMISSION_TASK: &[u8] = include_bytes!("../../tasks/remission/RMTASK.JSON");
const RESEARCH_TASK: &[u8] = include_bytes!("../../tasks/research/RSTASK.JSON");

const FAIL_SCRIPT: &[u8] = b"raise ValueError('expected task failure')\n";

pub(crate) struct WorkflowExecutionReport {
    pub(crate) executed: usize,
    pub(crate) remission_result_bytes: usize,
    pub(crate) research_result_bytes: usize,
    pub(crate) host_research: HostResearch,
}

struct Overlay {
    files: Vec<(&'static str, Vec<u8>)>,
}

impl Overlay {
    fn add_python_task(
        &mut self,
        manifest: &'static str,
        script_name: &'static str,
        script: &[u8],
    ) {
        let task_id = manifest
            .split('.')
            .next()
            .unwrap_or("task")
            .to_ascii_lowercase();
        let manifest_text = single_file_manifest(
            &task_id,
            "micropython",
            script_name,
            "python",
            script,
            false,
            5,
        );
        self.files.push((manifest, manifest_text.into_bytes()));
        self.files.push((script_name, Vec::from(script)));
    }

    fn add_elf_task(
        &mut self,
        manifest: &'static str,
        entrypoint: &'static str,
        image: Vec<u8>,
        dns: bool,
        runtime_seconds: u64,
    ) {
        let task_id = manifest
            .split('.')
            .next()
            .unwrap_or("task")
            .to_ascii_lowercase();
        let manifest_text = elf_task_manifest(&task_id, entrypoint, &image, dns, runtime_seconds);
        self.files.push((manifest, manifest_text.into_bytes()));
        self.files.push((entrypoint, image));
    }

    fn read(&self, name: &str, output: &mut [u8]) -> Option<Result<usize, &'static str>> {
        let (_, contents) = self.files.iter().find(|(file, _)| *file == name)?;
        Some(
            output
                .get_mut(..contents.len())
                .map(|slot| {
                    slot.copy_from_slice(contents);
                    contents.len()
                })
                .ok_or("overlay file does not fit the read buffer"),
        )
    }
}

fn expect_outcomes(
    run: &WorkflowRun,
    expected: &[(&str, BlockOutcome, BlockStatus)],
    error: &'static str,
) -> Result<(), &'static str> {
    for (block, outcome, status) in expected {
        let actual = run.outcome(block);
        if actual != Some((*outcome, *status)) {
            use core::fmt::Write;
            let _ = writeln!(
                crate::Serial,
                "workflow block {block}: expected {outcome:?}/{status:?}, got {actual:?}"
            );
            return Err(error);
        }
    }
    Ok(())
}

/// Executes the stored ELF workflow, a mixed workflow whose blocks must
/// succeed, fail and be refused for the right reasons, and an output-file
/// workflow that also checks write permissions and the runtime limit.
/// Programs and manifests other than the stored workflow live in an
/// in-memory overlay so they do not use root-directory slots; Python scripts
/// are also written to disk for the run because the interpreter reads its
/// script through syscall 2.
pub(crate) fn verify_workflow_execution(
    elf_workflow: &[u8],
    elf_task_manifest_name: &str,
    python_task_manifest_name: &str,
    input_file_name: &'static str,
    mut read_disk: impl FnMut(&str, &mut [u8]) -> Result<usize, &'static str>,
    mut write_disk: impl FnMut(&str, &[u8]) -> Result<(), &'static str>,
    mut delete_disk: impl FnMut(&str) -> Result<bool, &'static str>,
    mut run_elf: impl FnMut(&[u8], &TaskGrant) -> Result<TaskRunResult, &'static str>,
) -> Result<WorkflowExecutionReport, &'static str> {
    use BlockOutcome::{Exited, NotRun, Refused};
    use BlockStatus::{Failed, Skipped, Succeeded};

    let stored = execute_workflow(
        elf_workflow,
        &[elf_task_manifest_name],
        &[input_file_name],
        &mut read_disk,
        &mut run_elf,
    )?;
    expect_outcomes(
        &stored,
        &[
            ("inspect", Exited(0), Succeeded),
            ("inspect-again", Exited(0), Succeeded),
        ],
        "stored ELF workflow block did not run to a successful exit",
    )?;

    let echo = super::task_programs::copy_program(input_file_name, None);
    let mut tampered = echo.clone();
    let last = tampered.len() - 1;
    tampered[last] ^= 0xff;
    let mut overlay = Overlay { files: Vec::new() };
    overlay.add_elf_task("NET.MF", "ECHO.ELF", echo.clone(), true, 5);
    let tampered_manifest = elf_task_manifest("tampered", "ECHO.ELF", &tampered, false, 5);
    overlay
        .files
        .push(("BAD.MF", tampered_manifest.into_bytes()));
    overlay.add_elf_task(
        "COPY.MF",
        "COPY.ELF",
        super::task_programs::copy_program(input_file_name, Some("COPY.OUT")),
        false,
        5,
    );
    overlay.add_elf_task(
        "CHECK.MF",
        "CHECK.ELF",
        super::task_programs::copy_program("COPY.OUT", None),
        false,
        5,
    );
    overlay.add_elf_task(
        "SPIN.MF",
        "SPIN.ELF",
        super::task_programs::spin_program(),
        false,
        1,
    );
    overlay.add_python_task("DNA.MF", "DNA.PY", DNA_COMPARE_SCRIPT);
    overlay.add_python_task("FAIL.MF", "FAIL.PY", FAIL_SCRIPT);
    overlay
        .files
        .push(("RMTASK.JSON", Vec::from(REMISSION_TASK)));
    overlay
        .files
        .push(("RSTASK.JSON", Vec::from(RESEARCH_TASK)));
    // Host-provided research input is only known at run time, so its
    // manifest pins the script alone; the input is a declared data file.
    overlay.files.push((
        HOST_RESEARCH_MANIFEST,
        single_file_manifest(
            "research-host",
            "micropython",
            RESEARCH_BUNDLE.entrypoint.0,
            "python",
            RESEARCH_BUNDLE.entrypoint.1,
            false,
            30,
        )
        .into_bytes(),
    ));
    let mut read_file = |name: &str, output: &mut [u8]| {
        overlay
            .read(name, output)
            .unwrap_or_else(|| read_disk(name, output))
    };

    let mixed_workflow = format!(
        r#"{{"schemaVersion":"nosfs.workflow.v1","workflowId":"mixed-check","failurePolicy":"continue","blocks":[{{"blockId":"python-task","taskManifest":"{python}","dependsOn":[],"inputFiles":["{input}"],"outputFiles":[]}},{{"blockId":"tampered","taskManifest":"BAD.MF","dependsOn":[],"inputFiles":["{input}"],"outputFiles":[]}},{{"blockId":"after-tampered","taskManifest":"{elf}","dependsOn":["tampered"],"inputFiles":["{input}"],"outputFiles":[]}},{{"blockId":"undeclared-input","taskManifest":"{elf}","dependsOn":[],"inputFiles":[],"outputFiles":[]}},{{"blockId":"network-task","taskManifest":"NET.MF","dependsOn":[],"inputFiles":["{input}"],"outputFiles":[]}},{{"blockId":"independent","taskManifest":"{elf}","dependsOn":[],"inputFiles":["{input}"],"outputFiles":[]}}]}}"#,
        python = python_task_manifest_name,
        elf = elf_task_manifest_name,
        input = input_file_name,
    );
    let mixed = execute_workflow(
        mixed_workflow.as_bytes(),
        &[
            python_task_manifest_name,
            elf_task_manifest_name,
            "BAD.MF",
            "NET.MF",
        ],
        &[input_file_name],
        &mut read_file,
        &mut run_elf,
    )?;
    expect_outcomes(
        &mixed,
        &[
            ("python-task", Exited(0), Succeeded),
            (
                "tampered",
                Refused("task bundle file SHA-256 does not match its manifest"),
                Failed,
            ),
            ("after-tampered", NotRun, Skipped),
            ("undeclared-input", Exited(1), Failed),
            (
                "network-task",
                Refused("task requests network access, which task execution does not grant"),
                Failed,
            ),
            ("independent", Exited(0), Succeeded),
        ],
        "mixed workflow block did not reach its expected outcome",
    )?;

    let output_workflow = format!(
        r#"{{"schemaVersion":"nosfs.workflow.v1","workflowId":"output-check","failurePolicy":"continue","blocks":[{{"blockId":"copy","taskManifest":"COPY.MF","dependsOn":[],"inputFiles":["{input}"],"outputFiles":["COPY.OUT"]}},{{"blockId":"check-copy","taskManifest":"CHECK.MF","dependsOn":["copy"],"inputFiles":["COPY.OUT"],"outputFiles":[]}},{{"blockId":"undeclared-write","taskManifest":"COPY.MF","dependsOn":["check-copy"],"inputFiles":["{input}"],"outputFiles":["OTHER.OUT"]}},{{"blockId":"missing-output","taskManifest":"{elf}","dependsOn":[],"inputFiles":["{input}"],"outputFiles":["NONE.OUT"]}},{{"blockId":"spin","taskManifest":"SPIN.MF","dependsOn":[],"inputFiles":[],"outputFiles":[]}},{{"blockId":"python-dna","taskManifest":"DNA.MF","dependsOn":[],"inputFiles":[],"outputFiles":[]}},{{"blockId":"python-raise","taskManifest":"FAIL.MF","dependsOn":[],"inputFiles":[],"outputFiles":[]}}]}}"#,
        elf = elf_task_manifest_name,
        input = input_file_name,
    );
    write_disk("DNA.PY", DNA_COMPARE_SCRIPT)?;
    write_disk("FAIL.PY", FAIL_SCRIPT)?;
    let output_run = execute_workflow(
        output_workflow.as_bytes(),
        &[
            elf_task_manifest_name,
            "COPY.MF",
            "CHECK.MF",
            "SPIN.MF",
            "DNA.MF",
            "FAIL.MF",
        ],
        &[input_file_name],
        &mut read_file,
        &mut run_elf,
    )?;
    expect_outcomes(
        &output_run,
        &[
            ("copy", Exited(0), Succeeded),
            ("check-copy", Exited(0), Succeeded),
            ("undeclared-write", Exited(1), Failed),
            (
                "missing-output",
                Refused("task exited without writing its declared output files"),
                Failed,
            ),
            (
                "spin",
                Refused("ring-3 task exceeded its runtime limit"),
                Failed,
            ),
            ("python-dna", Exited(0), Succeeded),
            ("python-raise", Exited(1), Failed),
        ],
        "output workflow block did not reach its expected outcome",
    )?;
    let mut input = [0; 1024];
    let mut copied = [0; 1024];
    let input_length = read_file(input_file_name, &mut input)?;
    let copied_length = read_file("COPY.OUT", &mut copied)?;
    if input[..input_length] != copied[..copied_length] {
        return Err("task output file does not match the copied input");
    }
    // Keep root-directory slots free for the remission run and the next boot.
    for transient in ["DNA.PY", "FAIL.PY", "COPY.OUT"] {
        if !delete_disk(transient)? {
            return Err("transient workflow file was missing before deletion");
        }
    }

    // The real bundles from os/tasks, each with its own manifest, workflow,
    // declared input and declared .OUT output, run by the MicroPython runtime.
    let (remission_runs, remission_result_bytes) = run_embedded_bundle(
        &REMISSION_BUNDLE,
        &mut read_file,
        &mut write_disk,
        &mut delete_disk,
        &mut run_elf,
    )?;
    let (research_runs, research_result_bytes) = run_embedded_bundle(
        &RESEARCH_BUNDLE,
        &mut read_file,
        &mut write_disk,
        &mut delete_disk,
        &mut run_elf,
    )?;
    let host_research = run_host_research(
        &mut read_file,
        &mut write_disk,
        &mut delete_disk,
        &mut run_elf,
    )?;

    Ok(WorkflowExecutionReport {
        executed: stored.executed_count()
            + mixed.executed_count()
            + output_run.executed_count()
            + remission_runs
            + research_runs,
        remission_result_bytes,
        research_result_bytes,
        host_research,
    })
}

/// Name the host runner uses to place fetched research records on the disk
/// (`cargo run -- research RESEARCH.JSON`), and the name of the ranking the
/// kernel leaves for the runner to read back after QEMU exits.
const HOST_RESEARCH_INPUT: &str = "HOSTIN.JSON";
const HOST_RESEARCH_OUTPUT: &str = "HOSTOUT.JSON";
const HOST_RESEARCH_MANIFEST: &str = "RSHOST.MF";
const HOST_RESEARCH_WORKFLOW: &[u8] = br#"{"schemaVersion":"nosfs.workflow.v1","workflowId":"research-host","failurePolicy":"stop","blocks":[{"blockId":"research-host","taskManifest":"RSHOST.MF","dependsOn":[],"inputFiles":["RESEARCH.JSON"],"outputFiles":["RANKED.OUT"]}]}"#;

/// Outcome of analyzing host-provided research records, if any were given.
pub(crate) enum HostResearch {
    NotProvided,
    Ranked(usize),
    Rejected(&'static str),
}

/// If the runner placed HOSTIN.JSON on the disk, runs the research task on
/// it and saves the ranking as HOSTOUT.JSON. Bad host data is reported, not
/// fatal: the records are untrusted input, and the boot checks go on.
fn run_host_research(
    read_file: &mut impl FnMut(&str, &mut [u8]) -> Result<usize, &'static str>,
    write_disk: &mut impl FnMut(&str, &[u8]) -> Result<(), &'static str>,
    delete_disk: &mut impl FnMut(&str) -> Result<bool, &'static str>,
    run_elf: &mut impl FnMut(&[u8], &TaskGrant) -> Result<TaskRunResult, &'static str>,
) -> Result<HostResearch, &'static str> {
    let mut input = Vec::new();
    input.resize(64 * 1024, 0);
    let length = match read_file(HOST_RESEARCH_INPUT, &mut input) {
        Ok(length) => length,
        Err("filesystem file does not exist") => return Ok(HostResearch::NotProvided),
        Err(error) => {
            delete_disk(HOST_RESEARCH_INPUT)?;
            return Ok(HostResearch::Rejected(error));
        }
    };
    write_disk(RESEARCH_BUNDLE.entrypoint.0, RESEARCH_BUNDLE.entrypoint.1)?;
    write_disk(RESEARCH_BUNDLE.input.0, &input[..length])?;
    let run = execute_workflow(
        HOST_RESEARCH_WORKFLOW,
        &[HOST_RESEARCH_MANIFEST],
        &[RESEARCH_BUNDLE.input.0],
        &mut *read_file,
        &mut *run_elf,
    )?;
    let outcome = match run.outcome("research-host") {
        Some((BlockOutcome::Exited(0), BlockStatus::Succeeded)) => {
            let mut output = Vec::new();
            output.resize(16 * 1024, 0);
            let output_length = read_file(RESEARCH_BUNDLE.output, &mut output)?;
            write_disk(HOST_RESEARCH_OUTPUT, &output[..output_length])?;
            HostResearch::Ranked(output_length)
        }
        Some((BlockOutcome::Refused(reason), _)) => HostResearch::Rejected(reason),
        _ => HostResearch::Rejected("research task exited with a failure status"),
    };
    for transient in [
        RESEARCH_BUNDLE.entrypoint.0,
        RESEARCH_BUNDLE.input.0,
        RESEARCH_BUNDLE.output,
        HOST_RESEARCH_INPUT,
    ] {
        delete_disk(transient)?;
    }
    Ok(outcome)
}

/// A task bundle from os/tasks, embedded in the kernel and run at boot.
struct EmbeddedBundle {
    entrypoint: (&'static str, &'static [u8]),
    input: (&'static str, &'static [u8]),
    task_manifest: &'static str,
    workflow: &'static [u8],
    block_id: &'static str,
    output: &'static str,
    /// Fragments the output file must contain.
    expected: &'static [&'static [u8]],
}

const REMISSION_BUNDLE: EmbeddedBundle = EmbeddedBundle {
    entrypoint: (
        "REMISSION.PY",
        include_bytes!("../../tasks/remission/REMISSION.PY"),
    ),
    input: (
        "SAMPLE.JSON",
        include_bytes!("../../tasks/remission/SAMPLE.JSON"),
    ),
    task_manifest: "RMTASK.JSON",
    workflow: include_bytes!("../../tasks/remission/RMFLOW.JSON"),
    block_id: "remission-model",
    output: "RESULT.OUT",
    expected: &[
        br#""modeled_status":"MODELED_REFERENCE_MATCH""#,
        br#""clinical_status":"NOT_CLINICALLY_CONFIRMED""#,
        br#""verified":true"#,
    ],
};

const RESEARCH_BUNDLE: EmbeddedBundle = EmbeddedBundle {
    entrypoint: (
        "RESEARCH.PY",
        include_bytes!("../../tasks/research/RESEARCH.PY"),
    ),
    input: (
        "RESEARCH.JSON",
        include_bytes!("../../tasks/research/RESEARCH.JSON"),
    ),
    task_manifest: "RSTASK.JSON",
    workflow: include_bytes!("../../tasks/research/RSFLOW.JSON"),
    block_id: "research-analysis",
    output: "RANKED.OUT",
    expected: &[
        br#""schema":"research-ranking.v1""#,
        br#""duplicates_removed":2"#,
        br#""unique_records":3"#,
        br#""external_id":"SYNTH-PM-1""#,
    ],
};

/// Writes the bundle's script and input to disk, runs its workflow, checks
/// its declared output, then deletes all three files. Returns the number of
/// task runs and the output size.
fn run_embedded_bundle(
    bundle: &EmbeddedBundle,
    read_file: &mut impl FnMut(&str, &mut [u8]) -> Result<usize, &'static str>,
    write_disk: &mut impl FnMut(&str, &[u8]) -> Result<(), &'static str>,
    delete_disk: &mut impl FnMut(&str) -> Result<bool, &'static str>,
    run_elf: &mut impl FnMut(&[u8], &TaskGrant) -> Result<TaskRunResult, &'static str>,
) -> Result<(usize, usize), &'static str> {
    write_disk(bundle.entrypoint.0, bundle.entrypoint.1)?;
    write_disk(bundle.input.0, bundle.input.1)?;
    let run = execute_workflow(
        bundle.workflow,
        &[bundle.task_manifest],
        &[bundle.input.0],
        &mut *read_file,
        &mut *run_elf,
    )?;
    expect_outcomes(
        &run,
        &[(
            bundle.block_id,
            BlockOutcome::Exited(0),
            BlockStatus::Succeeded,
        )],
        "embedded task bundle did not run to a successful exit",
    )?;
    let mut output = Vec::new();
    output.resize(16 * 1024, 0);
    let length = read_file(bundle.output, &mut output)?;
    let output = &output[..length];
    for needle in bundle.expected {
        if !output.windows(needle.len()).any(|window| window == *needle) {
            use core::fmt::Write;
            let _ = writeln!(
                crate::Serial,
                "task bundle {}: {} is missing {}",
                bundle.block_id,
                bundle.output,
                core::str::from_utf8(needle).unwrap_or("<binary>")
            );
            return Err("embedded task bundle output did not contain its expected result");
        }
    }
    for transient in [bundle.entrypoint.0, bundle.input.0, bundle.output] {
        if !delete_disk(transient)? {
            return Err("transient task bundle file was missing before deletion");
        }
    }
    Ok((run.executed_count(), length))
}

struct UniqueValue(Value);

impl<'de> Deserialize<'de> for UniqueValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(UniqueValueVisitor)
    }
}

struct UniqueValueVisitor;

impl<'de> Visitor<'de> for UniqueValueVisitor {
    type Value = UniqueValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON value without duplicate object keys")
    }

    fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Bool(value)))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Number(value.into())))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Number(value.into())))
    }

    fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        let number = serde_json::Number::from_f64(value)
            .ok_or_else(|| E::custom("JSON number is not finite"))?;
        Ok(UniqueValue(Value::Number(number)))
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::String(value.into())))
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::String(value)))
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Null))
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Null))
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element::<UniqueValue>()? {
            values.push(value.0);
        }
        Ok(UniqueValue(Value::Array(values)))
    }

    fn visit_map<A>(self, mut object: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut values = serde_json::Map::new();
        while let Some(key) = object.next_key::<String>()? {
            if values.contains_key(&key) {
                return Err(A::Error::custom("JSON object contains a duplicate key"));
            }
            let UniqueValue(value) = object.next_value()?;
            values.insert(key, value);
        }
        Ok(UniqueValue(Value::Object(values)))
    }
}

pub(crate) fn validate_task_manifest(
    input: &[u8],
    mut read_file: impl FnMut(&str, &mut [u8]) -> Result<usize, &'static str>,
) -> Result<TaskManifestSummary, &'static str> {
    let root = parse_manifest(input)?;
    exact_keys(
        &root,
        &[
            "schemaVersion",
            "taskId",
            "runtime",
            "entrypoint",
            "files",
            "capabilities",
            "limits",
        ],
    )?;
    require_string(&root, "schemaVersion", "nosfs.task-bundle.v1")?;
    validate_identifier(require_string_value(&root, "taskId")?, 48)?;
    let task_runtime = match require_string_value(&root, "runtime")? {
        "micropython" => TaskRuntime::MicroPython,
        "elf" => TaskRuntime::Elf,
        _ => return Err("task bundle runtime is not supported"),
    };
    let entrypoint = require_string_value(&root, "entrypoint")?;
    validate_filename(entrypoint)?;

    let files = root
        .get("files")
        .and_then(Value::as_array)
        .ok_or("task bundle files must be an array")?;
    if files.is_empty() || files.len() > MAX_TASK_FILES {
        return Err("task bundle file count is outside its supported bounds");
    }
    let mut entrypoint_digest = None;
    for (index, file) in files.iter().enumerate() {
        exact_keys(file, &["name", "role", "sizeBytes", "sha256"])?;
        let name = require_string_value(file, "name")?;
        validate_filename(name)?;
        for previous in &files[..index] {
            if previous.get("name").and_then(Value::as_str) == Some(name) {
                return Err("task bundle contains duplicate file names");
            }
        }
        let role = require_string_value(file, "role")?;
        if !matches!(role, "python" | "elf" | "json" | "data") {
            return Err("task bundle file has an unsupported role");
        }
        let size = file
            .get("sizeBytes")
            .and_then(Value::as_u64)
            .ok_or("task bundle file size must be an integer")?;
        if size == 0 || size > super::filesystem::MAX_FILE_SIZE as u64 {
            return Err("task bundle file size exceeds the filesystem limit");
        }
        let expected_digest = require_string_value(file, "sha256")?;
        validate_sha256(expected_digest)?;

        let mut contents = Vec::new();
        contents
            .try_reserve_exact(size as usize)
            .map_err(|_| "not enough kernel memory to validate a task bundle file")?;
        contents.resize(size as usize, 0);
        let length = read_file(name, &mut contents)?;
        if length != contents.len() {
            return Err("task bundle file length does not match its manifest");
        }
        let digest = sha256(&contents);
        if !digest_matches_hex(&digest, expected_digest.as_bytes()) {
            return Err("task bundle file SHA-256 does not match its manifest");
        }
        if name == entrypoint && role == task_runtime.entrypoint_role() {
            entrypoint_digest = Some((contents.len(), digest));
        }
    }
    let Some((entrypoint_size, entrypoint_sha256)) = entrypoint_digest else {
        return Err("task bundle entrypoint must name a declared file for its runtime");
    };

    let capabilities = root
        .get("capabilities")
        .ok_or("task bundle capabilities are missing")?;
    exact_keys(capabilities, &["network"])?;
    let network = capabilities
        .get("network")
        .ok_or("task bundle network capabilities are missing")?;
    exact_keys(
        network,
        &["dns", "udpDestinations", "tcpDestinations", "tlsHosts"],
    )?;
    let mut network_requested = network
        .get("dns")
        .and_then(Value::as_bool)
        .ok_or("task bundle DNS capability must be boolean")?;
    for field in ["udpDestinations", "tcpDestinations", "tlsHosts"] {
        let destinations = network
            .get(field)
            .and_then(Value::as_array)
            .ok_or("task bundle network destinations must be arrays")?;
        if destinations.len() > 8 {
            return Err("task bundle has too many network destinations");
        }
        network_requested |= !destinations.is_empty();
        for (index, destination) in destinations.iter().enumerate() {
            let host = destination
                .as_str()
                .ok_or("task bundle network destination must be a hostname")?;
            validate_hostname(host)?;
            if destinations[..index]
                .iter()
                .any(|previous| previous.as_str() == Some(host))
            {
                return Err("task bundle contains duplicate network destinations");
            }
        }
    }

    let limits = root.get("limits").ok_or("task bundle limits are missing")?;
    exact_keys(limits, &["memoryBytes", "runtimeSeconds"])?;
    let memory = require_u64(limits, "memoryBytes")?;
    let runtime_seconds = require_u64(limits, "runtimeSeconds")?;
    if !(16_384..=2_097_152).contains(&memory) || !(1..=300).contains(&runtime_seconds) {
        return Err("task bundle resource limits are outside supported bounds");
    }
    Ok(TaskManifestSummary {
        runtime: task_runtime,
        entrypoint: String::from(entrypoint),
        entrypoint_size,
        entrypoint_sha256,
        network_requested,
        runtime_seconds,
    })
}

pub(crate) fn verify_rejected_manifests() -> Result<(), &'static str> {
    if parse_manifest(b"{").is_ok() || parse_manifest(br#"{"a":1,"a":2}"#).is_ok() {
        return Err("manifest parser accepted malformed JSON");
    }
    if !digest_matches_hex(
        &sha256(b"abc"),
        b"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    ) {
        return Err("SHA-256 failed its known-answer check");
    }

    const BAD_DIGEST_TASK: &[u8] = br#"{"schemaVersion":"nosfs.task-bundle.v1","taskId":"digest-test","runtime":"micropython","entrypoint":"TASK.PY","files":[{"name":"TASK.PY","role":"python","sizeBytes":1,"sha256":"0000000000000000000000000000000000000000000000000000000000000000"}],"capabilities":{"network":{"dns":false,"udpDestinations":[],"tcpDestinations":[],"tlsHosts":[]}},"limits":{"memoryBytes":16384,"runtimeSeconds":1}}"#;
    let digest_result = validate_task_manifest(BAD_DIGEST_TASK, |_, output| {
        output.copy_from_slice(b"x");
        Ok(output.len())
    });
    if !matches!(
        digest_result,
        Err("task bundle file SHA-256 does not match its manifest")
    ) {
        return Err("task bundle validator did not reject a mismatched file digest");
    }

    const CYCLIC_WORKFLOW: &[u8] = br#"{"schemaVersion":"nosfs.workflow.v1","workflowId":"cycle-test","failurePolicy":"stop","blocks":[{"blockId":"first","taskManifest":"TASK.MF","dependsOn":["second"],"inputFiles":[],"outputFiles":[]},{"blockId":"second","taskManifest":"TASK.MF","dependsOn":["first"],"inputFiles":[],"outputFiles":[]}]}"#;
    if validate_workflow_manifest(CYCLIC_WORKFLOW, &["TASK.MF"], &[])
        != Err("workflow dependency graph contains a cycle")
    {
        return Err("workflow validator did not reject a dependency cycle");
    }
    Ok(())
}

pub(crate) fn validate_workflow_manifest(
    input: &[u8],
    available_task_manifests: &[&str],
    available_files: &[&str],
) -> Result<(), &'static str> {
    let root = parse_manifest(input)?;
    exact_keys(
        &root,
        &["schemaVersion", "workflowId", "failurePolicy", "blocks"],
    )?;
    require_string(&root, "schemaVersion", "nosfs.workflow.v1")?;
    validate_identifier(require_string_value(&root, "workflowId")?, 48)?;
    let policy = require_string_value(&root, "failurePolicy")?;
    if !matches!(policy, "stop" | "continue") {
        return Err("workflow has an unsupported failure policy");
    }
    let blocks = root
        .get("blocks")
        .and_then(Value::as_array)
        .ok_or("workflow blocks must be an array")?;
    if blocks.is_empty() || blocks.len() > MAX_WORKFLOW_BLOCKS {
        return Err("workflow block count is outside its supported bounds");
    }
    let mut block_ids = [None; MAX_WORKFLOW_BLOCKS];
    let mut block_values = [None; MAX_WORKFLOW_BLOCKS];
    for (index, block) in blocks.iter().enumerate() {
        exact_keys(
            block,
            &[
                "blockId",
                "taskManifest",
                "dependsOn",
                "inputFiles",
                "outputFiles",
            ],
        )?;
        let block_id = require_string_value(block, "blockId")?;
        validate_identifier(block_id, 32)?;
        if block_ids[..index].contains(&Some(block_id)) {
            return Err("workflow contains duplicate block IDs");
        }
        block_ids[index] = Some(block_id);
        block_values[index] = Some(block);

        let task_manifest = require_string_value(block, "taskManifest")?;
        validate_filename(task_manifest)?;
        if !available_task_manifests.contains(&task_manifest) {
            return Err("workflow references a task manifest that is not available");
        }
        validate_file_list(block, "inputFiles")?;
        validate_file_list(block, "outputFiles")?;
        let outputs = block
            .get("outputFiles")
            .and_then(Value::as_array)
            .ok_or("workflow output files must be an array")?;
        if outputs
            .iter()
            .any(|file| file.as_str().is_none_or(|name| !name.ends_with(".OUT")))
        {
            return Err("workflow output files must use the .OUT suffix");
        }
    }

    for block in blocks {
        let dependencies = block
            .get("dependsOn")
            .and_then(Value::as_array)
            .ok_or("workflow dependencies must be an array")?;
        if dependencies.len() > MAX_WORKFLOW_BLOCKS {
            return Err("workflow block has too many dependencies");
        }
        for (index, dependency) in dependencies.iter().enumerate() {
            let dependency = dependency
                .as_str()
                .ok_or("workflow dependency must be a block ID")?;
            if dependencies[..index]
                .iter()
                .any(|previous| previous.as_str() == Some(dependency))
            {
                return Err("workflow contains duplicate dependencies");
            }
            if !block_ids.contains(&Some(dependency)) {
                return Err("workflow dependency references an unknown block");
            }
        }
        let input_files = block
            .get("inputFiles")
            .and_then(Value::as_array)
            .ok_or("workflow input files must be an array")?;
        for file in input_files {
            let name = file
                .as_str()
                .ok_or("workflow input file must be a filename")?;
            let produced_by_dependency = dependencies.iter().any(|dependency| {
                blocks.iter().any(|candidate| {
                    candidate.get("blockId") == Some(dependency)
                        && candidate
                            .get("outputFiles")
                            .and_then(Value::as_array)
                            .is_some_and(|outputs| {
                                outputs.iter().any(|output| output.as_str() == Some(name))
                            })
                })
            });
            if !available_files.contains(&name) && !produced_by_dependency {
                return Err("workflow references an input file that is not available");
            }
        }
    }

    let mut completed = [false; MAX_WORKFLOW_BLOCKS];
    let mut completed_count = 0;
    while completed_count < blocks.len() {
        let mut made_progress = false;
        for index in 0..blocks.len() {
            if completed[index] {
                continue;
            }
            let block = block_values[index].ok_or("workflow block validation state is invalid")?;
            let dependencies = block
                .get("dependsOn")
                .and_then(Value::as_array)
                .ok_or("workflow dependencies must be an array")?;
            let ready = dependencies.iter().all(|dependency| {
                let dependency = dependency.as_str();
                block_ids
                    .iter()
                    .position(|block_id| *block_id == dependency)
                    .is_some_and(|dependency_index| completed[dependency_index])
            });
            if ready {
                completed[index] = true;
                completed_count += 1;
                made_progress = true;
            }
        }
        if !made_progress {
            return Err("workflow dependency graph contains a cycle");
        }
    }
    Ok(())
}

fn parse_manifest(input: &[u8]) -> Result<Value, &'static str> {
    if input.is_empty() || input.len() > MAX_MANIFEST_SIZE {
        return Err("manifest size is outside the supported bounds");
    }
    let UniqueValue(value) = serde_json::from_slice(input)
        .map_err(|_| "manifest contains invalid or duplicate-key JSON")?;
    if !value.is_object() {
        return Err("manifest root must be a JSON object");
    }
    Ok(value)
}

fn exact_keys(value: &Value, expected: &[&str]) -> Result<(), &'static str> {
    let object = value
        .as_object()
        .ok_or("manifest field must be a JSON object")?;
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err("manifest object has missing or unsupported fields");
    }
    Ok(())
}

fn require_string<'a>(value: &'a Value, field: &str, expected: &str) -> Result<(), &'static str> {
    if require_string_value(value, field)? == expected {
        Ok(())
    } else {
        Err("manifest version or runtime is unsupported")
    }
}

fn require_string_value<'a>(value: &'a Value, field: &str) -> Result<&'a str, &'static str> {
    value
        .get(field)
        .and_then(Value::as_str)
        .ok_or("manifest field must be a string")
}

fn require_u64(value: &Value, field: &str) -> Result<u64, &'static str> {
    value
        .get(field)
        .and_then(Value::as_u64)
        .ok_or("manifest field must be a nonnegative integer")
}

fn validate_identifier(value: &str, max_length: usize) -> Result<(), &'static str> {
    let bytes = value.as_bytes();
    if bytes.is_empty()
        || bytes.len() > max_length
        || !bytes[0].is_ascii_lowercase() && !bytes[0].is_ascii_digit()
        || !bytes
            .iter()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || b"._-".contains(byte))
    {
        return Err("manifest identifier is invalid");
    }
    Ok(())
}

fn validate_filename(value: &str) -> Result<(), &'static str> {
    let bytes = value.as_bytes();
    if bytes.is_empty()
        || bytes.len() > 15
        || !bytes[0].is_ascii_uppercase() && !bytes[0].is_ascii_digit()
        || !bytes
            .iter()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || b"._-".contains(byte))
    {
        return Err("manifest contains an invalid NOSFS filename");
    }
    Ok(())
}

fn validate_sha256(value: &str) -> Result<(), &'static str> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("manifest SHA-256 value is invalid");
    }
    Ok(())
}

fn digest_matches_hex(digest: &[u8], expected: &[u8]) -> bool {
    if digest.len() * 2 != expected.len() {
        return false;
    }
    digest.iter().enumerate().all(|(index, byte)| {
        let high = hex_digit(byte >> 4);
        let low = hex_digit(byte & 0x0f);
        expected[index * 2] == high && expected[index * 2 + 1] == low
    })
}

fn sha256(input: &[u8]) -> [u8; 32] {
    const INITIAL_STATE: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut state = INITIAL_STATE;
    let mut chunks = input.chunks_exact(64);
    for chunk in &mut chunks {
        let mut block = [0; 64];
        block.copy_from_slice(chunk);
        compress_sha256(&mut state, &block);
    }

    let remainder = chunks.remainder();
    let mut tail = [0; 128];
    tail[..remainder.len()].copy_from_slice(remainder);
    tail[remainder.len()] = 0x80;
    let tail_length = if remainder.len() < 56 { 64 } else { 128 };
    let bit_length = (input.len() as u64).wrapping_mul(8);
    tail[tail_length - 8..tail_length].copy_from_slice(&bit_length.to_be_bytes());
    for block in tail[..tail_length].chunks_exact(64) {
        let mut block_bytes = [0; 64];
        block_bytes.copy_from_slice(block);
        compress_sha256(&mut state, &block_bytes);
    }

    let mut digest = [0; 32];
    for (index, word) in state.iter().enumerate() {
        digest[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    digest
}

fn compress_sha256(state: &mut [u32; 8], block: &[u8; 64]) {
    const ROUND_CONSTANTS: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut words = [0u32; 64];
    for (index, bytes) in block.chunks_exact(4).enumerate() {
        words[index] = u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
    }
    for index in 16..64 {
        let x = words[index - 15];
        let y = words[index - 2];
        let sigma0 = x.rotate_right(7) ^ x.rotate_right(18) ^ (x >> 3);
        let sigma1 = y.rotate_right(17) ^ y.rotate_right(19) ^ (y >> 10);
        words[index] = words[index - 16]
            .wrapping_add(sigma0)
            .wrapping_add(words[index - 7])
            .wrapping_add(sigma1);
    }

    let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = *state;
    for (index, round_constant) in ROUND_CONSTANTS.iter().enumerate() {
        let sum1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
        let choose = (e & f) ^ (!e & g);
        let temp1 = h
            .wrapping_add(sum1)
            .wrapping_add(choose)
            .wrapping_add(*round_constant)
            .wrapping_add(words[index]);
        let sum0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
        let majority = (a & b) ^ (a & c) ^ (b & c);
        let temp2 = sum0.wrapping_add(majority);
        h = g;
        g = f;
        f = e;
        e = d.wrapping_add(temp1);
        d = c;
        c = b;
        b = a;
        a = temp1.wrapping_add(temp2);
    }
    state[0] = state[0].wrapping_add(a);
    state[1] = state[1].wrapping_add(b);
    state[2] = state[2].wrapping_add(c);
    state[3] = state[3].wrapping_add(d);
    state[4] = state[4].wrapping_add(e);
    state[5] = state[5].wrapping_add(f);
    state[6] = state[6].wrapping_add(g);
    state[7] = state[7].wrapping_add(h);
}

fn hex_digit(value: u8) -> u8 {
    match value {
        0..=9 => b'0' + value,
        _ => b'a' + value - 10,
    }
}

fn validate_hostname(hostname: &str) -> Result<(), &'static str> {
    if hostname.is_empty()
        || hostname.len() > 253
        || hostname.split('.').any(|label| {
            let bytes = label.as_bytes();
            bytes.is_empty()
                || bytes.len() > 63
                || !bytes[0].is_ascii_alphanumeric()
                || !bytes[bytes.len() - 1].is_ascii_alphanumeric()
                || !bytes
                    .iter()
                    .all(|byte| byte.is_ascii_alphanumeric() || *byte == b'-')
        })
    {
        return Err("manifest contains an invalid network hostname");
    }
    Ok(())
}

fn validate_file_list(block: &Value, field: &str) -> Result<(), &'static str> {
    let files = block
        .get(field)
        .and_then(Value::as_array)
        .ok_or("workflow file references must be arrays")?;
    if files.len() > 8 {
        return Err("workflow block references too many files");
    }
    for (index, file) in files.iter().enumerate() {
        let name = file
            .as_str()
            .ok_or("workflow file reference must be a filename")?;
        validate_filename(name)?;
        if files[..index]
            .iter()
            .any(|previous| previous.as_str() == Some(name))
        {
            return Err("workflow block contains duplicate file references");
        }
    }
    Ok(())
}
