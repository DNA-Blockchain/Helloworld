use super::block_device::{BlockDevice, SECTOR_SIZE, Sector};
use core::cell::UnsafeCell;
use core::ops::{Deref, DerefMut};
use core::sync::atomic::{AtomicBool, Ordering};

const SUPERBLOCK_LBA: u32 = 8;
const BITMAP_LBA: u32 = 9;
/// Versions 1 and 2 kept a one-sector (16-entry) root directory here.
/// Version 3 leaves it reserved and records a larger directory extent in
/// the superblock.
const LEGACY_ROOT_DIRECTORY_LBA: u32 = 10;
const FIRST_DATA_LBA: u32 = 11;
const DIRECTORY_ENTRY_SIZE: usize = 32;
const ROOT_DIRECTORY_SECTORS: usize = 8;
pub(crate) const MAX_DIRECTORY_ENTRIES: usize =
    ROOT_DIRECTORY_SECTORS * SECTOR_SIZE / DIRECTORY_ENTRY_SIZE;
const MAX_FILE_SECTORS: usize = 512;
pub(crate) const MAX_FILE_SIZE: usize = MAX_FILE_SECTORS * SECTOR_SIZE;
const SUPERBLOCK_MAGIC: &[u8; 8] = b"NOSFS001";
const FILESYSTEM_VERSION: u32 = 3;
const ENTRY_NAME_SIZE: usize = 16;

// Superblock (version 3): 0..8 magic, 8..12 version, 12..16 sector count,
// 16..24 bitmap hash, 24..32 unused (version-1 checksum), 32..40 root
// directory hash, 40..48 checksum over 0..40 and 48..56, 48..52 root
// directory start LBA, 52..56 root directory sector count.

type RootExtent = (u32, usize);

const ROOT_DIRECTORY_BYTES: usize = ROOT_DIRECTORY_SECTORS * SECTOR_SIZE;

// The filesystem runs before the kernel heap exists and from the syscall
// stack, so the 4-KiB directory lives in one static buffer. Filesystem calls
// never nest; the guard turns an accidental nested use into an error.
struct DirectoryBuffer(UnsafeCell<[u8; ROOT_DIRECTORY_BYTES]>);

unsafe impl Sync for DirectoryBuffer {}

static DIRECTORY_BUFFER: DirectoryBuffer =
    DirectoryBuffer(UnsafeCell::new([0; ROOT_DIRECTORY_BYTES]));
static DIRECTORY_BUFFER_IN_USE: AtomicBool = AtomicBool::new(false);

struct Directory;

impl Deref for Directory {
    type Target = [u8];

    fn deref(&self) -> &[u8] {
        unsafe { &*DIRECTORY_BUFFER.0.get() }
    }
}

impl DerefMut for Directory {
    fn deref_mut(&mut self) -> &mut [u8] {
        unsafe { &mut *DIRECTORY_BUFFER.0.get() }
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        DIRECTORY_BUFFER_IN_USE.store(false, Ordering::Release);
    }
}

pub(crate) struct Filesystem {
    sector_count: u32,
}

impl Filesystem {
    pub(crate) fn mount(device: &mut dyn BlockDevice) -> Result<Self, &'static str> {
        let sector_count = device.sector_count();
        if sector_count <= FIRST_DATA_LBA || sector_count > (SECTOR_SIZE * 8) as u32 {
            return Err("block-device capacity is outside the supported filesystem range");
        }

        let mut superblock = [0; SECTOR_SIZE];
        device.read_sector(SUPERBLOCK_LBA, &mut superblock)?;
        if superblock.iter().all(|byte| *byte == 0) {
            Self::format_if_blank(device, sector_count)?;
            device.read_sector(SUPERBLOCK_LBA, &mut superblock)?;
        }
        if version(&superblock) == 1 {
            Self::upgrade_v1(device, sector_count, &mut superblock)?;
        }
        if version(&superblock) == 2 {
            Self::upgrade_v2(device, sector_count, &mut superblock)?;
        }
        validate_superblock(&superblock, sector_count)?;

