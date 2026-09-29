/*
 * ============================================================================
 *  SPDX-License-Identifier: UPL-1.0
 *
 *  Copyright (c) 2026 Chase Allen Ringquist
 *
 *  This file is part of an operating system, software, and network Work
 *  conceived and authored by Chase Allen Ringquist. The Author retains
 *  copyright and authorship. Use of this file is licensed as follows.
 *
 *  ----------------------------------------------------------------------------
 *  The Universal Permissive License (UPL), Version 1.0
 *
 *  Subject to the condition set forth below, permission is hereby granted to
 *  any person obtaining a copy of this software, associated documentation
 *  and/or data (collectively the "Software"), free of charge and under any
 *  and all copyright rights in the Software, and any and all patent rights
 *  owned or freely licensable by each licensor hereunder covering either
 *  (i) the unmodified Software as contributed to or provided by such
 *  licensor, or (ii) the Larger Works (as defined below), to deal in both
 *
 *  (a) the Software, and
 *
 *  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
 *  if one is included with the Software (each a "Larger Work" to which the
 *  Software is contributed by such licensors),
 *
 *  without restriction, including without limitation the rights to copy,
 *  create derivative works of, display, perform, and distribute the Software
 *  and make, use, sell, offer for sale, import, export, have made, and have
 *  sold the Software and the Larger Work(s), and to sublicense the foregoing
 *  rights on either these or other terms.
 *
 *  This license is subject to the following condition:
 *
 *  The above copyright notice and either this complete permission notice or
 *  at a minimum a reference to the UPL must be included in all copies or
 *  substantial portions of the Software.
 *
 *  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 *  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 *  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 *  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 *  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 *  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 *  DEALINGS IN THE SOFTWARE.
 *  ----------------------------------------------------------------------------
 *
 *  Do not remove or alter this notice or any record of origin.
 *  See NOTICE.md in the project root for authorship and ownership terms.
 *
 *  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
 *            Bixby, OK, United States
 * ============================================================================
 */

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
#define SYS_WRITE_FILE       (13)
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
    mp_obj_t exception = MP_OBJ_FROM_PTR(nlr.ret_val);
    if (mp_obj_is_subclass_fast(MP_OBJ_FROM_PTR(mp_obj_get_type(exception)),
        MP_OBJ_FROM_PTR(&mp_type_SystemExit))) {
        // sys.exit(n) exits with n; sys.exit() exits 0; sys.exit("why")
        // prints the message and exits 1, as CPython does.
        mp_obj_t code = mp_obj_exception_get_value(exception);
        mp_int_t status;
        if (code == mp_const_none) {
            return 0;
        }
        if (mp_obj_get_int_maybe(code, &status)) {
            return (int)status;
        }
        mp_obj_print_helper(&mp_plat_print, code, PRINT_STR);
        mp_print_str(&mp_plat_print, "\n");
        return EXIT_UNCAUGHT_EXCEPTION;
    }
    mp_obj_print_exception(&mp_plat_print, exception);
    return EXIT_UNCAUGHT_EXCEPTION;
}

// open() for task scripts. Read modes load the whole file through syscall 2
// (so the kernel's input-file policy applies); write modes buffer in memory
// and store the file through syscall 13 on close (so only declared .OUT
// outputs can be written).
typedef struct {
    mp_obj_base_t base;
    vstr_t data;
    size_t position;
    bool binary;
    bool writing;
    bool closed;
    char name[NAME_CAPACITY];
} task_file_obj_t;

static task_file_obj_t *task_file_open(mp_obj_t self_in) {
    task_file_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->closed) {
        mp_raise_ValueError(MP_ERROR_TEXT("I/O operation on closed file"));
    }
    return self;
}

