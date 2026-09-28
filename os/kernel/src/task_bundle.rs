use alloc::string::String;
use alloc::vec::Vec;
use core::fmt;
use serde::{
    Deserialize, Deserializer,
    de::{Error as _, MapAccess, SeqAccess, Visitor},
};
use serde_json::Value;

const MAX_MANIFEST_SIZE: usize = 4096;
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
) -> Result<(), &'static str> {
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
    require_string(&root, "runtime", "micropython")?;
    let entrypoint = require_string_value(&root, "entrypoint")?;
    validate_filename(entrypoint)?;

    let files = root
        .get("files")
        .and_then(Value::as_array)
        .ok_or("task bundle files must be an array")?;
    if files.is_empty() || files.len() > MAX_TASK_FILES {
        return Err("task bundle file count is outside its supported bounds");
    }
    let mut entrypoint_is_python = false;
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
        if !matches!(role, "python" | "json" | "data") {
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
        if name == entrypoint && role == "python" {
            entrypoint_is_python = true;
        }
    }
    if !entrypoint_is_python {
        return Err("task bundle entrypoint must name a declared Python file");
    }

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
    network
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
    let runtime = require_u64(limits, "runtimeSeconds")?;
    if !(16_384..=2_097_152).contains(&memory) || !(1..=300).contains(&runtime) {
        return Err("task bundle resource limits are outside supported bounds");
    }
    Ok(())
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
    if digest_result != Err("task bundle file SHA-256 does not match its manifest") {
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
        let input_files = block
            .get("inputFiles")
            .and_then(Value::as_array)
            .ok_or("workflow input files must be an array")?;
        if input_files.iter().any(|file| {
            file.as_str()
                .is_none_or(|name| !available_files.contains(&name))
        }) {
            return Err("workflow references an input file that is not available");
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