        let mut bitmap = [0; SECTOR_SIZE];
        device.read_sector(BITMAP_LBA, &mut bitmap)?;
        if hash(&bitmap) != u64::from_le_bytes(superblock[16..24].try_into().unwrap()) {
            return Err("filesystem allocation bitmap checksum mismatch");
        }
        validate_bitmap(&bitmap, sector_count)?;
        let (root, extent) = Self::read_root(device, sector_count)?;
        validate_directory(&root, &bitmap, sector_count, extent)?;
        Ok(Self { sector_count })
    }

    pub(crate) fn read_file(
        &self,
        device: &mut dyn BlockDevice,
        name: &str,
        output: &mut [u8],
    ) -> Result<usize, &'static str> {
        validate_name(name)?;
        let bitmap = self.read_bitmap(device)?;
        let (root, extent) = Self::read_root(device, self.sector_count)?;
        validate_directory(&root, &bitmap, self.sector_count, extent)?;
        let entry_index = find_entry(&root, name)?.ok_or("filesystem file does not exist")?;
        let entry = &root[entry_index * DIRECTORY_ENTRY_SIZE..][..DIRECTORY_ENTRY_SIZE];
        let start = u32::from_le_bytes(entry[16..20].try_into().unwrap());
        let length = u32::from_le_bytes(entry[20..24].try_into().unwrap()) as usize;
        let expected_hash = u64::from_le_bytes(entry[24..32].try_into().unwrap());
        if length > output.len() {
            return Err("filesystem output buffer is too small for the file");
        }
        let sectors = sectors_for_length(length)?;
        validate_extent(start, sectors, &bitmap, self.sector_count)?;
        let mut copied = 0;
        for offset in 0..sectors {
            let mut sector = [0; SECTOR_SIZE];
            device.read_sector(start + offset as u32, &mut sector)?;
            let count = (length - copied).min(SECTOR_SIZE);
            output[copied..copied + count].copy_from_slice(&sector[..count]);
            copied += count;
        }
        if hash(&output[..length]) != expected_hash {
            return Err("filesystem file checksum mismatch");
        }
        Ok(length)
    }

    /// Removes a file: clears its directory entry first, then frees its
    /// extent, so an interruption can leak sectors but never leave an entry
    /// pointing at free space. Returns false if the file did not exist.
    pub(crate) fn delete_file(
        &self,
        device: &mut dyn BlockDevice,
        name: &str,
    ) -> Result<bool, &'static str> {
        validate_name(name)?;
        let mut bitmap = self.read_bitmap(device)?;
        let (mut root, extent) = Self::read_root(device, self.sector_count)?;
        validate_directory(&root, &bitmap, self.sector_count, extent)?;
        let Some(entry_index) = find_entry(&root, name)? else {
            return Ok(false);
        };
        let entry = &mut root[entry_index * DIRECTORY_ENTRY_SIZE..][..DIRECTORY_ENTRY_SIZE];
        let start = u32::from_le_bytes(entry[16..20].try_into().unwrap());
        let length = u32::from_le_bytes(entry[20..24].try_into().unwrap()) as usize;
        let sectors = sectors_for_length(length)?;
        entry.fill(0);
        self.write_root(device, &root)?;
        mark_extent(&mut bitmap, start, sectors, false)?;
        self.write_bitmap(device, &bitmap)?;
        Ok(true)
    }

    pub(crate) fn write_file(
        &self,
        device: &mut dyn BlockDevice,
        name: &str,
        contents: &[u8],
    ) -> Result<(), &'static str> {
        validate_name(name)?;
        let sectors_needed = sectors_for_length(contents.len())?;
        let bitmap = self.read_bitmap(device)?;
        let (mut root, extent) = Self::read_root(device, self.sector_count)?;
        validate_directory(&root, &bitmap, self.sector_count, extent)?;

        let existing = find_entry(&root, name)?;
        let entry_index = match existing {
            Some(index) => index,
            None => root
                .chunks_exact(DIRECTORY_ENTRY_SIZE)
                .position(|entry| entry[..ENTRY_NAME_SIZE].iter().all(|byte| *byte == 0))
                .ok_or("filesystem root directory is full")?,
        };
        let old_extent = match existing {
            Some(index) => {
                let entry = &root[index * DIRECTORY_ENTRY_SIZE..][..DIRECTORY_ENTRY_SIZE];
                let start = u32::from_le_bytes(entry[16..20].try_into().unwrap());
                let length = u32::from_le_bytes(entry[20..24].try_into().unwrap()) as usize;
                Some((start, sectors_for_length(length)?))
            }
            None => None,
        };

        let mut allocation_bitmap = bitmap;
        let start = allocate_extent(&mut allocation_bitmap, sectors_needed, self.sector_count)?;
        write_contents(device, start, contents, sectors_needed)?;
        device.flush()?;
        self.write_bitmap(device, &allocation_bitmap)?;

        let entry = &mut root[entry_index * DIRECTORY_ENTRY_SIZE..][..DIRECTORY_ENTRY_SIZE];
        entry.fill(0);
        entry[..name.len()].copy_from_slice(name.as_bytes());
        entry[16..20].copy_from_slice(&start.to_le_bytes());
        entry[20..24].copy_from_slice(&(contents.len() as u32).to_le_bytes());
        entry[24..32].copy_from_slice(&hash(contents).to_le_bytes());
        self.write_root(device, &root)?;

        if let Some((old_start, old_count)) = old_extent {
            mark_extent(&mut allocation_bitmap, old_start, old_count, false)?;
            self.write_bitmap(device, &allocation_bitmap)?;
        }
        Ok(())
    }

    fn read_bitmap(&self, device: &mut dyn BlockDevice) -> Result<Sector, &'static str> {
        let mut superblock = [0; SECTOR_SIZE];
        let mut bitmap = [0; SECTOR_SIZE];
        device.read_sector(SUPERBLOCK_LBA, &mut superblock)?;
        device.read_sector(BITMAP_LBA, &mut bitmap)?;
        validate_superblock(&superblock, self.sector_count)?;
        if hash(&bitmap) != u64::from_le_bytes(superblock[16..24].try_into().unwrap()) {
            return Err("filesystem allocation bitmap checksum mismatch");
        }
        validate_bitmap(&bitmap, self.sector_count)?;
        Ok(bitmap)
    }

    /// Reads the multi-sector root directory into the shared directory buffer.
    fn read_root(
        device: &mut dyn BlockDevice,
        sector_count: u32,
    ) -> Result<(Directory, RootExtent), &'static str> {
        let mut superblock = [0; SECTOR_SIZE];
        device.read_sector(SUPERBLOCK_LBA, &mut superblock)?;
        validate_superblock(&superblock, sector_count)?;
        let extent = root_extent(&superblock);
        let root = read_sectors(device, extent)?;
        if hash(&root) != u64::from_le_bytes(superblock[32..40].try_into().unwrap()) {
            return Err("filesystem root directory checksum mismatch");
        }
        Ok((root, extent))
    }

    fn write_root(&self, device: &mut dyn BlockDevice, root: &[u8]) -> Result<(), &'static str> {
        let mut superblock = [0; SECTOR_SIZE];
        device.read_sector(SUPERBLOCK_LBA, &mut superblock)?;
        validate_superblock(&superblock, self.sector_count)?;
        write_sectors(device, root_extent(&superblock), root)?;
        device.flush()?;
        superblock[32..40].copy_from_slice(&hash(root).to_le_bytes());
        seal_superblock(&mut superblock);
        device.write_sector(SUPERBLOCK_LBA, &superblock)?;
        device.flush()
    }

    fn write_bitmap(
        &self,
        device: &mut dyn BlockDevice,
        bitmap: &Sector,
    ) -> Result<(), &'static str> {
        let mut superblock = [0; SECTOR_SIZE];
        device.read_sector(SUPERBLOCK_LBA, &mut superblock)?;
        validate_superblock(&superblock, self.sector_count)?;
        device.write_sector(BITMAP_LBA, bitmap)?;
        device.flush()?;
        superblock[16..24].copy_from_slice(&hash(bitmap).to_le_bytes());
        seal_superblock(&mut superblock);
        device.write_sector(SUPERBLOCK_LBA, &superblock)?;
        device.flush()
    }

    fn format_if_blank(
        device: &mut dyn BlockDevice,
        sector_count: u32,
    ) -> Result<(), &'static str> {
        let mut bitmap = [0; SECTOR_SIZE];
        let mut legacy_root = [0; SECTOR_SIZE];
        device.read_sector(BITMAP_LBA, &mut bitmap)?;
        device.read_sector(LEGACY_ROOT_DIRECTORY_LBA, &mut legacy_root)?;
        if bitmap.iter().any(|byte| *byte != 0) || legacy_root.iter().any(|byte| *byte != 0) {
            return Err("filesystem metadata is not formatted; refusing to overwrite it");
        }
        let extent = (FIRST_DATA_LBA, ROOT_DIRECTORY_SECTORS);
        if FIRST_DATA_LBA as usize + ROOT_DIRECTORY_SECTORS > sector_count as usize {
            return Err("block device is too small for the root directory");
        }

        for lba in 0..FIRST_DATA_LBA {
            set_bit(&mut bitmap, lba, true)?;
        }
        mark_extent(&mut bitmap, extent.0, extent.1, true)?;
        let root = zeroed_directory()?;
        write_sectors(device, extent, &root)?;
        device.write_sector(BITMAP_LBA, &bitmap)?;
        device.flush()?;

        let mut superblock = [0; SECTOR_SIZE];
        superblock[..8].copy_from_slice(SUPERBLOCK_MAGIC);
        superblock[8..12].copy_from_slice(&FILESYSTEM_VERSION.to_le_bytes());
        superblock[12..16].copy_from_slice(&sector_count.to_le_bytes());
        superblock[16..24].copy_from_slice(&hash(&bitmap).to_le_bytes());
        superblock[32..40].copy_from_slice(&hash(&root).to_le_bytes());
        superblock[48..52].copy_from_slice(&extent.0.to_le_bytes());
        superblock[52..56].copy_from_slice(&(extent.1 as u32).to_le_bytes());
        seal_superblock(&mut superblock);
        device.write_sector(SUPERBLOCK_LBA, &superblock)?;
        device.flush()
    }

    fn upgrade_v1(
        device: &mut dyn BlockDevice,
        sector_count: u32,
        superblock: &mut Sector,
    ) -> Result<(), &'static str> {
        if &superblock[..8] != SUPERBLOCK_MAGIC
            || u32::from_le_bytes(superblock[12..16].try_into().unwrap()) != sector_count
            || hash(&superblock[..24]) != u64::from_le_bytes(superblock[24..32].try_into().unwrap())
        {
            return Err("legacy filesystem metadata failed validation; refusing migration");
        }

        let mut bitmap = [0; SECTOR_SIZE];
        let mut root = [0; SECTOR_SIZE];
        device.read_sector(BITMAP_LBA, &mut bitmap)?;
        device.read_sector(LEGACY_ROOT_DIRECTORY_LBA, &mut root)?;
        if hash(&bitmap) != u64::from_le_bytes(superblock[16..24].try_into().unwrap()) {
            return Err("legacy filesystem bitmap checksum mismatch; refusing migration");
        }
        validate_bitmap(&bitmap, sector_count)?;
        validate_directory(&root, &bitmap, sector_count, (LEGACY_ROOT_DIRECTORY_LBA, 1))?;

        superblock[8..12].copy_from_slice(&2u32.to_le_bytes());
        superblock[32..40].copy_from_slice(&hash(&root).to_le_bytes());
        let checksum = hash(&superblock[..40]);
        superblock[40..48].copy_from_slice(&checksum.to_le_bytes());
        device.write_sector(SUPERBLOCK_LBA, superblock)?;
        device.flush()
    }

    /// Moves a version-2 16-entry directory into a newly allocated
    /// ROOT_DIRECTORY_SECTORS extent. The new directory and bitmap are
    /// written before the superblock that points at them; like other NOSFS
    /// metadata updates, an interruption between those writes can require
    /// manual recovery.
    fn upgrade_v2(
        device: &mut dyn BlockDevice,
        sector_count: u32,
        superblock: &mut Sector,
    ) -> Result<(), &'static str> {
        if &superblock[..8] != SUPERBLOCK_MAGIC
            || u32::from_le_bytes(superblock[12..16].try_into().unwrap()) != sector_count
            || hash(&superblock[..40]) != u64::from_le_bytes(superblock[40..48].try_into().unwrap())
        {
            return Err("version-2 filesystem metadata failed validation; refusing migration");
        }
        let mut bitmap = [0; SECTOR_SIZE];
        let mut legacy_root = [0; SECTOR_SIZE];
        device.read_sector(BITMAP_LBA, &mut bitmap)?;
        device.read_sector(LEGACY_ROOT_DIRECTORY_LBA, &mut legacy_root)?;
        if hash(&bitmap) != u64::from_le_bytes(superblock[16..24].try_into().unwrap())
            || hash(&legacy_root) != u64::from_le_bytes(superblock[32..40].try_into().unwrap())
        {
            return Err("version-2 filesystem checksum mismatch; refusing migration");
        }
        validate_bitmap(&bitmap, sector_count)?;
        validate_directory(
            &legacy_root,
            &bitmap,
            sector_count,
            (LEGACY_ROOT_DIRECTORY_LBA, 1),
        )?;

        let start = allocate_extent(&mut bitmap, ROOT_DIRECTORY_SECTORS, sector_count)?;
        let extent = (start, ROOT_DIRECTORY_SECTORS);
        let mut root = zeroed_directory()?;
        root[..SECTOR_SIZE].copy_from_slice(&legacy_root);
        write_sectors(device, extent, &root)?;
        device.write_sector(BITMAP_LBA, &bitmap)?;
        device.flush()?;

        superblock[8..12].copy_from_slice(&FILESYSTEM_VERSION.to_le_bytes());
        superblock[16..24].copy_from_slice(&hash(&bitmap).to_le_bytes());
        superblock[32..40].copy_from_slice(&hash(&root).to_le_bytes());
        superblock[48..52].copy_from_slice(&extent.0.to_le_bytes());
        superblock[52..56].copy_from_slice(&(extent.1 as u32).to_le_bytes());
        seal_superblock(superblock);
        device.write_sector(SUPERBLOCK_LBA, superblock)?;
        device.flush()
    }
}

