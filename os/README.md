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
- Loads a small static x86_64 ELF64 `ET_DYN` executable from `TEST.ELF` on
  `NOSFS v2`. The bounded loader validates the ELF header and program-header
  ranges, accepts only static `PT_LOAD` segments, applies a page-aligned load
  bias, rejects writable-executable segments, caps the ELF image at 256 KiB
  and the process at 512 user pages, maps private user pages, zeroes BSS, and
  applies read/write/NX page
  permissions. The test maps the executable and stack into a dedicated CR3
  address space, rejects a malformed ELF, verifies that execution from the NX
  stack and a write to read-only executable text both fault and return to the
  harness, and verifies that an unhandled user page fault terminates the test
  process. An invalid-opcode exception in ring 3 also returns to the harness,
  which then reclaims the process address space. The ring-3 program calls
  `int 0x80` to exit with status 42.
  This is a bounded lifecycle smoke test, not a general process manager: there
  is no dynamic linker, relocations, arguments/environment, complete syscall
  ABI, or recovery from user exceptions other than invalid-opcode and page
  faults.
- Also exercises a separate ring-3 machine-code test program that reads a
  NUL-terminated filename through the read-only user-copy path, requests that
  file from `NOSFS v2`, and receives it into a fully validated writable user
  buffer. The syscall bounds the filename to 15 bytes and the output length to
  the filesystem's 256-KiB file limit. It then echoes the file through the
  bounded stdout syscall. QEMU checks the emitted `BOOT.JSON` bytes and rejects
  supervisor pointers for file reads and stdout writes. The `int 0x80` ABI uses
  syscall 1 for exit (`RDI` = status), syscall 2 for read-file (`RDI` =
  filename pointer, `RSI` = output pointer, `RDX` = output capacity), and
  syscall 3 for stdout (`RDI` = readable buffer, `RSI` = byte count, capped at
  4 KiB per call). Successful reads/writes return a byte count; failures return
  `u64::MAX - 1`. Stdout is the serial console, not a terminal or network
  stream. User-mode file creation/writes, directories, filesystem permissions,
  and concurrent filesystem access are not exposed.
- Provides a kernel heap backed by mapped pages and a first-fit free-list
  allocator. It starts at 64 KiB and can grow by contiguous pages to at most
  512 KiB. The boot check exercises heap growth and Rust `Vec` and `Box`
  allocation and release. The heap is not available to user-mode programs.
- Runs a one-shot kernel task on a separate 16-KiB stack and verifies that it
  can allocate from the kernel heap. This is a stack-switching test, not a
  process or preemptive scheduler.
- Includes a bounded cooperative scheduler check: two kernel tasks switch
  across five timer-paced A/B/A/B/A steps on separate 16-KiB stacks. The check
  exercises ready, running, blocked, and exited states, including waking a
  blocked task. It is not preemptive, does not block ring-3 processes, and does
  not yet schedule the network service.
- Uses `smoltcp` as a no-heap dual-stack network layer with Ethernet, ARP,
  IPv4, IPv6, DHCPv4, ICMP/ICMPv6, UDP, TCP, and IPv6 SLAAC support enabled.
- Requests an IPv4 lease from QEMU's user-mode DHCP service, then sends an
  ICMP echo request to the IPv4 gateway.
- Uses a bounded UDP DNS client to query QEMU's resolver at `10.0.2.3` for
  `example.com`. The boot check validates the transaction ID, response flags,
  question, answer bounds, and IPv4 record before reporting the result. This
  exercises kernel networking only; user processes do not yet have DNS or
  socket syscalls. Networks without QEMU's resolver report DNS as unavailable;
  the standard `check` mode requires resolution, while the loopback-only
  `check-slaac` mode does not provide an upstream resolver.
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
  `os/target/network-os-persistent.img`. ATA PIO access is routed through a
  bounded 512-byte `BlockDevice` sector interface with capacity checks and
  explicit flush. A small `NOSFS v2` filesystem on that image provides a
  checksummed allocation bitmap, fixed root directory with 16 entries,
  contiguous extents up to 256 KiB per file, and read/write support. The boot
  check reads back `BOOT.JSON` and a 24-KiB `RUNTIME.TEST` file across boots.
  This experimental filesystem has no journaling, directories, permissions, or
  general crash recovery; malformed or unknown metadata is rejected rather
  than reformatted. The image is generated under ignored build output and is
  never a host physical disk.
- Defines initial JSON Schema contracts for MicroPython task bundles and
  workflows in `os/schemas/`. A task bundle references bounded, checksummed
  files stored as ordinary NOSFS files; workflow blocks reference task
  manifests and name their input/output files and dependencies. A block is
  not an independently executable disk sector. The boot test persists and
  reads back a sample bundle, validates its task and workflow manifests in the
  guest, verifies each declared file's SHA-256 and size, and rejects malformed
  JSON, a bad digest, and a cyclic workflow. The bounded validator checks
  required/allowed fields and cross-references. A non-executing dispatcher
  builds a topological plan, tracks `Ready`, `Waiting`, `Succeeded`, `Failed`,
  and `Skipped` states, and records transitions in a fixed-size in-memory
  event log. Boot tests simulate runtime outcomes to check dependency wake-up
  and both failure policies; no MicroPython task is launched. This is not a
  persistent run history or task-level filesystem/network capability
  enforcement.
  The names reflect current NOSFS constraints (15-byte flat filenames and
  256-KiB maximum file size); the 16-entry root directory is too small for a
  useful multi-task workflow alongside the current boot/test files. SHA-256
  fields verify content integrity, not publisher identity. Execution will
  require an approval/authenticity mechanism and enforcement of the declared
  resource and network capabilities.

