# Network OS x86_64 prototype

This is a separate, experimental bare-metal kernel prototype. It boots in
QEMU without replacing or modifying the host operating system. The existing
Python network/research application remains unchanged and does not run inside
this kernel.

## What the first milestone does

- Builds a BIOS boot image for `x86_64-unknown-none`.
- Starts it in QEMU with a serial console and an emulated Intel E1000 PCI
  network adapter.
- Initializes COM1 serial output, scans PCI configuration space, and reports
  network-class devices and their vendor/device IDs.
- Exits QEMU after reporting the result.

This is device discovery only—not a NIC driver or a TCP/IP implementation.
The QEMU user-mode network backend is configured, but the kernel has no
driver and sends no network traffic. No host network ports are opened by this
prototype.

## Requirements

- Rust nightly via rustup, with `llvm-tools-preview` and the
  `x86_64-unknown-none` target. The checked-in `rust-toolchain.toml` selects
  these for this subproject only.
- QEMU x86_64 (`qemu-system-x86_64`) on `PATH`.
- On Windows, the pinned GNU-host Rust toolchain needs a MinGW-w64 linker.
- Network access to download the pinned Rust crates on the first build.

## Build and boot

From the repository root:

```powershell
$env:PATH = "$env:USERPROFILE\.cargo\bin;C:\Program Files\qemu;$env:PATH"
Set-Location os
cargo run
```

If QEMU is installed elsewhere, replace `C:\Program Files\qemu` with its
installation directory. To run a non-interactive integration check that
asserts the kernel boot and emulated E1000 discovery:

```powershell
cargo run -- check
```

Expected serial output includes a `network controller: 8086:100e` line from
QEMU's emulated E1000, followed by a clear note that no network driver or
IP stack is present. Build artifacts and generated disk images stay under
`os/target/` and are ignored by Git.

This kernel has direct hardware I/O instructions and must only be run in the
configured emulator for this prototype. Do not write its disk image to a
physical drive.