fn version(superblock: &Sector) -> u32 {
    u32::from_le_bytes(superblock[8..12].try_into().unwrap())
}

fn root_extent(superblock: &Sector) -> RootExtent {
    (
        u32::from_le_bytes(superblock[48..52].try_into().unwrap()),
        u32::from_le_bytes(superblock[52..56].try_into().unwrap()) as usize,
    )
}

fn superblock_checksum(superblock: &Sector) -> u64 {
    hash_from(hash(&superblock[..40]), &superblock[48..56])
}

fn seal_superblock(superblock: &mut Sector) {
    let checksum = superblock_checksum(superblock);
    superblock[40..48].copy_from_slice(&checksum.to_le_bytes());
}

fn zeroed_directory() -> Result<Directory, &'static str> {
    DIRECTORY_BUFFER_IN_USE
        .compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
        .map_err(|_| "filesystem directory buffer is already in use")?;
    let mut root = Directory;
    root.fill(0);
    Ok(root)
}

fn read_sectors(
    device: &mut dyn BlockDevice,
    extent: RootExtent,
) -> Result<Directory, &'static str> {
    let mut data = zeroed_directory()?;
    for (index, chunk) in data
        .chunks_exact_mut(SECTOR_SIZE)
        .take(extent.1)
        .enumerate()
    {
        let mut sector = [0; SECTOR_SIZE];
        device.read_sector(extent.0 + index as u32, &mut sector)?;
        chunk.copy_from_slice(&sector);
    }
    Ok(data)
}

