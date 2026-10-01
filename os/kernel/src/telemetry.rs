use core::cmp::Ordering as CmpOrdering;

use crate::Serial;
use core::fmt::Write;

const LOG_MAGIC: &[u8; 8] = b"NOSLOG01";
const CHECKPOINT_MAGIC: &[u8; 8] = b"NOSCHK01";
const LOG_A: &str = "OSLOG.A";
const LOG_B: &str = "OSLOG.B";
const CHECKPOINT_A: &str = "OSCHK.A";
const CHECKPOINT_B: &str = "OSCHK.B";
const LOG_HEADER_SIZE: usize = 24;
const MAX_EVENTS: usize = 8;
const EVENT_SIZE: usize = 16;
const LOG_SIZE: usize = LOG_HEADER_SIZE + MAX_EVENTS * EVENT_SIZE + 8;
const CHECKPOINT_SIZE: usize = 40;
type SlotRead<T> = Result<Option<T>, &'static str>;

pub(crate) const STATUS_OK: u16 = 0;
pub(crate) const STATUS_FAILED: u16 = 1;
pub(crate) const STAGE_BOOT_STARTED: u16 = 1;
pub(crate) const STAGE_TASKS_VALIDATED: u16 = 2;
pub(crate) const STAGE_USER_PROCESS_CHECKED: u16 = 3;
pub(crate) const STAGE_DHCP_CONFIGURED: u16 = 4;
pub(crate) const STAGE_NETWORK_READY: u16 = 5;
pub(crate) const STAGE_BOOT_FAILED: u16 = u16::MAX;

#[derive(Clone, Copy, Default, Eq, PartialEq)]
struct Event {
    sequence: u64,
    stage: u16,
    status: u16,
    ticks: u32,
}

#[derive(Clone, Copy, Default, Eq, PartialEq)]
struct EventLog {
    generation: u64,
    count: usize,
    events: [Event; MAX_EVENTS],
}

#[derive(Clone, Copy, Default, Eq, PartialEq)]
struct Checkpoint {
    generation: u64,
    boot_count: u64,
    stage: u16,
    status: u16,
    ticks: u32,
}

pub(crate) struct Telemetry {
    enabled: bool,
    log: EventLog,
    checkpoint: Checkpoint,
    log_slot: Option<usize>,
    checkpoint_slot: Option<usize>,
    recovered_copy: bool,
}

impl Telemetry {
    pub(crate) const fn new() -> Self {
        Self {
            enabled: false,
            log: EventLog {
                generation: 0,
                count: 0,
                events: [Event {
                    sequence: 0,
                    stage: 0,
                    status: 0,
                    ticks: 0,
                }; MAX_EVENTS],
            },
            checkpoint: Checkpoint {
                generation: 0,
                boot_count: 0,
                stage: 0,
                status: 0,
                ticks: 0,
            },
            log_slot: None,
            checkpoint_slot: None,
            recovered_copy: false,
        }
    }

