use super::block_device::{BlockDevice, SECTOR_SIZE, Sector};
use crate::{port_read, port_read_u16, port_write, port_write_u16};
use core::sync::atomic::{AtomicBool, Ordering};

const IO_BASE: u16 = 0x170;
const CONTROL_PORT: u16 = 0x376;
const DATA_PORT: u16 = IO_BASE;
const ERROR_FEATURES_PORT: u16 = IO_BASE + 1;
const SECTOR_COUNT_PORT: u16 = IO_BASE + 2;
const LBA_LOW_PORT: u16 = IO_BASE + 3;
const LBA_MID_PORT: u16 = IO_BASE + 4;
const LBA_HIGH_PORT: u16 = IO_BASE + 5;
const DRIVE_PORT: u16 = IO_BASE + 6;
const STATUS_COMMAND_PORT: u16 = IO_BASE + 7;
const STATUS_ERROR: u8 = 1;
const STATUS_DATA_READY: u8 = 1 << 3;
const STATUS_BUSY: u8 = 1 << 7;
const READ_SECTORS: u8 = 0x20;
const WRITE_SECTORS: u8 = 0x30;
const FLUSH_CACHE: u8 = 0xe7;
const TEST_LBA: u32 = 1;
const DEVICE_SECTORS: u32 = 4096;
const MAGIC: &[u8; 8] = b"NOSDISK1";
const BOOT_JSON_NAME: &str = "BOOT.JSON";
const BOOT_JSON_CONTENT: &[u8] =
    br#"{"schema":"network-os.fs-smoke.v1","purpose":"persistent filesystem test"}"#;
const TEST_ELF_NAME: &str = "TEST.ELF";
const TEST_ELF_SIZE: usize = 134;
const RUNTIME_TEST_SIZE: usize = 24 * 1024;
const TASK_MANIFEST_NAME: &str = "TASK.MF";
const TASK_MANIFEST: &[u8] = br#"{"schemaVersion":"nosfs.task-bundle.v1","taskId":"offline-smoke","runtime":"micropython","entrypoint":"TASK.PY","files":[{"name":"TASK.PY","role":"python","sizeBytes":32,"sha256":"eb6cbf91a38220fe9ab3bcb02dd0ae95b938e08ee1b7a54686244b9ddeb2d94c"},{"name":"INPUT.JSON","role":"json","sizeBytes":20,"sha256":"1ae0badf27f751acdba98773e30e45d08351ee156bdf97c99e888add3fd5e790"}],"capabilities":{"network":{"dns":false,"udpDestinations":[],"tcpDestinations":[],"tlsHosts":[]}},"limits":{"memoryBytes":65536,"runtimeSeconds":5}}"#;
const WORKFLOW_MANIFEST_NAME: &str = "FLOW.MF";
const WORKFLOW_MANIFEST: &[u8] = br#"{"schemaVersion":"nosfs.workflow.v1","workflowId":"offline-smoke","failurePolicy":"stop","blocks":[{"blockId":"inspect-input","taskManifest":"TASK.MF","dependsOn":[],"inputFiles":["INPUT.JSON"],"outputFiles":["OUTPUT.JSON"]},{"blockId":"summarize-input","taskManifest":"TASK.MF","dependsOn":["inspect-input"],"inputFiles":["INPUT.JSON"],"outputFiles":["SUMMARY.JSON"]}]}"#;
const TASK_PYTHON_NAME: &str = "TASK.PY";
const TASK_PYTHON: &[u8] = b"print(\"task bundle smoke test\")\n";
const TASK_INPUT_NAME: &str = "INPUT.JSON";
const TASK_INPUT: &[u8] = br#"{"sample":"offline"}"#;
const TEST_ELF_CODE: [u8; 14] = [
    0xb8, 0x01, 0x00, 0x00, 0x00, 0xbf, 0x2a, 0x00, 0x00, 0x00, 0xcd, 0x80, 0x0f, 0x0b,
];