fn write_sectors(
    device: &mut dyn BlockDevice,
    extent: RootExtent,
    data: &[u8],
) -> Result<(), &'static str> {
    if data.len() != extent.1 * SECTOR_SIZE {
        return Err("filesystem directory buffer does not match its extent");
    }
    for (index, chunk) in data.chunks_exact(SECTOR_SIZE).enumerate() {
        let mut sector = [0; SECTOR_SIZE];
        sector.copy_from_slice(chunk);
        device.write_sector(extent.0 + index as u32, &sector)?;
    }
    Ok(())
}

fn validate_superblock(superblock: &Sector, sector_count: u32) -> Result<(), &'static str> {
    if &superblock[..8] != SUPERBLOCK_MAGIC {
        return Err("filesystem superblock has an unknown format");
    }
    if version(superblock) != FILESYSTEM_VERSION {
        return Err("filesystem version is unsupported");
    }
    if u32::from_le_bytes(superblock[12..16].try_into().unwrap()) != sector_count {
        return Err("filesystem size does not match the block device");
    }
    if superblock_checksum(superblock) != u64::from_le_bytes(superblock[40..48].try_into().unwrap())
    {
        return Err("filesystem superblock checksum mismatch");
    }
    let (start, sectors) = root_extent(superblock);
    if start < FIRST_DATA_LBA
        || sectors != ROOT_DIRECTORY_SECTORS
        || start as usize + sectors > sector_count as usize
    {
        return Err("filesystem root directory extent is invalid");
    }
    Ok(())
}