    pub(crate) fn initialize(&mut self, ticks: u64) -> Result<(), &'static str> {
        verify_fallback_policy()?;
        let _ = writeln!(
            Serial,
            "Guest checkpoint failback verified: intact prior copy selected after simulated corruption."
        );
        let (log, log_slot, log_recovered) = load_log_pair()?;
        let (checkpoint, checkpoint_slot, checkpoint_recovered) = load_checkpoint_pair()?;
        self.log = log;
        self.log_slot = log_slot;
        self.checkpoint = checkpoint;
        self.checkpoint_slot = checkpoint_slot;
        self.recovered_copy = log_recovered || checkpoint_recovered;
        self.enabled = true;
        if self.recovered_copy {
            let _ = writeln!(
                Serial,
                "Guest telemetry fallback selected the newest intact checkpoint; redundancy will be repaired."
            );
        }
        self.record(STAGE_BOOT_STARTED, STATUS_OK, ticks)
    }

    pub(crate) fn record(
        &mut self,
        stage: u16,
        status: u16,
        ticks: u64,
    ) -> Result<(), &'static str> {
        if !self.enabled {
            return Ok(());
        }
        let result = self.commit_record(stage, status, ticks);
        if result.is_err() {
            self.enabled = false;
        }
        result
    }

    fn commit_record(&mut self, stage: u16, status: u16, ticks: u64) -> Result<(), &'static str> {
        let log_generation = self
            .log
            .generation
            .checked_add(1)
            .ok_or("guest event-log generation overflow")?;
        let checkpoint_generation = self
            .checkpoint
            .generation
            .checked_add(1)
            .ok_or("guest checkpoint generation overflow")?;
        let boot_count = if stage == STAGE_BOOT_STARTED {
            self.checkpoint
                .boot_count
                .checked_add(1)
                .ok_or("guest boot counter overflow")?
        } else {
            self.checkpoint.boot_count
        };

        let mut next_log = self.log;
        if next_log.count == MAX_EVENTS {
            next_log.events.copy_within(1..MAX_EVENTS, 0);
            next_log.count -= 1;
        }
        next_log.events[next_log.count] = Event {
            sequence: log_generation,
            stage,
            status,
            ticks: ticks.min(u64::from(u32::MAX)) as u32,
        };
        next_log.count += 1;
        next_log.generation = log_generation;

        let next_checkpoint = Checkpoint {
            generation: checkpoint_generation,
            boot_count,
            stage,
            status,
            ticks: ticks.min(u64::from(u32::MAX)) as u32,
        };

        let log_target = other_slot(self.log_slot);
        commit_log(log_target, &next_log)?;
        self.log = next_log;
        self.log_slot = Some(log_target);

        let checkpoint_target = other_slot(self.checkpoint_slot);
        commit_checkpoint(checkpoint_target, &next_checkpoint)?;
        self.checkpoint = next_checkpoint;
        self.checkpoint_slot = Some(checkpoint_target);
        self.recovered_copy = false;
        Ok(())
    }

    pub(crate) fn boot_count(&self) -> u64 {
        self.checkpoint.boot_count
    }

    pub(crate) fn log_generation(&self) -> u64 {
        self.log.generation
    }

    pub(crate) fn checkpoint_generation(&self) -> u64 {
        self.checkpoint.generation
    }
}

fn other_slot(active: Option<usize>) -> usize {
    match active {
        Some(0) => 1,
        Some(_) | None => 0,
    }
}

fn load_log_pair() -> Result<(EventLog, Option<usize>, bool), &'static str> {
    choose_log_pair(read_log_slot(LOG_A), read_log_slot(LOG_B))
}

fn choose_log_pair(
    first: SlotRead<EventLog>,
    second: SlotRead<EventLog>,
) -> Result<(EventLog, Option<usize>, bool), &'static str> {
    match (first, second) {
        (Ok(Some(a)), Ok(Some(b))) => match a.generation.cmp(&b.generation) {
            CmpOrdering::Greater => Ok((a, Some(0), false)),
            CmpOrdering::Less => Ok((b, Some(1), false)),
            CmpOrdering::Equal if a == b => Ok((a, Some(0), false)),
            CmpOrdering::Equal => Err("guest event-log copies conflict at the same generation"),
        },
        (Ok(Some(value)), Ok(None)) => Ok((value, Some(0), true)),
        (Ok(None), Ok(Some(value))) => Ok((value, Some(1), true)),
        (Ok(Some(value)), Err(_)) => Ok((value, Some(0), true)),
        (Err(_), Ok(Some(value))) => Ok((value, Some(1), true)),
        (Ok(None), Ok(None)) => Ok((EventLog::default(), None, false)),
        _ => Err("no intact guest event-log checkpoint is available"),
    }
}

fn load_checkpoint_pair() -> Result<(Checkpoint, Option<usize>, bool), &'static str> {
    choose_checkpoint_pair(
        read_checkpoint_slot(CHECKPOINT_A),
        read_checkpoint_slot(CHECKPOINT_B),
    )
}