The driver is specifically for the emulated 82540EM used by this QEMU runner;
it is not a general PCI NIC driver. The runner uses QEMU user-mode networking
and forwards host `127.0.0.1:18080` to guest port 8080; it does not bind the
service to a public host interface. `cargo run` keeps the kernel service
running until QEMU is stopped. `cargo run -- check` starts QEMU, checks DHCP
and both gateway echoes, makes repeated real HTTP requests through the
loopback-only forward, and stops QEMU. `cargo run -- check-slaac` runs the
controlled RA test described above. This validates the stack and driver only
in QEMU, not on physical hardware or a production network.

The Python research agent is still not executable in this kernel. The intended
direction is a workflow dispatcher that loads approved task manifests and
launches MicroPython in a separate ring-3 ELF process, never inside the kernel.
The guest can validate and plan the initial task-bundle and workflow formats,
but this does not execute them or persist run status. The current loader,
process lifecycle, 256-KiB per-file limit, and minimal read-only file syscall
are not sufficient to load MicroPython or dispatch these workflows. Before
execution, the OS needs a stable process ABI, a user-space runtime, bounded
data handoff, and enforced per-task capabilities. Only approved code may be
executable; downloaded research records remain data, not code.

The host research application has an optional local Ollama integration for
citation-grounded answers (`local_ai_retrieval.py`), but the bare-metal guest
does not currently connect to Ollama, cloud LLM APIs, MCP servers, or other
agents. The new ring-3 stdout call is only a local console interface; it does
not provide guest networking, TLS, credentials, or model access. A future AI
connection should be an explicitly configured user-space client behind the
network and TLS services, with per-task destination/data permissions. No
provider or remote AI endpoint is contacted by the QEMU checks.

### MicroPython host soft launch

`examples/micropython/soft_launch.py` is a harmless host-side smoke task. It
round-trips a small JSON object and checks its fields using MicroPython. It was
run with the official MicroPython Unix port in an isolated Ubuntu 24.04 WSL
distribution, built from upstream revision
`09f5bb447504a058376c62fe991b3613531837e6`. `mpy-cross` also compiled the
sample to `.mpy` bytecode, and the same host runtime loaded that module
successfully. The standard Unix port was used because the minimal variant
omits the JSON module.

The WSL build is a development tool, not part of the kernel or guest image.
To reproduce it in Ubuntu/WSL, install `build-essential`, `git`, `python3`,
`pkg-config`, and `libffi-dev`, then run:

```sh
git clone https://github.com/micropython/micropython.git
cd micropython
git checkout 09f5bb447504a058376c62fe991b3613531837e6
make -C mpy-cross -j2
make -C ports/unix submodules
make -C ports/unix VARIANT=standard -j2
ports/unix/build-standard/micropython /mnt/c/Users/odaat/network-os-project/os/examples/micropython/soft_launch.py
mpy-cross/build/mpy-cross -o /tmp/soft_launch.mpy /mnt/c/Users/odaat/network-os-project/os/examples/micropython/soft_launch.py
MICROPYPATH=/tmp ports/unix/build-standard/micropython -m soft_launch
```

### Host research-to-MicroPython pilot

`examples/micropython/research_result_summary.py` accepts one saved JSON
response from `blockchain_dna_tool.py` and emits a bounded summary of topic,
source statuses, record counts, and new-ID count. It treats records and IDs as
data, does not infer scientific results, and marks chain writes disabled. The
paired `research_result_fixture.json` contains synthetic IDs only; it permits
offline validation without contacting research APIs. To run the fixture using
the WSL standard MicroPython binary built above:

```powershell
wsl.exe -d Ubuntu-24.04 -- /root/micropython-soft-launch/source/ports/unix/build-standard/micropython /mnt/c/Users/odaat/network-os-project/os/examples/micropython/research_result_summary.py /mnt/c/Users/odaat/network-os-project/os/examples/micropython/research_result_fixture.json
```

For a future real-data trial, first make an explicitly approved research query
with `blockchain_dna_tool.py`, save its JSON response, review that response,
and pass only the reviewed response file to the same MicroPython task. Do not
pipe raw external web content into execution, and do not write research data to
a blockchain. This host-side orchestration is not a security sandbox and does
not integrate the runtime into the guest OS.

This validates task syntax and MicroPython behavior on the host only; WSL
MicroPython has the host user's permissions and is not a security sandbox. Run
only reviewed, approved scripts, never untrusted research records or downloaded
code. The built host executable is about 875 KB and is a dynamically linked
Linux PIE; it is not a guest executable. The current guest loader accepts at
most 256-KiB static ELF images, rejects dynamic linking, and has only a small
process/syscall surface. Porting MicroPython into ring 3 still requires a
dedicated bare-metal port, an appropriate memory plan, and console/file APIs.

Blockchain is not required to run the research agent. The recommended data
path is authorized, encrypted off-chain storage with provenance and access
controls. If a later, separately reviewed integration uses a chain, prefer a
permissioned network and write only a minimal, non-identifying integrity digest
and provenance reference. Never write patient records, genomic sequences, API
credentials, or identifying metadata to an immutable chain; hashes and metadata
can still reveal sensitive information and require a privacy review.

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