fn validate_directory(
    root: &[u8],
    bitmap: &Sector,
    sector_count: u32,
    root_extent: RootExtent,
) -> Result<(), &'static str> {
    let root_end = root_extent.0 + root_extent.1 as u32;
    for lba in root_extent.0..root_end {
        if !get_bit(bitmap, lba)? {
            return Err("filesystem root directory sectors are marked free");
        }
    }
    for (index, entry) in root.chunks_exact(DIRECTORY_ENTRY_SIZE).enumerate() {
        if entry[..ENTRY_NAME_SIZE].iter().all(|byte| *byte == 0) {
            if entry[ENTRY_NAME_SIZE..].iter().any(|byte| *byte != 0) {
                return Err("filesystem directory contains a malformed empty entry");
            }
            continue;
        }
        let name_end = entry[..ENTRY_NAME_SIZE]
            .iter()
            .position(|byte| *byte == 0)
            .unwrap_or(ENTRY_NAME_SIZE);
        if entry[name_end..ENTRY_NAME_SIZE]
            .iter()
            .any(|byte| *byte != 0)
        {
            return Err("filesystem directory filename padding is malformed");
        }
        let name = core::str::from_utf8(&entry[..name_end])
            .map_err(|_| "filesystem directory filename is not valid UTF-8")?;
        validate_name(name)?;
        let start = u32::from_le_bytes(entry[16..20].try_into().unwrap());
        let length = u32::from_le_bytes(entry[20..24].try_into().unwrap()) as usize;
        let sectors = sectors_for_length(length)?;
        validate_extent(start, sectors, bitmap, sector_count)?;
        let end = start + sectors as u32;
        if start < root_end && root_extent.0 < end {
            return Err("filesystem file overlaps the root directory");
        }
        for previous in root[..index * DIRECTORY_ENTRY_SIZE].chunks_exact(DIRECTORY_ENTRY_SIZE) {
            if previous[..ENTRY_NAME_SIZE].iter().all(|byte| *byte == 0) {
                continue;
            }
            let previous_end = previous[..ENTRY_NAME_SIZE]
                .iter()
                .position(|byte| *byte == 0)
                .unwrap_or(ENTRY_NAME_SIZE);
            if previous[..previous_end] == entry[..name_end] {
                return Err("filesystem directory contains a duplicate filename");
            }
            let previous_start = u32::from_le_bytes(previous[16..20].try_into().unwrap());
            let previous_length = u32::from_le_bytes(previous[20..24].try_into().unwrap()) as usize;
            let previous_sectors = sectors_for_length(previous_length)?;
            let previous_end = previous_start + previous_sectors as u32;
            if start < previous_end && previous_start < end {
                return Err("filesystem files have overlapping data extents");
            }
        }
    }
    Ok(())
}