static mp_obj_t task_file_read(size_t n_args, const mp_obj_t *args) {
    task_file_obj_t *self = task_file_open(args[0]);
    if (self->writing) {
        mp_raise_OSError(MP_EBADF);
    }
    size_t count = self->data.len - self->position;
    if (n_args > 1 && args[1] != mp_const_none) {
        mp_int_t requested = mp_obj_get_int(args[1]);
        if (requested >= 0 && (size_t)requested < count) {
            count = (size_t)requested;
        }
    }
    const char *start = self->data.buf + self->position;
    self->position += count;
    if (self->binary) {
        return mp_obj_new_bytes((const byte *)start, count);
    }
    return mp_obj_new_str(start, count);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(task_file_read_obj, 1, 2, task_file_read);

static mp_obj_t task_file_write(mp_obj_t self_in, mp_obj_t data) {
    task_file_obj_t *self = task_file_open(self_in);
    if (!self->writing) {
        mp_raise_OSError(MP_EBADF);
    }
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(data, &buffer, MP_BUFFER_READ);
    vstr_add_strn(&self->data, buffer.buf, buffer.len);
    return MP_OBJ_NEW_SMALL_INT(buffer.len);
}
static MP_DEFINE_CONST_FUN_OBJ_2(task_file_write_obj, task_file_write);

static mp_obj_t task_file_close(mp_obj_t self_in) {
    task_file_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->closed) {
        return mp_const_none;
    }
    self->closed = true;
    if (self->writing
        && syscall3(SYS_WRITE_FILE, (long)self->name, (long)self->data.buf, (long)self->data.len) < 0) {
        mp_raise_OSError(MP_EIO);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(task_file_close_obj, task_file_close);

static mp_obj_t task_file_enter(mp_obj_t self_in) {
    return self_in;
}
static MP_DEFINE_CONST_FUN_OBJ_1(task_file_enter_obj, task_file_enter);

static mp_obj_t task_file_exit(size_t n_args, const mp_obj_t *args) {
    (void)n_args;
    return task_file_close(args[0]);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(task_file_exit_obj, 4, 4, task_file_exit);

static const mp_rom_map_elem_t task_file_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_read), MP_ROM_PTR(&task_file_read_obj) },
    { MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&task_file_write_obj) },
    { MP_ROM_QSTR(MP_QSTR_close), MP_ROM_PTR(&task_file_close_obj) },
    { MP_ROM_QSTR(MP_QSTR___enter__), MP_ROM_PTR(&task_file_enter_obj) },
    { MP_ROM_QSTR(MP_QSTR___exit__), MP_ROM_PTR(&task_file_exit_obj) },
};
static MP_DEFINE_CONST_DICT(task_file_locals, task_file_locals_table);

static MP_DEFINE_CONST_OBJ_TYPE(
    task_file_type,
    MP_QSTR_TaskFile,
    MP_TYPE_FLAG_NONE,
    locals_dict, &task_file_locals
    );

mp_obj_t mp_builtin_open(size_t n_args, const mp_obj_t *args, mp_map_t *kwargs) {
    (void)kwargs;
    const char *name = mp_obj_str_get_str(args[0]);
    const char *mode = n_args > 1 ? mp_obj_str_get_str(args[1]) : "r";
    size_t name_length = strlen(name);
    if (name_length == 0 || name_length >= NAME_CAPACITY) {
        mp_raise_OSError(MP_ENOENT);
    }
    task_file_obj_t *self = mp_obj_malloc(task_file_obj_t, &task_file_type);
    memcpy(self->name, name, name_length + 1);
    self->position = 0;
    self->closed = false;
    self->binary = strchr(mode, 'b') != NULL;
    self->writing = strchr(mode, 'w') != NULL;
    if (self->writing) {
        vstr_init(&self->data, 256);
        return MP_OBJ_FROM_PTR(self);
    }
    vstr_init(&self->data, SCRIPT_CAPACITY);
    long length = syscall3(SYS_READ_FILE, (long)self->name, (long)self->data.buf, SCRIPT_CAPACITY);
    if (length < 0) {
        mp_raise_OSError(MP_ENOENT);
    }
    self->data.len = (size_t)length;
    return MP_OBJ_FROM_PTR(self);
}
MP_DEFINE_CONST_FUN_OBJ_KW(mp_builtin_open_obj, 1, mp_builtin_open);

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
    mp_obj_list_append(mp_sys_argv, mp_obj_new_str(name, (size_t)name_length));
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
