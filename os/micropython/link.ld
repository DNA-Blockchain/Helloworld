/* Static ET_DYN layout for the Network OS ELF loader: exactly two PT_LOAD
 * segments (read+execute, read+write), no PT_DYNAMIC or PT_INTERP, and no
 * relocation targets outside the writable segment. _start applies the
 * R_X86_64_RELATIVE entries between __rela_start and __rela_end itself. */

ENTRY(_start)

PHDRS
{
    text PT_LOAD FLAGS(5);
    data PT_LOAD FLAGS(6);
}

SECTIONS
{
    . = 0;
    __image_base = .;
    . = SIZEOF_HEADERS;

    .text : { *(.text .text.*) } :text
    .rodata : { *(.rodata .rodata.*) } :text
    .rela.dyn : {
        __rela_start = .;
        *(.rela.dyn .rela.*)
        __rela_end = .;
    } :text
    .dynsym : { *(.dynsym) } :text
    .dynstr : { *(.dynstr) } :text
    .hash : { *(.hash) } :text
    .gnu.hash : { *(.gnu.hash) } :text

    . = ALIGN(4096);
    .data.rel.ro : { *(.data.rel.ro .data.rel.ro.*) } :data
    .dynamic : { *(.dynamic) } :data
    .got : { *(.got .got.plt) } :data
    .data : { *(.data .data.*) } :data
    .bss : { *(.bss .bss.* COMMON) } :data

    /DISCARD/ : { *(.note.*) *(.comment) *(.eh_frame*) *(.interp) }
}
