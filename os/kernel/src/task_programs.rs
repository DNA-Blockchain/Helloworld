//! Small position-independent ring-3 programs used by the workflow boot
//! tests, wrapped as static `ET_DYN` ELF images for `elf::load`.

use alloc::vec::Vec;

const STACK_BUFFER_BYTES: [u8; 4] = 0x400u32.to_le_bytes();

/// Wraps position-independent machine code in a single read+execute
/// `PT_LOAD` segment.
pub(crate) fn build_static_elf(code: &[u8]) -> Vec<u8> {
    let mut image = Vec::new();
    image.resize(120 + code.len(), 0);
    image[..7].copy_from_slice(&[0x7f, b'E', b'L', b'F', 2, 1, 1]);
    image[16..18].copy_from_slice(&3u16.to_le_bytes());
    image[18..20].copy_from_slice(&62u16.to_le_bytes());
    image[20..24].copy_from_slice(&1u32.to_le_bytes());
    image[32..40].copy_from_slice(&64u64.to_le_bytes());
    image[52..54].copy_from_slice(&64u16.to_le_bytes());
    image[54..56].copy_from_slice(&56u16.to_le_bytes());
    image[56..58].copy_from_slice(&1u16.to_le_bytes());

    image[64..68].copy_from_slice(&1u32.to_le_bytes());
    image[68..72].copy_from_slice(&5u32.to_le_bytes());
    image[72..80].copy_from_slice(&120u64.to_le_bytes());
    image[96..104].copy_from_slice(&(code.len() as u64).to_le_bytes());
    image[104..112].copy_from_slice(&(code.len() as u64).to_le_bytes());
    image[112..120].copy_from_slice(&1u64.to_le_bytes());
    image[120..].copy_from_slice(code);
    image
}

/// Reads `input` (syscall 2) into a 1-KiB stack buffer, then writes it to
/// stdout (syscall 3) or to the `output` file (syscall 13) and exits 0.
/// Exits 1 if the file is empty or any syscall fails.
pub(crate) fn copy_program(input: &str, output: Option<&str>) -> Vec<u8> {
    let mut code = Vec::new();
    let mut fail_jumps = Vec::new();
    let mut name_references = Vec::new();

    code.extend_from_slice(&[0x48, 0x81, 0xec]); // sub rsp, 0x400
    code.extend_from_slice(&STACK_BUFFER_BYTES);
    code.extend_from_slice(&[0x48, 0x8d, 0x3d]); // lea rdi, [rip + input]
    name_references.push((code.len(), 0));
    code.extend_from_slice(&[0; 4]);
    code.extend_from_slice(&[0x48, 0x89, 0xe6]); // mov rsi, rsp
    code.push(0xba); // mov edx, 0x400
    code.extend_from_slice(&STACK_BUFFER_BYTES);
    code.extend_from_slice(&[0xb8, 0x02, 0x00, 0x00, 0x00, 0xcd, 0x80]); // read file
    code.extend_from_slice(&[0x48, 0x83, 0xf8, 0xfe, 0x0f, 0x84]); // cmp rax, -2; je fail
    fail_jumps.push(code.len());
    code.extend_from_slice(&[0; 4]);
    code.extend_from_slice(&[0x48, 0x85, 0xc0, 0x0f, 0x84]); // test rax, rax; je fail
    fail_jumps.push(code.len());
    code.extend_from_slice(&[0; 4]);
    match output {
        None => {
            code.extend_from_slice(&[0x48, 0x89, 0xc6]); // mov rsi, rax
            code.extend_from_slice(&[0x48, 0x89, 0xe7]); // mov rdi, rsp
            code.extend_from_slice(&[0xb8, 0x03, 0x00, 0x00, 0x00, 0xcd, 0x80]); // stdout
        }
        Some(_) => {
            code.extend_from_slice(&[0x48, 0x89, 0xc2]); // mov rdx, rax
            code.extend_from_slice(&[0x48, 0x89, 0xe6]); // mov rsi, rsp
            code.extend_from_slice(&[0x48, 0x8d, 0x3d]); // lea rdi, [rip + output]
            name_references.push((code.len(), 1));
            code.extend_from_slice(&[0; 4]);
            code.extend_from_slice(&[0xb8, 0x0d, 0x00, 0x00, 0x00, 0xcd, 0x80]); // write file
        }
    }
    code.extend_from_slice(&[0x48, 0x83, 0xf8, 0xfe, 0x0f, 0x84]); // cmp rax, -2; je fail
    fail_jumps.push(code.len());
    code.extend_from_slice(&[0; 4]);
    code.extend_from_slice(&[
        0xb8, 0x01, 0x00, 0x00, 0x00, 0x31, 0xff, 0xcd, 0x80, 0x0f, 0x0b,
    ]); // exit 0
    let fail = code.len();
    code.extend_from_slice(&[
        0xb8, 0x01, 0x00, 0x00, 0x00, 0xbf, 0x01, 0x00, 0x00, 0x00, 0xcd, 0x80, 0x0f, 0x0b,
    ]); // exit 1

    let mut name_offsets = [0; 2];
    for (index, name) in [Some(input), output].into_iter().enumerate() {
        if let Some(name) = name {
            name_offsets[index] = code.len();
            code.extend_from_slice(name.as_bytes());
            code.push(0);
        }
    }
    for at in fail_jumps {
        patch_rel32(&mut code, at, fail);
    }
    for (at, index) in name_references {
        patch_rel32(&mut code, at, name_offsets[index]);
    }
    build_static_elf(&code)
}

/// `jmp $`: never exits, so only the runtime limit can stop it.
pub(crate) fn spin_program() -> Vec<u8> {
    build_static_elf(&[0xeb, 0xfe])
}

fn patch_rel32(code: &mut [u8], at: usize, target: usize) {
    let relative = target as i32 - (at as i32 + 4);
    code[at..at + 4].copy_from_slice(&relative.to_le_bytes());
}