fn validate_bitmap(bitmap: &Sector, sector_count: u32) -> Result<(), &'static str> {
    for lba in 0..FIRST_DATA_LBA {
        if !get_bit(bitmap, lba)? {
            return Err("filesystem metadata sectors are marked free");
        }
    }
    for lba in sector_count..(SECTOR_SIZE * 8) as u32 {
        if get_bit(bitmap, lba)? {
            return Err("filesystem bitmap allocates sectors beyond the block device");
        }
    }
    Ok(())
}

fn find_entry(root: &[u8], name: &str) -> Result<Option<usize>, &'static str> {
    for (index, entry) in root.chunks_exact(DIRECTORY_ENTRY_SIZE).enumerate() {
        let Some(end) = entry[..ENTRY_NAME_SIZE].iter().position(|byte| *byte == 0) else {
            return Err("filesystem directory filename is not null-terminated");
        };
        if end > 0 && &entry[..end] == name.as_bytes() {
            return Ok(Some(index));
        }
    }
    Ok(None)
}

fn validate_name(name: &str) -> Result<(), &'static str> {
    if name.is_empty()
        || name.len() >= ENTRY_NAME_SIZE
        || !name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(
            "filesystem filename must be 1-15 ASCII letters, digits, dot, dash, or underscore",
        );
    }
    Ok(())
}

