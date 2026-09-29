# Ring-3 MicroPython runtime

`MPY.ELF` is a freestanding build of MicroPython (pinned revision
`09f5bb447504a058376c62fe991b3613531837e6`) that the kernel embeds and runs
for workflow tasks whose manifest says `"runtime": "micropython"`.

## How it runs

1. The kernel validates the task manifest and every file digest, then loads
   `MPY.ELF` (from the kernel image, not the disk) into a fresh ring-3
   address space.
2. `_start` applies the image's own `R_X86_64_RELATIVE` relocations (the
   kernel loader has no dynamic linker) and switches to a 64-KiB stack in
   `.bss`.
3. Syscall 14 returns the manifest's entrypoint name, syscall 2 reads that
   script, and MicroPython compiles and runs it with a 512-KiB heap.
4. `print` goes to syscall 3 (the serial console). The task exits 0 on
   success or 1 on an uncaught exception; the kernel's task policy still
   limits file reads to the entrypoint and declared inputs, blocks network
   syscalls, and stops the task at `runtimeSeconds`.

Exit codes 2-4 mean a startup failure: an unsupported relocation, no
entrypoint name, or an unreadable script.

## Rebuilding

In Ubuntu/WSL with `gcc`, `make`, `python3` and `git`:

```sh
sh os/micropython/build.sh
```

It clones the pinned MicroPython revision into `~/.cache` (or uses
`MICROPY_TOP`), builds in a Linux-local directory, strips the result, marks
it `ET_DYN`, refuses any relocation other than `R_X86_64_RELATIVE`, and
writes `os/micropython/MPY.ELF`. Rebuild the kernel afterwards; it embeds the
file with `include_bytes!`.

## Limits

The configuration is MicroPython's `CORE_FEATURES` level plus Unicode `str`,
`json`, `hashlib.sha256`, `binascii` (`hexlify`) and `sys` (`argv`, `exit`,
`platform == "network-os"`), with a 512-KiB heap. That is enough for
`remission_core.py` and `research_analysis.py`, which the kernel's boot check
runs and compares with CPython's output byte for byte.

Two settings matter for matching CPython. Unicode `str` is on: without it
`str` is a byte string and `json.loads` keeps only the low byte of a `\u`
escape. And the port builds with `-funsigned-char`: MicroPython's freestanding
`memcmp` compares plain `char`, which is signed on x86-64 and would sort bytes
above 0x7F before ASCII. MicroPython's `str.strip`, `split`, `lower`,
`isalpha` and `isdigit` still only know ASCII, so the task modules define
their own text rules. `open()` supports
whole-file reads (`"r"`/`"rb"`, at most 64 KiB, through syscall 2) and
buffered writes that are stored on `close()` (`"w"`/`"wb"`, at most 16 KiB,
through syscall 13), so the kernel's input and `.OUT` output policy applies.
There are no floats, no `import` of other files, no seeking and no network
access. `sys.exit(n)` exits with `n`. ROM text compression is disabled
because it inflates x86-64 code about tenfold.
