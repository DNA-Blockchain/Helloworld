// Network OS ring-3 MicroPython runtime.
//
// The kernel loads this static ET_DYN image at an arbitrary base with no
// dynamic linker, so _start first applies its own R_X86_64_RELATIVE
// relocations, switches to a 64-KiB stack in .bss, then asks the kernel
// which script the task manifest names (syscall 14), reads it (syscall 2),
// and runs it. Output goes to the kernel's stdout syscall. The task exits
// with status 0 on success and 1 on an uncaught Python exception.

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "py/builtin.h"
#include "py/compile.h"
#include "py/gc.h"
#include "py/mphal.h"
#include "py/mperrno.h"
#include "py/runtime.h"
#include "py/stackctrl.h"
#include "shared/runtime/gchelper.h"

#define SYS_EXIT             (1)
#define SYS_READ_FILE        (2)
#define SYS_WRITE            (3)
#define SYS_TASK_ENTRYPOINT  (14)
#define SYS_WRITE_MAX        (4096)
#define R_X86_64_RELATIVE    (8)

#define STACK_BYTES          (64 * 1024)
#define SCRIPT_CAPACITY      (64 * 1024)
#define NAME_CAPACITY        (16)

#define EXIT_UNCAUGHT_EXCEPTION     (1)
#define EXIT_BAD_RELOCATION         (2)
#define EXIT_NO_ENTRYPOINT          (3)
#define EXIT_SCRIPT_UNREADABLE      (4)

#define HIDDEN __attribute__((visibility("hidden")))

typedef struct {
    uint64_t offset;
    uint64_t info;
    int64_t addend;
} rela_t;

extern const rela_t __rela_start[] HIDDEN;
extern const rela_t __rela_end[] HIDDEN;
extern char __image_base[] HIDDEN;

HIDDEN uint8_t task_stack[STACK_BYTES] __attribute__((aligned(16)));
static char heap[MICROPY_HEAP_SIZE];
static char script[SCRIPT_CAPACITY];

__asm__(
    ".text\n"
    ".globl _start\n"
    "_start:\n"
    "    leaq task_stack+65536(%rip), %rsp\n"
    "    andq $-16, %rsp\n"
    "    call network_os_start\n"
    "    ud2\n"
    );

// The kernel's int 0x80 stub clobbers every caller-saved register.
static long syscall3(long number, long a, long b, long c) {
    __asm__ volatile (
        "int $0x80"
        : "+a" (number), "+D" (a), "+S" (b), "+d" (c)
        :
        : "rcx", "r8", "r9", "r10", "r11", "memory", "cc");
    return number;
}

static MP_NORETURN void task_exit(long status) {
    syscall3(SYS_EXIT, status, 0, 0);
    for (;;) {
    }
}

mp_uint_t mp_hal_stdout_tx_strn(const char *str, size_t len) {
    size_t written = 0;
    while (written < len) {
        size_t chunk = len - written;
        if (chunk > SYS_WRITE_MAX) {
            chunk = SYS_WRITE_MAX;
        }
        if (syscall3(SYS_WRITE, (long)(str + written), (long)chunk, 0) < 0) {
            break;
        }
        written += chunk;
    }
    return written;
}

static int run_script(const char *name, size_t length) {
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_lexer_t *lex = mp_lexer_new_from_str_len(qstr_from_str(name), script, length, 0);
        qstr source_name = lex->source_name;
        mp_parse_tree_t tree = mp_parse(lex, MP_PARSE_FILE_INPUT);
        mp_obj_t module = mp_compile(&tree, source_name, false);
        mp_call_function_0(module);
        nlr_pop();
        return 0;
    }
    mp_obj_print_exception(&mp_plat_print, MP_OBJ_FROM_PTR(nlr.ret_val));
    return EXIT_UNCAUGHT_EXCEPTION;
}

static MP_NORETURN void network_os_main(void) {
    char name[NAME_CAPACITY];
    long name_length = syscall3(SYS_TASK_ENTRYPOINT, (long)name, NAME_CAPACITY - 1, 0);
    if (name_length <= 0 || name_length >= NAME_CAPACITY) {
        task_exit(EXIT_NO_ENTRYPOINT);
    }
    name[name_length] = '\0';
    long length = syscall3(SYS_READ_FILE, (long)name, (long)script, SCRIPT_CAPACITY);
    if (length < 0) {
        task_exit(EXIT_SCRIPT_UNREADABLE);
    }

    mp_stack_ctrl_init();
    mp_stack_set_limit(STACK_BYTES - 8 * 1024);
    gc_init(heap, heap + sizeof(heap));
    mp_init();
    int status = run_script(name, (size_t)length);
    mp_deinit();
    task_exit(status);
}

// Runs before any relocated pointer is used; references only hidden
// symbols, which -fPIE addresses RIP-relative without the GOT.
__attribute__((used)) HIDDEN MP_NORETURN void network_os_start(void) {
    uintptr_t base = (uintptr_t)__image_base;
    for (const rela_t *rela = __rela_start; rela < __rela_end; rela++) {
        if ((rela->info & 0xffffffff) != R_X86_64_RELATIVE) {
            task_exit(EXIT_BAD_RELOCATION);
        }
        *(uint64_t *)(base + rela->offset) = base + (uint64_t)rela->addend;
    }
    network_os_main();
}

void gc_collect(void) {
    gc_collect_start();
    gc_helper_collect_regs_and_stack();
    gc_collect_end();
}

mp_lexer_t *mp_lexer_new_from_file(qstr filename) {
    (void)filename;
    mp_raise_OSError(MP_ENOENT);
}

mp_import_stat_t mp_import_stat(const char *path) {
    (void)path;
    return MP_IMPORT_STAT_NO_EXIST;
}

void nlr_jump_fail(void *val) {
    (void)val;
    task_exit(EXIT_UNCAUGHT_EXCEPTION);
}

void MP_NORETURN __fatal_error(const char *msg) {
    mp_hal_stdout_tx_strn(msg, strlen(msg));
    task_exit(EXIT_UNCAUGHT_EXCEPTION);
}

#ifndef NDEBUG
void MP_WEAK __assert_func(const char *file, int line, const char *func, const char *expr) {
    (void)file;
    (void)line;
    (void)func;
    __fatal_error(expr);
}
#endif