// The atomic lock below provides exclusive access to this boot-time test buffer.
struct RuntimeTestReadback(core::cell::UnsafeCell<[u8; RUNTIME_TEST_SIZE]>);

unsafe impl Sync for RuntimeTestReadback {}

struct RuntimeTestGuard;

impl Drop for RuntimeTestGuard {
    fn drop(&mut self) {
        RUNTIME_TEST_LOCK.store(false, Ordering::Release);
    }
}

static RUNTIME_TEST_PAYLOAD: [u8; RUNTIME_TEST_SIZE] = create_runtime_test_payload();
static RUNTIME_TEST_READBACK: RuntimeTestReadback =
    RuntimeTestReadback(core::cell::UnsafeCell::new([0; RUNTIME_TEST_SIZE]));
static RUNTIME_TEST_LOCK: AtomicBool = AtomicBool::new(false);

pub(crate) fn verify_persistent_record() -> Result<u64, &'static str> {
    let mut device = QemuAtaDevice::initialize()?;
    verify_device_bounds(&device)?;
    let mut sector = [0u8; SECTOR_SIZE];
    device.read_sector(TEST_LBA, &mut sector)?;

    let generation = if sector.iter().all(|byte| *byte == 0) {
        1
    } else {
        if &sector[..MAGIC.len()] != MAGIC {
            return Err(
                "reserved test sector contains an unknown record; refusing to overwrite it",
            );
        }
        let previous = u64::from_le_bytes(
            sector[8..16]
                .try_into()
                .map_err(|_| "persistent record has an invalid generation field")?,
        );
        let stored_hash = u64::from_le_bytes(
            sector[16..24]
                .try_into()
                .map_err(|_| "persistent record has an invalid checksum field")?,
        );
        if record_hash(&sector[..16]) != stored_hash {
            return Err("persistent storage record checksum did not match");
        }
        previous
            .checked_add(1)
            .ok_or("persistent storage generation counter overflow")?
    };

    sector.fill(0);
    sector[..MAGIC.len()].copy_from_slice(MAGIC);
    sector[8..16].copy_from_slice(&generation.to_le_bytes());
    let checksum = record_hash(&sector[..16]);
    sector[16..24].copy_from_slice(&checksum.to_le_bytes());
    device.write_sector(TEST_LBA, &sector)?;
    device.flush()?;

    let mut verified = [0u8; SECTOR_SIZE];
    device.read_sector(TEST_LBA, &mut verified)?;
    if verified[..24] != sector[..24] {
        return Err("persistent storage read-after-write verification failed");
    }
    Ok(generation)
}

pub(crate) fn verify_filesystem_record() -> Result<(), &'static str> {
    let mut device = QemuAtaDevice::initialize()?;
    let filesystem = super::filesystem::Filesystem::mount(&mut device)?;
    let mut stored = [0; 512];
    match filesystem.read_file(&mut device, BOOT_JSON_NAME, &mut stored) {
        Ok(length) => {
            if &stored[..length] != BOOT_JSON_CONTENT {
                return Err("filesystem BOOT.JSON contains unexpected data");
            }
        }
        Err("filesystem file does not exist") => {
            filesystem.write_file(&mut device, BOOT_JSON_NAME, BOOT_JSON_CONTENT)?;
            let mut verified = [0; 512];
            let length = filesystem.read_file(&mut device, BOOT_JSON_NAME, &mut verified)?;
            if &verified[..length] != BOOT_JSON_CONTENT {
                return Err("filesystem BOOT.JSON read-after-write verification failed");
            }
        }
        Err(error) => return Err(error),
    }

    const UPDATE_NAME: &str = "UPDATE.TEST";
    const UPDATE_CONTENT: &[u8] = b"replacement file contents verify extent update and release";
    filesystem.write_file(&mut device, UPDATE_NAME, UPDATE_CONTENT)?;
    let mut updated = [0; 512];
    let length = filesystem.read_file(&mut device, UPDATE_NAME, &mut updated)?;
    if &updated[..length] != UPDATE_CONTENT {
        return Err("filesystem replacement write did not persist the updated file");
    }

    const RUNTIME_TEST_NAME: &str = "RUNTIME.TEST";
    RUNTIME_TEST_LOCK
        .compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
        .map_err(|_| "filesystem runtime-size test buffer is already in use")?;
    let _runtime_test_guard = RuntimeTestGuard;
    filesystem.write_file(&mut device, RUNTIME_TEST_NAME, &RUNTIME_TEST_PAYLOAD)?;
    let runtime_readback = unsafe { &mut *RUNTIME_TEST_READBACK.0.get() };
    let runtime_length = filesystem.read_file(&mut device, RUNTIME_TEST_NAME, runtime_readback)?;
    if runtime_length != RUNTIME_TEST_SIZE || runtime_readback != &RUNTIME_TEST_PAYLOAD {
        return Err("filesystem runtime-sized file failed read-after-write verification");
    }

    let test_elf = create_test_elf();
    filesystem.write_file(&mut device, TEST_ELF_NAME, &test_elf)?;
    let mut stored_elf = [0; TEST_ELF_SIZE];
    let elf_length = filesystem.read_file(&mut device, TEST_ELF_NAME, &mut stored_elf)?;
    if elf_length != TEST_ELF_SIZE || stored_elf != test_elf {
        return Err("filesystem TEST.ELF read-after-write verification failed");
    }
    Ok(())
}

