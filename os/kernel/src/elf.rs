use super::address_space::AddressSpace;

const ELF_HEADER_SIZE: usize = 64;
const PROGRAM_HEADER_SIZE: usize = 56;
const MAX_PROGRAM_HEADERS: usize = 4;
const MAX_IMAGE_SIZE: usize = 8192;
const MAX_LOAD_PAGES: usize = 16;
const PAGE_SIZE: u64 = 4096;
const ET_EXEC: u16 = 2;
const ET_DYN: u16 = 3;
const EM_X86_64: u16 = 62;
const PT_LOAD: u32 = 1;
const PF_X: u32 = 1;
const PF_W: u32 = 2;
const PF_R: u32 = 4;

#[derive(Clone, Copy)]
struct LoadSegment {
    file_offset: usize,
    virtual_address: u64,
    file_size: usize,
    memory_size: usize,
    flags: u32,
}

pub(crate) struct LoadedImage {
    pub(crate) entry: u64,
    pub(crate) load_bias: u64,
}

pub(crate) fn load(
    address_space: &mut AddressSpace,
    image: &[u8],
    dynamic_base: u64,
) -> Result<LoadedImage, &'static str> {
    if image.len() < ELF_HEADER_SIZE || image.len() > MAX_IMAGE_SIZE {
        return Err("ELF image size is outside the supported bounds");
    }
    if image[..4] != [0x7f, b'E', b'L', b'F'] || image[4] != 2 || image[5] != 1 || image[6] != 1 {
        return Err("ELF image must use the ELF64 little-endian current-version format");
    }
    let elf_type = read_u16(image, 16)?;
    if !matches!(elf_type, ET_EXEC | ET_DYN) || read_u16(image, 18)? != EM_X86_64 {
        return Err("ELF image must be a static x86_64 executable or shared-object image");
    }
    if read_u32(image, 20)? != 1 || read_u16(image, 52)? as usize != ELF_HEADER_SIZE {
        return Err("ELF header version or size is invalid");
    }
    let entry = read_u64(image, 24)?;
    let program_offset = usize::try_from(read_u64(image, 32)?)
        .map_err(|_| "ELF program-header offset is too large")?;
    let program_entry_size = read_u16(image, 54)? as usize;
    let program_count = read_u16(image, 56)? as usize;
    if program_entry_size != PROGRAM_HEADER_SIZE
        || program_count == 0
        || program_count > MAX_PROGRAM_HEADERS
    {
        return Err("ELF program-header table has an unsupported size or count");
    }
    let table_size = program_entry_size
        .checked_mul(program_count)
        .ok_or("ELF program-header table size overflow")?;
    let table_end = program_offset
        .checked_add(table_size)
        .ok_or("ELF program-header table range overflow")?;
    if program_offset < ELF_HEADER_SIZE || table_end > image.len() {
        return Err("ELF program-header table extends beyond the image");
    }

    let load_bias = match elf_type {
        ET_EXEC => 0,
        ET_DYN => dynamic_base,
        _ => return Err("unsupported ELF type"),
    };
    if load_bias % PAGE_SIZE != 0 || load_bias >= (1 << 47) {
        return Err("ELF load base must be page-aligned in user address space");
    }

    let mut segments: [Option<LoadSegment>; MAX_PROGRAM_HEADERS] = [None; MAX_PROGRAM_HEADERS];
    let mut segment_count = 0;
    let mut total_pages = 0usize;
    let mut entry_is_executable = false;
    for index in 0..program_count {
        let header = program_offset + index * program_entry_size;
        let kind = read_u32(image, header)?;
        if kind != PT_LOAD {
            if kind != 0 {
                return Err(
                    "ELF dynamic, interpreter, and auxiliary program headers are unsupported",
                );
            }
            continue;
        }
        let flags = read_u32(image, header + 4)?;
        if flags & !(PF_R | PF_W | PF_X) != 0 || flags & PF_R == 0 {
            return Err("ELF load segment has unsupported or unreadable permissions");
        }
        if flags & PF_W != 0 && flags & PF_X != 0 {
            return Err("ELF writable-executable segments are not supported");
        }

        let file_offset = usize::try_from(read_u64(image, header + 8)?)
            .map_err(|_| "ELF segment file offset is too large")?;
        let virtual_address = read_u64(image, header + 16)?;
        let file_size = usize::try_from(read_u64(image, header + 32)?)
            .map_err(|_| "ELF segment file size is too large")?;
        let memory_size = usize::try_from(read_u64(image, header + 40)?)
            .map_err(|_| "ELF segment memory size is too large")?;
        let alignment = read_u64(image, header + 48)?;
        if memory_size == 0 || file_size > memory_size {
            return Err("ELF load segment has invalid file or memory sizes");
        }
        let file_end = file_offset
            .checked_add(file_size)
            .ok_or("ELF segment file range overflow")?;
        if file_offset < table_end || file_end > image.len() {
            return Err("ELF load segment extends beyond the image");
        }
        if alignment > 1
            && (!alignment.is_power_of_two()
                || file_offset as u64 % alignment != virtual_address % alignment)
        {
            return Err("ELF load segment has invalid alignment");
        }

        let start = load_bias
            .checked_add(virtual_address)
            .ok_or("ELF segment load address overflow")?;
        let end_relative = virtual_address
            .checked_add(memory_size as u64)
            .ok_or("ELF relative segment memory range overflow")?;
        let end = start
            .checked_add(memory_size as u64)
            .ok_or("ELF segment memory range overflow")?;
        if start < load_bias || end > (1 << 47) || start < (1 << 20) {
            return Err("ELF load segment is outside the supported user address range");
        }
        let first_page = start & !(PAGE_SIZE - 1);
        let last_page = (end - 1) & !(PAGE_SIZE - 1);
        let page_count = ((last_page - first_page) / PAGE_SIZE + 1) as usize;
        total_pages = total_pages
            .checked_add(page_count)
            .ok_or("ELF total mapped page count overflow")?;
        if total_pages > MAX_LOAD_PAGES {
            return Err("ELF image requires too many load pages");
        }
        for previous in segments.iter().flatten() {
            let previous_start = load_bias + previous.virtual_address;
            let previous_end = previous_start + previous.memory_size as u64;
            let previous_first_page = previous_start & !(PAGE_SIZE - 1);
            let previous_last_page = (previous_end - 1) & !(PAGE_SIZE - 1);
            if (start < previous_end && previous_start < end)
                || (first_page <= previous_last_page && previous_first_page <= last_page)
            {
                return Err("ELF load segments overlap in bytes or mapped pages");
            }
        }
        if flags & PF_X != 0 && entry >= virtual_address && entry < end_relative {
            entry_is_executable = true;
        }
        if segment_count >= segments.len() {
            return Err("ELF image contains too many loadable segments");
        }
        segments[segment_count] = Some(LoadSegment {
            file_offset,
            virtual_address,
            file_size,
            memory_size,
            flags,
        });
        segment_count += 1;
    }
    if segment_count == 0 || !entry_is_executable {
        return Err("ELF image has no loadable segment containing its entry point");
    }

    for segment in segments.iter().flatten() {
        let start = load_bias + segment.virtual_address;
        let end = start + segment.memory_size as u64;
        let first_page = start & !(PAGE_SIZE - 1);
        let last_page = (end - 1) & !(PAGE_SIZE - 1);
        let mut page = first_page;
        loop {
            super::address_space::map_user_page_for_elf(address_space, page)?;
            if page == last_page {
                break;
            }
            page = page
                .checked_add(PAGE_SIZE)
                .ok_or("ELF page mapping address overflow")?;
        }
    }

    for segment in segments.iter().flatten() {
        let destination = load_bias + segment.virtual_address;
        let file_end = segment
            .file_offset
            .checked_add(segment.file_size)
            .ok_or("ELF segment file range overflow")?;
        if segment.file_size > 0 {
            super::address_space::copy_to_user(destination, &image[segment.file_offset..file_end])?;
        }
        let zero_start = destination
            .checked_add(segment.file_size as u64)
            .ok_or("ELF zero-fill address overflow")?;
        let zero_length = segment.memory_size - segment.file_size;
        if zero_length > 0 {
            super::address_space::zero_user_range(zero_start, zero_length)?;
        }
        let start = load_bias + segment.virtual_address;
        let end = start + segment.memory_size as u64;
        let first_page = start & !(PAGE_SIZE - 1);
        let last_page = (end - 1) & !(PAGE_SIZE - 1);
        let mut page = first_page;
        loop {
            super::address_space::set_user_page_permissions(
                page,
                segment.flags & PF_W != 0,
                segment.flags & PF_X != 0,
            )?;
            if page == last_page {
                break;
            }
            page = page
                .checked_add(PAGE_SIZE)
                .ok_or("ELF protection page address overflow")?;
        }
    }

    let loaded_entry = load_bias
        .checked_add(entry)
        .ok_or("ELF entry-point address overflow")?;
    Ok(LoadedImage {
        entry: loaded_entry,
        load_bias,
    })
}

fn read_u16(image: &[u8], offset: usize) -> Result<u16, &'static str> {
    let bytes = image
        .get(offset..offset.checked_add(2).ok_or("ELF field range overflow")?)
        .ok_or("ELF field extends beyond the image")?;
    Ok(u16::from_le_bytes([bytes[0], bytes[1]]))
}

fn read_u32(image: &[u8], offset: usize) -> Result<u32, &'static str> {
    let bytes = image
        .get(offset..offset.checked_add(4).ok_or("ELF field range overflow")?)
        .ok_or("ELF field extends beyond the image")?;
    Ok(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn read_u64(image: &[u8], offset: usize) -> Result<u64, &'static str> {
    let bytes = image
        .get(offset..offset.checked_add(8).ok_or("ELF field range overflow")?)
        .ok_or("ELF field extends beyond the image")?;
    Ok(u64::from_le_bytes([
        bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
    ]))
}
