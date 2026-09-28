# Network OS x86_64 prototype

This is a separate, experimental bare-metal kernel prototype. It boots in
QEMU without replacing or modifying the host operating system. The existing
Python network/research application remains unchanged and does not run inside
this kernel.

## What the network milestone does

- Builds a BIOS boot image for `x86_64-unknown-none`.
- Starts it in QEMU with a serial console and an emulated Intel E1000 PCI
  network adapter.
- Initializes the QEMU Intel 82540EM (`8086:100e`) E1000 using DMA
  descriptor rings and memory-mapped registers.
- Installs a 100 Hz PIT interrupt handler, remaps and masks the legacy PIC,
  provides a monotonic millisecond clock, and uses `hlt` while waiting.
- Initializes a fixed-metadata physical frame allocator for usable memory
  below 4 GiB; the boot check allocates, maps, writes, releases, and reuses a
  page.
- Adds a kernel-only virtual-page arena in an unused PML4 slot. The boot check
  maps a zeroed 4-KiB frame, verifies read/write access, unmaps it, checks the
  page-table entry was cleared, rejects a repeated free, and reuses the
  virtual slot. Empty page-table levels are reclaimed.
- Creates two independent page-table roots with shared supervisor-only
  kernel-half mappings and private user-marked pages at the same virtual
  address. The QEMU check switches CR3 and verifies each space retains its
  own data, then releases its page tables and frames. This exercises page-table
  separation.
- Enters ring 3 for a tiny machine-code test program, services its DPL-3
  `int 0x80` exit syscall on a TSS-provided ring-0 stack, and verifies the
  program returns exit code 42. This is a single test syscall, not a general
  syscall ABI or a complete process loader; protection-fault recovery is not
  implemented.
- Provides a kernel heap backed by mapped pages and a first-fit free-list
  allocator. It starts at 64 KiB and can grow by contiguous pages to at most
  512 KiB. The boot check exercises heap growth and Rust `Vec` and `Box`
  allocation and release. The heap is not available to user-mode programs.
- Runs a one-shot kernel task on a separate 16-KiB stack and verifies that it
  can allocate from the kernel heap. This is a stack-switching test, not a
  process or preemptive scheduler.
- Includes a bounded cooperative round-robin scheduler check: two kernel
  tasks take five timer-paced steps in the expected A/B/A/B/A order, each on
  its own 16-KiB stack. It is not preemptive and does not schedule ring-3
  processes.
- Uses `smoltcp` as a no-heap dual-stack network layer with Ethernet, ARP,
  IPv4, IPv6, DHCPv4, ICMP/ICMPv6, UDP, TCP, and IPv6 SLAAC support enabled.
- Requests an IPv4 lease from QEMU's user-mode DHCP service, then sends an
  ICMP echo request to the IPv4 gateway.
- Enables IPv6 SLAAC and waits for an address and default route from a router
  advertisement. QEMU's built-in user network sends no router
  advertisements, so the standard network check reports SLAAC as unavailable
  and uses an explicitly labelled static test address and route. A separate
  `check-slaac` run uses a loopback-only QEMU socket network and a small local
  test router that sends a real RA; it verifies the SLAAC address, RA default
  route, and ICMPv6 echo response in the guest.
- Verifies an ICMPv6 echo reply from the QEMU IPv6 gateway.
- Runs a small in-kernel HTTP health service on guest TCP port 8080. `GET
  /health` returns `200 OK` with `ok`; other paths return `404`.
- Uses a QEMU-only secondary IDE disk image at
  `os/target/network-os-persistent.img`. The kernel reads and updates one
  reserved sector with a generation counter and checksum, flushes the write,
  and verifies it by reading the sector back. Repeated boots increment the
  counter, demonstrating persistence across emulator restarts. This is a
  block-I/O test, not a filesystem; the image is generated under ignored
  build output and is never a host physical disk.

The driver is specifically for the emulated 82540EM used by this QEMU runner;
it is not a general PCI NIC driver. The runner uses QEMU user-mode networking
and forwards host `127.0.0.1:18080` to guest port 8080; it does not bind the
service to a public host interface. `cargo run` keeps the kernel service
running until QEMU is stopped. `cargo run -- check` starts QEMU, checks DHCP
and both gateway echoes, makes repeated real HTTP requests through the
loopback-only forward, and stops QEMU. `cargo run -- check-slaac` runs the
controlled RA test described above. This validates the stack and driver only
in QEMU, not on physical hardware or a production network.

## Requirements

- Rust nightly via rustup, with `llvm-tools-preview` and the
  `x86_64-unknown-none` target. The checked-in `rust-toolchain.toml` selects
  these for this subproject only.
- QEMU x86_64 (`qemu-system-x86_64`) on `PATH`.
- On Windows, the pinned GNU-host Rust toolchain needs a MinGW-w64 linker.
- Python 3 is needed for the optional controlled SLAAC router test.
- Network access to download the pinned Rust crates on the first build.

## Build and boot

From the repository root:

```powershell
$env:PATH = "$env:USERPROFILE\.cargo\bin;C:\Program Files\qemu;$env:PATH"
Set-Location os
cargo run
```

If QEMU is installed elsewhere, replace `C:\Program Files\qemu` with its
installation directory. The health endpoint is available at
`http://127.0.0.1:18080/health` while the OS is running. To run a
non-interactive integration check that asserts NIC initialization, IPv4 DHCP,
IPv4/IPv6 gateway echo replies, and an actual HTTP response:

```powershell
cargo run -- check
```

To verify SLAAC using a controlled local router instead of QEMU's user-mode
network:

```powershell
cargo run -- check-slaac
```

Build artifacts and generated disk images stay under `os/target/` and are
ignored by Git.

This kernel uses direct hardware I/O and DMA and must only be run in the
configured QEMU emulator for this prototype. Do not write its disk image to a
physical drive or use the driver on a physical machine.