pub(crate) fn verify_task_bundle() -> Result<(), &'static str> {
    let mut device = QemuAtaDevice::initialize()?;
    let filesystem = super::filesystem::Filesystem::mount(&mut device)?;
    filesystem.write_file(&mut device, TASK_MANIFEST_NAME, TASK_MANIFEST)?;
    filesystem.write_file(&mut device, WORKFLOW_MANIFEST_NAME, WORKFLOW_MANIFEST)?;
    filesystem.write_file(&mut device, TASK_PYTHON_NAME, TASK_PYTHON)?;
    filesystem.write_file(&mut device, TASK_INPUT_NAME, TASK_INPUT)?;

    let mut task_manifest = [0; 4096];
    let task_manifest_length =
        filesystem.read_file(&mut device, TASK_MANIFEST_NAME, &mut task_manifest)?;
    if &task_manifest[..task_manifest_length] != TASK_MANIFEST {
        return Err("task bundle manifest readback did not match the stored bytes");
    }
    super::task_bundle::validate_task_manifest(
        &task_manifest[..task_manifest_length],
        |name, output| filesystem.read_file(&mut device, name, output),
    )?;

    let mut workflow_manifest = [0; 4096];
    let workflow_manifest_length =
        filesystem.read_file(&mut device, WORKFLOW_MANIFEST_NAME, &mut workflow_manifest)?;
    if &workflow_manifest[..workflow_manifest_length] != WORKFLOW_MANIFEST {
        return Err("workflow manifest readback did not match the stored bytes");
    }
    super::task_bundle::validate_workflow_manifest(
        &workflow_manifest[..workflow_manifest_length],
        &[TASK_MANIFEST_NAME],
        &[TASK_PYTHON_NAME, TASK_INPUT_NAME],
    )?;

    super::task_bundle::verify_rejected_manifests()?;
    let planned_events = super::task_bundle::verify_dispatcher_smoke(
        &workflow_manifest[..workflow_manifest_length],
        &[TASK_MANIFEST_NAME],
        &[TASK_PYTHON_NAME, TASK_INPUT_NAME],
    )?;
    if planned_events != 5 {
        return Err("workflow dispatcher returned an unexpected bounded event count");
    }
    Ok(())
}

pub(crate) fn read_test_elf(output: &mut [u8]) -> Result<usize, &'static str> {
    let mut device = QemuAtaDevice::initialize()?;
    let filesystem = super::filesystem::Filesystem::mount(&mut device)?;
    filesystem.read_file(&mut device, TEST_ELF_NAME, output)
}

