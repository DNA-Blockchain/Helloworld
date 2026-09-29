// MicroPython configuration for the Network OS ring-3 task runtime.
// Built freestanding: no host libc; files are reached only through the
// kernel's task syscalls, and output goes to its stdout syscall.

#include <stdint.h>

// Core features give the language surface remission_core.py relies on
// (str % formatting, enumerate, str.encode, unicode strings, io).
#define MICROPY_CONFIG_ROM_LEVEL          (MICROPY_CONFIG_ROM_LEVEL_CORE_FEATURES)

#define MICROPY_ENABLE_COMPILER           (1)
#define MICROPY_ENABLE_GC                 (1)
#define MICROPY_HELPER_REPL               (0)
#define MICROPY_ENABLE_EXTERNAL_IMPORT    (0)
#define MICROPY_ENABLE_SOURCE_LINE        (1)
#define MICROPY_ERROR_REPORTING           (MICROPY_ERROR_REPORTING_NORMAL)
#define MICROPY_STACK_CHECK               (1)
#define MICROPY_ALLOC_PATH_MAX            (64)
#define MICROPY_ALLOC_PARSE_CHUNK_INIT    (16)
#define MICROPY_FLOAT_IMPL                (MICROPY_FLOAT_IMPL_NONE)

// Modules the remission workflow imports.
#define MICROPY_PY_JSON                   (1)
#define MICROPY_PY_HASHLIB                (1)
#define MICROPY_PY_HASHLIB_SHA256         (1)
#define MICROPY_PY_BINASCII               (1)
#define MICROPY_PY_BUILTINS_BYTES_HEX     (1) // binascii.hexlify

#define MICROPY_PY_SYS                    (1)
#define MICROPY_PY_SYS_ARGV               (1)
#define MICROPY_PY_SYS_EXIT               (1)
#define MICROPY_PY_SYS_PLATFORM           "network-os"
#define MICROPY_PY_SYS_MODULES            (0)
#define MICROPY_PY_SYS_PATH               (0)

// Heap for Python objects, in the task's .bss (the kernel zero-fills it).
#define MICROPY_HEAP_SIZE                 (512 * 1024)

#define MICROPY_HW_BOARD_NAME             "network-os"
#define MICROPY_HW_MCU_NAME               "x86_64-ring3"

typedef long mp_off_t;

// alloca() is a compiler builtin; the header only maps the name.
#include <alloca.h>

#define MP_STATE_PORT MP_STATE_VM
