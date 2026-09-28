use super::block_device::{BlockDevice, SECTOR_SIZE, Sector};

const SUPERBLOCK_LBA: u32 = 8;
const BITMAP_LBA: u32 = 9;
const ROOT_DIRECTORY_LBA: u32 = 10;
const FIRST_DATA_LBA: u32 = 11;
const DIRECTORY_ENTRY_SIZE: usize = 32;
const MAX_FILE_SECTORS: usize = 512;
pub(crate) const MAX_FILE_SIZE: usize = MAX_FILE_SECTORS * SECTOR_SIZE;
const SUPERBLOCK_MAGIC: &[u8; 8] = b"NOSFS001";
const FILESYSTEM_VERSION: u32 = 2;
const ENTRY_NAME_SIZE: usize = 16;

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
        if u32::from_le_bytes(superblock[8..12].try_into().unwrap()) == 1 {
            Self::upgrade_v1(device, sector_count, &mut superblock)?;
        }
        validate_superblock(&superblock, sector_count)?;

        let mut bitmap = [0; SECTOR_SIZE];
        device.read_sector(BITMAP_LBA, &mut bitmap)?;
        if hash(&bitmap) != u64::from_le_bytes(superblock[16..24].try_into().unwrap()) {
            return Err("filesystem allocation bitmap checksum mismatch");
        }
        validate_bitmap(&bitmap, sector_count)?;
        let root = Self::read_root(device, sector_count)?;
        validate_directory(&root, &bitmap, sector_count)?;
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
        let root = Self::read_root(device, self.sector_count)?;
        validate_directory(&root, &bitmap, self.sector_count)?;
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

    pub(crate) fn write_file(
        &self,
        device: &mut dyn BlockDevice,
        name: &str,
        contents: &[u8],
    ) -> Result<(), &'static str> {
        validate_name(name)?;
        let sectors_needed = sectors_for_length(contents.len())?;
        let bitmap = self.read_bitmap(device)?;
        let mut root = Self::read_root(device, self.sector_count)?;
        validate_directory(&root, &bitmap, self.sector_count)?;

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

    fn read_root(device: &mut dyn BlockDevice, sector_count: u32) -> Result<Sector, &'static str> {
        let mut superblock = [0; SECTOR_SIZE];
        let mut root = [0; SECTOR_SIZE];
        device.read_sector(SUPERBLOCK_LBA, &mut superblock)?;
        device.read_sector(ROOT_DIRECTORY_LBA, &mut root)?;
        validate_superblock(&superblock, sector_count)?;
        if hash(&root) != u64::from_le_bytes(superblock[32..40].try_into().unwrap()) {
            return Err("filesystem root directory checksum mismatch");
        }
        Ok(root)
    }

    fn write_root(&self, device: &mut dyn BlockDevice, root: &Sector) -> Result<(), &'static str> {
        let mut superblock = [0; SECTOR_SIZE];
        device.read_sector(SUPERBLOCK_LBA, &mut superblock)?;
        validate_superblock(&superblock, self.sector_count)?;
        device.write_sector(ROOT_DIRECTORY_LBA, root)?;
        device.flush()?;
        superblock[32..40].copy_from_slice(&hash(root).to_le_bytes());
        let checksum = hash(&superblock[..40]);
        superblock[40..48].copy_from_slice(&checksum.to_le_bytes());
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
        let checksum = hash(&superblock[..40]);
        superblock[40..48].copy_from_slice(&checksum.to_le_bytes());
        device.write_sector(SUPERBLOCK_LBA, &superblock)?;
        device.flush()
    }

    fn format_if_blank(
        device: &mut dyn BlockDevice,
        sector_count: u32,
    ) -> Result<(), &'static str> {
        let mut bitmap = [0; SECTOR_SIZE];
        let mut root = [0; SECTOR_SIZE];
        device.read_sector(BITMAP_LBA, &mut bitmap)?;
        device.read_sector(ROOT_DIRECTORY_LBA, &mut root)?;
        if bitmap.iter().any(|byte| *byte != 0) || root.iter().any(|byte| *byte != 0) {
            return Err("filesystem metadata is not formatted; refusing to overwrite it");
        }

        for lba in 0..FIRST_DATA_LBA {
            set_bit(&mut bitmap, lba, true)?;
        }
        device.write_sector(BITMAP_LBA, &bitmap)?;
        device.write_sector(ROOT_DIRECTORY_LBA, &root)?;
        device.flush()?;

        let mut superblock = [0; SECTOR_SIZE];
        superblock[..8].copy_from_slice(SUPERBLOCK_MAGIC);
        superblock[8..12].copy_from_slice(&FILESYSTEM_VERSION.to_le_bytes());
        superblock[12..16].copy_from_slice(&sector_count.to_le_bytes());
        superblock[16..24].copy_from_slice(&hash(&bitmap).to_le_bytes());
        superblock[32..40].copy_from_slice(&hash(&root).to_le_bytes());
        let checksum = hash(&superblock[..40]);
        superblock[40..48].copy_from_slice(&checksum.to_le_bytes());
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
        device.read_sector(ROOT_DIRECTORY_LBA, &mut root)?;
        if hash(&bitmap) != u64::from_le_bytes(superblock[16..24].try_into().unwrap()) {
            return Err("legacy filesystem bitmap checksum mismatch; refusing migration");
        }
        validate_bitmap(&bitmap, sector_count)?;
        validate_directory(&root, &bitmap, sector_count)?;

        superblock[8..12].copy_from_slice(&FILESYSTEM_VERSION.to_le_bytes());
        superblock[32..40].copy_from_slice(&hash(&root).to_le_bytes());
        let checksum = hash(&superblock[..40]);
        superblock[40..48].copy_from_slice(&checksum.to_le_bytes());
        device.write_sector(SUPERBLOCK_LBA, superblock)?;
        device.flush()
    }
}

fn validate_superblock(superblock: &Sector, sector_count: u32) -> Result<(), &'static str> {
    if &superblock[..8] != SUPERBLOCK_MAGIC {
        return Err("filesystem superblock has an unknown format");
    }
    if u32::from_le_bytes(superblock[8..12].try_into().unwrap()) != FILESYSTEM_VERSION {
        return Err("filesystem version is unsupported");
    }
    if u32::from_le_bytes(superblock[12..16].try_into().unwrap()) != sector_count {
        return Err("filesystem size does not match the block device");
    }
    if hash(&superblock[..40]) != u64::from_le_bytes(superblock[40..48].try_into().unwrap()) {
        return Err("filesystem superblock checksum mismatch");
    }
    Ok(())
}

fn validate_directory(
    root: &Sector,
    bitmap: &Sector,
    sector_count: u32,
) -> Result<(), &'static str> {
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
            let end = start + sectors as u32;
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

fn find_entry(root: &Sector, name: &str) -> Result<Option<usize>, &'static str> {
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
    data.iter().fold(0xcbf2_9ce4_8422_2325, |value, byte| {
        (value ^ u64::from(*byte)).wrapping_mul(0x100_0000_01b3)
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