fn create_test_elf() -> [u8; TEST_ELF_SIZE] {
    let mut image = [0; TEST_ELF_SIZE];
    image[..7].copy_from_slice(&[0x7f, b'E', b'L', b'F', 2, 1, 1]);
    write_u16(&mut image, 16, 3);
    write_u16(&mut image, 18, 62);
    write_u32(&mut image, 20, 1);
    write_u64(&mut image, 24, 0);
    write_u64(&mut image, 32, 64);
    write_u16(&mut image, 52, 64);
    write_u16(&mut image, 54, 56);
    write_u16(&mut image, 56, 1);

    write_u32(&mut image, 64, 1);
    write_u32(&mut image, 68, 5);
    write_u64(&mut image, 72, 120);
    write_u64(&mut image, 80, 0);
    write_u64(&mut image, 96, TEST_ELF_CODE.len() as u64);
    write_u64(&mut image, 104, SECTOR_SIZE as u64);
    write_u64(&mut image, 112, 1);
    image[120..].copy_from_slice(&TEST_ELF_CODE);
    image
}

const fn create_runtime_test_payload() -> [u8; RUNTIME_TEST_SIZE] {
    let mut payload = [0; RUNTIME_TEST_SIZE];
    let mut index = 0;
    while index < RUNTIME_TEST_SIZE {
        payload[index] = (index.wrapping_mul(37) ^ (index >> 3)) as u8;
        index += 1;
    }
    payload
}

fn write_u16(output: &mut [u8], offset: usize, value: u16) {
    output[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
}

fn write_u32(output: &mut [u8], offset: usize, value: u32) {
    output[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn write_u64(output: &mut [u8], offset: usize, value: u64) {
    output[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
}

pub(crate) fn read_named_file(name: &str, output: &mut [u8]) -> Result<usize, &'static str> {
    let mut device = QemuAtaDevice::initialize()?;
    let filesystem = super::filesystem::Filesystem::mount(&mut device)?;
    filesystem.read_file(&mut device, name, output)
}

pub(crate) fn write_named_file(name: &str, contents: &[u8]) -> Result<(), &'static str> {
    let mut device = QemuAtaDevice::initialize()?;
    let filesystem = super::filesystem::Filesystem::mount(&mut device)?;
    filesystem.write_file(&mut device, name, contents)
}

pub(crate) fn expected_boot_json() -> &'static [u8] {
    BOOT_JSON_CONTENT
}

struct QemuAtaDevice {
    sector_count: u32,
}

impl QemuAtaDevice {
    fn initialize() -> Result<Self, &'static str> {
        select_test_disk()?;
        Ok(Self {
            sector_count: DEVICE_SECTORS,
        })
    }

    fn validate_lba(&self, lba: u32) -> Result<(), &'static str> {
        if lba >= self.sector_count {
            return Err("ATA test disk sector is outside the configured QEMU image");
        }
        Ok(())
    }
}

impl BlockDevice for QemuAtaDevice {
    fn sector_count(&self) -> u32 {
        self.sector_count
    }

    fn read_sector(&mut self, lba: u32, sector: &mut Sector) -> Result<(), &'static str> {
        self.validate_lba(lba)?;
        read_sector(lba, sector)
    }

    fn write_sector(&mut self, lba: u32, sector: &Sector) -> Result<(), &'static str> {
        self.validate_lba(lba)?;
        write_sector(lba, sector)
    }

    fn flush(&mut self) -> Result<(), &'static str> {
        unsafe {
            port_write(STATUS_COMMAND_PORT, FLUSH_CACHE);
        }
        delay_400ns();
        wait_not_busy()
    }
}

fn verify_device_bounds(device: &dyn BlockDevice) -> Result<(), &'static str> {
    if device.sector_count() != DEVICE_SECTORS {
        return Err("QEMU block device reported an unexpected image capacity");
    }
    if TEST_LBA >= device.sector_count() {
        return Err("persistent test sector is outside the block device");
    }
    Ok(())
}