fn sectors_for_length(length: usize) -> Result<usize, &'static str> {
    if length == 0 || length > MAX_FILE_SECTORS * SECTOR_SIZE {
        return Err("filesystem file length is outside the supported 1-262144 byte range");
    }
    length
        .checked_add(SECTOR_SIZE - 1)
        .map(|rounded| rounded / SECTOR_SIZE)
        .ok_or("filesystem file length overflow")
}

fn validate_extent(
    start: u32,
    count: usize,
    bitmap: &Sector,
    sector_count: u32,
) -> Result<(), &'static str> {
    let end = start
        .checked_add(count as u32)
        .ok_or("filesystem file extent overflow")?;
    if start < FIRST_DATA_LBA || end > sector_count {
        return Err("filesystem file extent is outside the data area");
    }
    for lba in start..end {
        if !get_bit(bitmap, lba)? {
            return Err("filesystem file extent is marked free in the allocation bitmap");
        }
    }
    Ok(())
}

fn allocate_extent(
    bitmap: &mut Sector,
    count: usize,
    sector_count: u32,
) -> Result<u32, &'static str> {
    let mut start = FIRST_DATA_LBA;
    while start
        .checked_add(count as u32)
        .is_some_and(|end| end <= sector_count)
    {
        let mut is_free = true;
        for lba in start..start + count as u32 {
            if get_bit(bitmap, lba)? {
                is_free = false;
                break;
            }
        }
        if is_free {
            mark_extent(bitmap, start, count, true)?;
            return Ok(start);
        }
        start += 1;
    }
    Err("filesystem has no contiguous extent large enough for the file")
}

fn mark_extent(
    bitmap: &mut Sector,
    start: u32,
    count: usize,
    allocated: bool,
) -> Result<(), &'static str> {
    for lba in start..start + count as u32 {
        set_bit(bitmap, lba, allocated)?;
    }
    Ok(())
}

fn set_bit(bitmap: &mut Sector, lba: u32, allocated: bool) -> Result<(), &'static str> {
    let byte = usize::try_from(lba / 8).map_err(|_| "filesystem sector bitmap index overflow")?;
    let mask = 1 << (lba % 8);
    let value = bitmap
        .get_mut(byte)
        .ok_or("filesystem sector is outside the bitmap capacity")?;
    if allocated {
        *value |= mask;
    } else {
        *value &= !mask;
    }
    Ok(())
}

fn get_bit(bitmap: &Sector, lba: u32) -> Result<bool, &'static str> {
    let byte = usize::try_from(lba / 8).map_err(|_| "filesystem sector bitmap index overflow")?;
    let value = bitmap
        .get(byte)
        .ok_or("filesystem sector is outside the bitmap capacity")?;
    Ok(value & (1 << (lba % 8)) != 0)
}

fn write_contents(
    device: &mut dyn BlockDevice,
    start: u32,
    contents: &[u8],
    sector_count: usize,
) -> Result<(), &'static str> {
    let mut written = 0;
    for offset in 0..sector_count {
        let mut sector = [0; SECTOR_SIZE];
        let count = (contents.len() - written).min(SECTOR_SIZE);
        sector[..count].copy_from_slice(&contents[written..written + count]);
        device.write_sector(start + offset as u32, &sector)?;
        written += count;
    }
    Ok(())
}

fn hash(data: &[u8]) -> u64 {
    hash_from(0xcbf2_9ce4_8422_2325, data)
}

fn hash_from(seed: u64, data: &[u8]) -> u64 {
    data.iter().fold(seed, |value, byte| {
        (value ^ u64::from(*byte)).wrapping_mul(0x100_0000_01b3)
    })
}