fn choose_checkpoint_pair(
    first: SlotRead<Checkpoint>,
    second: SlotRead<Checkpoint>,
) -> Result<(Checkpoint, Option<usize>, bool), &'static str> {
    match (first, second) {
        (Ok(Some(a)), Ok(Some(b))) => match a.generation.cmp(&b.generation) {
            CmpOrdering::Greater => Ok((a, Some(0), false)),
            CmpOrdering::Less => Ok((b, Some(1), false)),
            CmpOrdering::Equal if a == b => Ok((a, Some(0), false)),
            CmpOrdering::Equal => Err("guest checkpoint copies conflict at the same generation"),
        },
        (Ok(Some(value)), Ok(None)) => Ok((value, Some(0), true)),
        (Ok(None), Ok(Some(value))) => Ok((value, Some(1), true)),
        (Ok(Some(value)), Err(_)) => Ok((value, Some(0), true)),
        (Err(_), Ok(Some(value))) => Ok((value, Some(1), true)),
        (Ok(None), Ok(None)) => Ok((Checkpoint::default(), None, false)),
        _ => Err("no intact guest boot checkpoint is available"),
    }
}

fn verify_fallback_policy() -> Result<(), &'static str> {
    let older = Checkpoint {
        generation: 1,
        boot_count: 1,
        stage: STAGE_BOOT_STARTED,
        status: STATUS_OK,
        ticks: 10,
    };
    let newer = Checkpoint {
        generation: 2,
        stage: STAGE_TASKS_VALIDATED,
        ticks: 20,
        ..older
    };
    let mut damaged_newer = encode_checkpoint(&newer);
    damaged_newer[CHECKPOINT_SIZE - 1] ^= 1;
    if decode_checkpoint(&damaged_newer).is_ok() {
        return Err("guest checkpoint checksum did not detect simulated corruption");
    }
    let (selected, slot, recovered) =
        choose_checkpoint_pair(Ok(Some(older)), decode_checkpoint(&damaged_newer).map(Some))?;
    if selected != older || slot != Some(0) || !recovered {
        return Err("guest checkpoint did not fall back to the intact prior generation");
    }
    Ok(())
}

fn read_log_slot(name: &str) -> Result<Option<EventLog>, &'static str> {
    let mut bytes = [0; LOG_SIZE];
    match super::storage::read_named_file(name, &mut bytes) {
        Ok(length) => decode_log(&bytes[..length]).map(Some),
        Err("filesystem file does not exist") => Ok(None),
        Err(_) => Err("guest event-log slot could not be read"),
    }
}

fn read_checkpoint_slot(name: &str) -> Result<Option<Checkpoint>, &'static str> {
    let mut bytes = [0; CHECKPOINT_SIZE];
    match super::storage::read_named_file(name, &mut bytes) {
        Ok(length) => decode_checkpoint(&bytes[..length]).map(Some),
        Err("filesystem file does not exist") => Ok(None),
        Err(_) => Err("guest checkpoint slot could not be read"),
    }
}

fn commit_log(slot: usize, log: &EventLog) -> Result<(), &'static str> {
    let name = if slot == 0 { LOG_A } else { LOG_B };
    let bytes = encode_log(log);
    super::storage::write_named_file(name, &bytes)?;
    let stored = read_log_slot(name)?.ok_or("guest event-log write did not persist")?;
    if stored != *log {
        return Err("guest event-log readback did not match the committed record");
    }
    Ok(())
}

fn commit_checkpoint(slot: usize, checkpoint: &Checkpoint) -> Result<(), &'static str> {
    let name = if slot == 0 {
        CHECKPOINT_A
    } else {
        CHECKPOINT_B
    };
    let bytes = encode_checkpoint(checkpoint);
    super::storage::write_named_file(name, &bytes)?;
    let stored = read_checkpoint_slot(name)?.ok_or("guest checkpoint write did not persist")?;
    if stored != *checkpoint {
        return Err("guest checkpoint readback did not match the committed record");
    }
    Ok(())
}

fn encode_log(log: &EventLog) -> [u8; LOG_SIZE] {
    let mut bytes = [0; LOG_SIZE];
    bytes[..8].copy_from_slice(LOG_MAGIC);
    bytes[8..16].copy_from_slice(&log.generation.to_le_bytes());
    bytes[16..20].copy_from_slice(&(log.count as u32).to_le_bytes());
    for (index, event) in log.events.iter().take(log.count).enumerate() {
        let offset = LOG_HEADER_SIZE + index * EVENT_SIZE;
        bytes[offset..offset + 8].copy_from_slice(&event.sequence.to_le_bytes());
        bytes[offset + 8..offset + 10].copy_from_slice(&event.stage.to_le_bytes());
        bytes[offset + 10..offset + 12].copy_from_slice(&event.status.to_le_bytes());
        bytes[offset + 12..offset + 16].copy_from_slice(&event.ticks.to_le_bytes());
    }
    let checksum_offset = LOG_SIZE - 8;
    let hash = checksum(&bytes[..checksum_offset]);
    bytes[checksum_offset..].copy_from_slice(&hash.to_le_bytes());
    bytes
}