fn select_test_disk() -> Result<(), &'static str> {
    unsafe {
        port_write(CONTROL_PORT, 0x02);
        port_write(DRIVE_PORT, 0xe0);
        port_write(SECTOR_COUNT_PORT, 0);
        port_write(LBA_LOW_PORT, 0);
        port_write(LBA_MID_PORT, 0);
        port_write(LBA_HIGH_PORT, 0);
    }
    delay_400ns();
    wait_not_busy()
}

fn read_sector(lba: u32, sector: &mut [u8; SECTOR_SIZE]) -> Result<(), &'static str> {
    issue_sector_command(lba, READ_SECTORS)?;
    wait_data_ready()?;
    for word_index in 0..SECTOR_SIZE / 2 {
        let word = unsafe { port_read_u16(DATA_PORT) }.to_le_bytes();
        sector[word_index * 2] = word[0];
        sector[word_index * 2 + 1] = word[1];
    }
    wait_not_busy()
}

fn write_sector(lba: u32, sector: &[u8; SECTOR_SIZE]) -> Result<(), &'static str> {
    issue_sector_command(lba, WRITE_SECTORS)?;
    wait_data_ready()?;
    for word_index in 0..SECTOR_SIZE / 2 {
        let word = u16::from_le_bytes([sector[word_index * 2], sector[word_index * 2 + 1]]);
        unsafe {
            port_write_u16(DATA_PORT, word);
        }
    }
    wait_not_busy()
}

fn issue_sector_command(lba: u32, command: u8) -> Result<(), &'static str> {
    if lba >= 1 << 28 {
        return Err("test LBA is outside ATA 28-bit addressing");
    }
    wait_not_busy()?;
    unsafe {
        port_write(DRIVE_PORT, 0xe0 | ((lba >> 24) as u8 & 0x0f));
        port_write(SECTOR_COUNT_PORT, 1);
        port_write(LBA_LOW_PORT, lba as u8);
        port_write(LBA_MID_PORT, (lba >> 8) as u8);
        port_write(LBA_HIGH_PORT, (lba >> 16) as u8);
        port_write(STATUS_COMMAND_PORT, command);
    }
    delay_400ns();
    Ok(())
}

fn wait_data_ready() -> Result<(), &'static str> {
    for _ in 0..1_000_000 {
        let status = unsafe { port_read(STATUS_COMMAND_PORT) };
        if status == 0xff {
            return Err("QEMU test disk is not present on the secondary IDE channel");
        }
        if status & STATUS_BUSY == 0 {
            if status & STATUS_ERROR != 0 {
                let error = unsafe { port_read(ERROR_FEATURES_PORT) };
                return if error & (1 << 2) != 0 {
                    Err("ATA test disk reported an aborted command")
                } else {
                    Err("ATA test disk reported an I/O error")
                };
            }
            if status & STATUS_DATA_READY != 0 {
                return Ok(());
            }
        }
        core::hint::spin_loop();
    }
    Err("timed out waiting for ATA data")
}

fn wait_not_busy() -> Result<(), &'static str> {
    for _ in 0..1_000_000 {
        let status = unsafe { port_read(STATUS_COMMAND_PORT) };
        if status == 0xff {
            return Err("QEMU test disk is not present on the secondary IDE channel");
        }
        if status & STATUS_BUSY == 0 {
            if status & STATUS_ERROR != 0 {
                let error = unsafe { port_read(ERROR_FEATURES_PORT) };
                return if error & (1 << 2) != 0 {
                    Err("ATA test disk reported an aborted command")
                } else {
                    Err("ATA test disk reported an I/O error")
                };
            }
            return Ok(());
        }
        core::hint::spin_loop();
    }
    Err("timed out waiting for ATA test disk")
}

fn delay_400ns() {
    unsafe {
        for _ in 0..4 {
            let _ = port_read(CONTROL_PORT);
        }
    }
}

fn record_hash(data: &[u8]) -> u64 {
    data.iter().fold(0xcbf2_9ce4_8422_2325, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(0x100_0000_01b3)
    })
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
