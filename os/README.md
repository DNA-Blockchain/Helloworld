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
- Adds an initial ring-3 DNS lookup syscall (syscall 4: `RDI` = user hostname
  pointer, `RSI` = byte length (1-253 ASCII bytes), `RDX` = writable 4-byte
  IPv4 result). The kernel validates and copies the hostname, resolves through
  its existing UDP service with a bounded timeout, and returns 4 on success or
  `u64::MAX - 1` on error. QEMU runs this syscall from ring 3; the controlled
  SLAAC test verifies that unavailable upstream DNS is reported without
  preventing the HTTP service from starting. It is exercised only while the
  boot test temporarily lends the network owner to a synchronous ring-3 smoke
  program. DNS remains a test-context service, not a general process resolver.
- Adds bounded TCP/UDP socket syscalls 5-12 for the same synchronous ring-3
  smoke context. TCP connect takes an IPv4 address in `RDI` (a big-endian
  32-bit address value) and port in `RSI`, and blocks for at most five seconds.
  TCP send/receive use `RDI` = user buffer and `RSI` = length/capacity, capped
  at 1024 bytes; send may be partial, receive is a single poll and returns zero
  when no data is available. TCP close aborts the connection. UDP bind takes
  a nonzero local port in `RDI`; sendto uses `RDI` = readable buffer, `RSI` =
  length, and `RDX` = packed IPv4/port (IPv4 in low 32 bits, port in bits
  32-47). Recvfrom uses `RDI` = writable packet buffer, `RSI` = capacity, and
  `RDX` = writable 6-byte source endpoint (4 IPv4 bytes, then 2 big-endian port
  bytes); it waits at most two seconds and returns zero on timeout. UDP payloads
  are capped at 1024 bytes. Syscall 8 closes TCP and syscall 12 closes UDP.
  All calls return `u64::MAX - 1` on error. QEMU exercises UDP sendto/recvfrom
  against its configured DNS resolver and verifies the response source and
  parsed answer. It also checks TCP endpoint rejection and send-before-connect,
  and attempts a ring-3 TCP connect/close to the resolved test host on port 80;
  this last check is reported as unavailable rather than failing when the
  remote host or network does not accept it. These are early, single-context
  syscalls, not a process-owned descriptor table: there is one preallocated TCP
  socket and one UDP socket, accessible only while the boot smoke context is
  active. General process scheduling, socket ownership/capabilities,
  asynchronous readiness, IPv6 sockets, and robust stream EOF/error
  distinctions are not implemented.
- TLS is deliberately not claimed or enabled. Before a guest TLS client is
  safe, the OS needs a cryptographically secure entropy source for TLS and TCP
  sequence numbers, trustworthy time, bounded certificate-chain and hostname
  validation with a managed trust store, and a maintained no-std TLS stack
  that fits the process/runtime model. The current deterministic network seed,
  absent certificate store, limited process isolation, and lack of socket
  capabilities are not suitable foundations for authenticating cloud or AI
  endpoints. Until those prerequisites are implemented and tested, use the
  host-side encrypted backup client for remote transfers.
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
  question, answer bounds, and IPv4 record before reporting the result.
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
  and both failure policies. This is not a persistent run history.
