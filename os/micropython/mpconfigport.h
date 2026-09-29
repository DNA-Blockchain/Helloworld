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