fn decode_log(bytes: &[u8]) -> Result<EventLog, &'static str> {
    if bytes.len() != LOG_SIZE || &bytes[..8] != LOG_MAGIC {
        return Err("guest event-log format is invalid");
    }
    let checksum_offset = LOG_SIZE - 8;
    if checksum(&bytes[..checksum_offset])
        != u64::from_le_bytes(bytes[checksum_offset..].try_into().unwrap())
    {
        return Err("guest event-log checksum mismatch");
    }
    let count = u32::from_le_bytes(bytes[16..20].try_into().unwrap()) as usize;
    if count > MAX_EVENTS || bytes[20..LOG_HEADER_SIZE].iter().any(|byte| *byte != 0) {
        return Err("guest event-log count or reserved header is invalid");
    }
    let generation = u64::from_le_bytes(bytes[8..16].try_into().unwrap());
    if generation < count as u64 {
        return Err("guest event-log generation is inconsistent");
    }
    let mut log = EventLog {
        generation,
        count,
        events: [Event::default(); MAX_EVENTS],
    };
    let first_sequence = generation - count as u64 + 1;
    for index in 0..count {
        let offset = LOG_HEADER_SIZE + index * EVENT_SIZE;
        let event = Event {
            sequence: u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap()),
            stage: u16::from_le_bytes(bytes[offset + 8..offset + 10].try_into().unwrap()),
            status: u16::from_le_bytes(bytes[offset + 10..offset + 12].try_into().unwrap()),
            ticks: u32::from_le_bytes(bytes[offset + 12..offset + 16].try_into().unwrap()),
        };
        if event.sequence != first_sequence + index as u64 {
            return Err("guest event-log sequence is invalid");
        }
        log.events[index] = event;
    }
    Ok(log)
}

fn encode_checkpoint(checkpoint: &Checkpoint) -> [u8; CHECKPOINT_SIZE] {
    let mut bytes = [0; CHECKPOINT_SIZE];
    bytes[..8].copy_from_slice(CHECKPOINT_MAGIC);
    bytes[8..16].copy_from_slice(&checkpoint.generation.to_le_bytes());
    bytes[16..24].copy_from_slice(&checkpoint.boot_count.to_le_bytes());
    bytes[24..26].copy_from_slice(&checkpoint.stage.to_le_bytes());
    bytes[26..28].copy_from_slice(&checkpoint.status.to_le_bytes());
    bytes[28..32].copy_from_slice(&checkpoint.ticks.to_le_bytes());
    let hash = checksum(&bytes[..32]);
    bytes[32..].copy_from_slice(&hash.to_le_bytes());
    bytes
}

fn decode_checkpoint(bytes: &[u8]) -> Result<Checkpoint, &'static str> {
    if bytes.len() != CHECKPOINT_SIZE || &bytes[..8] != CHECKPOINT_MAGIC {
        return Err("guest checkpoint format is invalid");
    }
    if checksum(&bytes[..32]) != u64::from_le_bytes(bytes[32..].try_into().unwrap()) {
        return Err("guest checkpoint checksum mismatch");
    }
    let generation = u64::from_le_bytes(bytes[8..16].try_into().unwrap());
    let boot_count = u64::from_le_bytes(bytes[16..24].try_into().unwrap());
    if generation == 0 || boot_count == 0 {
        return Err("guest checkpoint counters are invalid");
    }
    Ok(Checkpoint {
        generation,
        boot_count,
        stage: u16::from_le_bytes(bytes[24..26].try_into().unwrap()),
        status: u16::from_le_bytes(bytes[26..28].try_into().unwrap()),
        ticks: u32::from_le_bytes(bytes[28..32].try_into().unwrap()),
    })
}

fn checksum(bytes: &[u8]) -> u64 {
    bytes.iter().fold(0xcbf2_9ce4_8422_2325, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(0x100_0000_01b3)
    })
}