- Executes workflow blocks whose task manifests use the `elf` runtime. For
  each ready block, in dependency order, the dispatcher re-reads and
  re-validates the task manifest (including every file's size and SHA-256),
  hashes the exact entrypoint bytes again before loading them, and runs the
  static ELF in its own CR3 address space in ring 3. Exit status 0 marks the
  block `Succeeded`; any other status, fault, or refusal marks it `Failed`, and
  the failure policy then skips or preserves dependent work. While a task
  runs, the read-file syscall accepts only the block's declared `inputFiles`,
  syscall 13 (write-file: `RDI` = filename, `RSI` = readable buffer, `RDX` =
  length, at most 16 KiB) accepts only its declared `outputFiles`, and every
  network syscall (4-12) fails. A block succeeds only if it exits 0 and wrote
  every declared output. Output names must end in `.OUT`, so a task cannot
  overwrite manifests, programs, or system files, and a block may read an
  output of a block it directly depends on. The PIT interrupt stops a task
  that runs past its manifest's `runtimeSeconds` and returns to the kernel
  the same way an unhandled user page fault does. Tasks whose manifest requests any
  network capability, or that need the `micropython` runtime, are refused
  rather than run. The boot test stores `INSPECT.ELF`, its `INSPECT.MF`
  manifest, and a two-block `RUN.MF` workflow; both blocks read `INPUT.JSON`,
  echo it to the serial console, and exit 0. A second in-memory workflow
  checks that a MicroPython task, a tampered-digest task, and a
  network-requesting task are refused, that a task reading an undeclared file
  fails with exit 1, that a dependent of a failed block is skipped, and that an
  independent block still succeeds. A third workflow copies `INPUT.JSON` to
  `COPY.OUT` in one block and reads it back in a dependent block, and checks
  that an undeclared write fails, that exiting without a declared output
  fails, and that a `jmp $` task is stopped by its 1-second limit. Its extra
  programs and manifests are built in memory rather than stored, to save
  root-directory slots; the boot test also deletes its `UPDATE.TEST` and
  `RUNTIME.TEST` scratch files after verifying them. Tasks still run one at a
  time inside the boot test context; `memoryBytes` is not enforced beyond the
  loader's page cap, and there is no persistent run log.
  The names reflect current NOSFS constraints (15-byte flat filenames and
  256-KiB maximum file size); the 16-entry root directory is too small for a
  useful multi-task workflow alongside the current boot/test files. SHA-256
  fields verify content integrity, not publisher identity, so executing a
  task proves its bytes match its manifest, not that it was approved.
  Broader execution still needs an approval/authenticity mechanism and
  enforcement of the declared resource limits.
- Persists bounded OS analytics locally on the QEMU data disk. Two rotating
  event-log snapshots and two alternating boot checkpoints are checksummed and
  read back after each update; startup selects the newest intact generation and
  retains the older copy as a fallback. The event ring records stage IDs,
  status codes, sequence numbers, and uptime ticks only. It does not collect
  research contents, prompts, credentials, or network payloads. If both copies
  are invalid or persistence fails, analytics disables itself with a serial
  warning and does not prevent OS boot. This is not a journaled filesystem,
  general rollback system, or agent analytics pipeline.
- The host QEMU integration runner captures the serial transcript from each
  `check` and `check-slaac` run in `os/logs/`, retaining the newest two logs per
  mode. These generated transcripts are excluded from Git but included in the
  encrypted project backup. The interactive `run` mode continues to display
  live output in the terminal.

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
The guest can now dispatch workflow blocks that run static ELF tasks, but
MicroPython tasks are refused because no MicroPython runtime exists in the
guest. The current loader, 256-KiB per-file limit, and minimal read-only file
syscall are not sufficient to load MicroPython. Before Python tasks can run,
the OS needs a stable process ABI, a user-space runtime, and enforced memory
limits. Only approved code may be
executable; downloaded research records remain data, not code.

The host research application has an optional local Ollama integration for
citation-grounded answers (`local_ai_retrieval.py`), but the bare-metal guest
does not currently connect to Ollama, cloud LLM APIs, MCP servers, or other
agents. Ring-3 stdout is a serial-console write, not a guest terminal. The DNS
syscall is limited to a boot smoke test; it is not a general application socket
API, and there is no guest TLS service or model access. A future AI connection
should be an explicitly configured user-space client behind general socket and
TLS services, with per-task destination/data permissions. No provider or
remote AI endpoint is contacted by the QEMU checks.

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
  a host-neutral dated nightly for this subproject only, including `rustfmt`;
  rustup selects its configured host triple.
- QEMU x86_64 (`qemu-system-x86_64`) on `PATH`.
- On Windows, the pre-existing GNU-host Rust toolchain needs a MinGW-w64
  linker. If rustup is configured for MSVC, set
  `$env:RUSTUP_TOOLCHAIN = "nightly-2026-09-27-x86_64-pc-windows-gnu"`
  in PowerShell before invoking Cargo to retain the GNU host.
- On Ubuntu/WSL, install `build-essential`, `ca-certificates`, `curl`,
  `qemu-system-x86`, and `qemu-utils`. Keep the project on its existing host
  filesystem if desired, but set a WSL-local `CARGO_TARGET_DIR` so Linux and
  Windows never share generated artifacts.
- Python 3 is needed for the optional controlled SLAAC router test.
- Network access to download the pinned Rust crates on the first build.

## Build and boot

From the repository root:

```powershell
$env:PATH = "$env:USERPROFILE\.cargo\bin;C:\Program Files\qemu;$env:PATH"
$env:RUSTUP_TOOLCHAIN = "nightly-2026-09-27-x86_64-pc-windows-gnu"
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

For WSL, the following example stores build artifacts in Linux's home
filesystem even when the checkout remains on `/mnt/c`:

```bash
export CARGO_TARGET_DIR="$HOME/.cache/network-os-target"
cd /mnt/c/Users/odaat/network-os-project/os
cargo fmt --all -- --check
cargo check --locked
cargo run --locked -- check
```

Linux and Windows builds have separate artifact directories. For faster
file-heavy builds, a WSL checkout under `~/projects/` is preferable to
`/mnt/c`; use Git to synchronize it rather than building both environments
against one target directory.

This kernel uses direct hardware I/O and DMA and must only be run in the
configured QEMU emulator for this prototype. Do not write its disk image to a
physical drive or use the driver on a physical machine.
