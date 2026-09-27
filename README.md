# network-os-project

A local-first, peer-to-peer research node. It keeps a signed personal
data strand (`digital_dna.py`), gossips signed blocks to peers you
explicitly connect to (`network_os.py`), and runs an autonomous
literature-research agent over **real public biomedical APIs**. Every
module logs to one tamper-evident audit trail, and every run is tied to
a verifiable hash of the exact code state (`project_identifier.py`).

It is **MIT-licensed** and **yours**. It runs on plain Python. It does
not require Claude, an internet account, a subscription, or GitHub to
run — see [Owning your copy](#owning-your-copy).

---

## What it actually does

| Piece | File | What's real |
|---|---|---|
| Identity + chain | `digital_dna.py`, `crypto_layer.py` | Real cryptographic signing; a per-node DNA-encoded strand |
| P2P networking | `network_os.py` | Real sockets; only connects to peers you name explicitly |
| Bare-metal OS prototype | `os/` | Separate Rust x86_64 BIOS kernel for QEMU; E1000 driver, DHCP lease, and IPv4/ARP/ICMP self-test |
| Research agent | `growing_research_agent.py`, `integrated_research_agent.py` | Live queries to ClinicalTrials.gov, PubMed, ClinVar, HGNC |
| Assistant definition | `.claude/agents/Blockchain-DNA.agent.md` | Browser-assisted research instructions for hosts that provide browser/MCP tools; not a standalone daemon |
| Coding research agent | `.claude/agents/Blockchain-DNA-Coding.agent.md` | Cross-language/platform coding and technical research guidance, including schema/environment practices and local/remote command approval boundaries |
| JSON research tool | `blockchain_dna_tool.py`, `.claude/skills/blockchain-dna-research/SKILL.md` | Validates structured research requests, reports source IDs/status, summarizes provenance, and offers opt-in local Python execution |
| Extra sources | `multi_source_research.py`, `extended_research_sources.py`, `maxwell_research.py` | arXiv, NIH RePORTER, Europe PMC, PubMed metadata |
| CRISPR suite | `crispr_research_suite.py`, `crispr_guide_design.py` | Literature tracking + a published GC-content guide heuristic |
| Ledger + audit | `token_ledger.py`, `audit_trail.py` | Local per-node score (not a cryptocurrency); append-only audit log |
| Provenance | `project_identifier.py` | Hash manifest tying each run to an exact code state |
| Entry points | `run_all.py`, `run_agent.py` | Launch everything, or just the research agent |

**Honest boundaries** (see [`KNOWN_GAPS.md`](KNOWN_GAPS.md) for the full list):
- `token_ledger.py` balances are a **local score**, not a tradable currency — no consensus, no wallet.
- The CRISPR guide scorer is a **GC-content heuristic** for narrowing candidates, *not* a clinical-grade on/off-target model. Candidates need real wet-lab validation.
- CRISPR results **never mine into the chain** — that boundary is enforced by construction (`node=None, dna=None`).
- Image/video generation is off unless you set your own API keys, and video is deliberately unimplemented.
- The node **connects to no peers on its own**. It reaches only the public research APIs listed above, and only when a topic is explored.

---

## Requirements

- **Python 3.14** (developed and tested on 3.14.6)
- The packages in [`requirements.txt`](requirements.txt): `cryptography`, `numpy`, `matplotlib`, `biopython`, `certifi`, plus `pytest` + `pytest-asyncio` for the tests.

```bash
python -m pip install -r requirements.txt
```

## Quickstart

Run everything (opens a local node on `0.0.0.0:8765`, seeds one research
topic, then idles until Ctrl+C — all state is saved to JSON files beside
the code and reloaded on the next run):

```bash
python run_all.py
```

Just the research agent, no networking node:

```bash
python run_agent.py
```

Edit the block near the top of `run_all.py` to change the seed label,
port, and the condition/biomarker it researches:

```python
SEED_LABEL = "my-research-node"
HOST, PORT = "0.0.0.0", 8765
CONDITION  = "breast cancer"
BIOMARKER  = "BRCA1"
```

## Experimental bootable OS prototype

The project also contains a separate Rust `no_std` x86_64 kernel prototype
in [`os/`](os/). It does not replace Windows and does not run the Python
research application inside the kernel. It boots only in QEMU, drives its
emulated E1000 NIC, obtains an IPv4 DHCP lease, and verifies IPv4 and IPv6
gateway reachability. Its no-heap stack enables UDP, TCP, and IPv6 SLAAC;
however, QEMU's built-in user network sends no router advertisements, so this
runner falls back to a labelled static IPv6 test address. The dedicated
`cargo run -- check-slaac` command runs a local QEMU router-advertisement test
and verifies a real SLAAC address, default route, and ICMPv6 reply. The kernel
also serves a small HTTP health endpoint at
`http://127.0.0.1:18080/health` through a loopback-only QEMU port forward.
`cargo run -- check` verifies network checks and repeated real HTTP requests.

See [`os/README.md`](os/README.md) for toolchain requirements and how to
build, boot, and check it. Keep testing in the emulator; do not write its disk
image to a physical drive.

## Running the tests

```bash
python -m pytest -q
```

As of this writing: **223 tests pass** in about a minute. The tests
deliberately do **not** hit the live external APIs (those are verified
by manual runs — see [`KNOWN_GAPS.md`](KNOWN_GAPS.md)) so the suite
stays deterministic.

To run every component's own built-in self-test (plus short live network
runs) in one go, with a log per component in `self_test_logs/`:

```bash
python run_self_tests.py
```

## Running on its own (autonomous mode)

`node_supervisor.py` keeps 3 nodes running on this PC (local-only,
ports 9611-9613) and writes a report every day:

```bash
python node_supervisor.py --install     # start at every Windows logon, and start now
python node_supervisor.py --status      # what's running
python node_supervisor.py --report-now  # write a report now
python node_supervisor.py --uninstall   # stop and remove the logon task
```

- Nodes split the recurring work between them (`work_sharing.py`): a
  ClinicalTrials.gov lookup every 15 minutes, a Bitcoin/Ethereum
  chain-tip read every 10, and one chain audit every 5 (nodes take turns
  re-verifying each other's chains). Each job is assigned to one node;
  if it's down or slow, the next node takes it over after 20 seconds.
- A node that exits is restarted (5s, 10s, 20s ... up to 5 min apart).
- Every day at 08:00 (or at the next logon if the PC was off) the
  supervisor runs the test suite and `run_self_tests.py`, writes `autonomous/reports/<date>.md`,
  archives the day's chains/logs to `autonomous/archive/` (30 days kept)
  and shows a Windows notification saying OK or what needs attention.
- Everything lives under `autonomous/` (gitignored). Signing keys are in
  `autonomous/node-N/keys/` and are never archived or deleted.

## Blockchain-DNA assistant

The reusable assistant instructions are in
[`.claude/agents/Blockchain-DNA.agent.md`](.claude/agents/Blockchain-DNA.agent.md).
When invoked in a compatible agent host, it can use that host's available
browser and configured MCP tools alongside this project's research APIs.
The assistant is not a continuous browser process. A host automation runs
the two agent roles daily at 09:00 local time: refreshes at most one
already-tracked topic via read-only public API requests (updating only the
local research store), then checks repository status and runs the local
test suite. It does not edit source code, install packages, run remote
commands, or write to cloud/public chains. `node_supervisor.py` separately
continues the project's local nodes and its existing scheduled API work.
Sources without event support are polled according to their schedules.

When the assistant explicitly saves a finding, local storage is the default
where the source permits it. The existing research worker persists source
IDs and topic metadata; it does not archive full source documents. Only a
digest and minimal provenance belong on this project's signed local chain.
This project does not currently upload records to cloud/MCP destinations or
submit transactions to a public blockchain. Those require an explicitly
configured connector and a confirmed destination; the supervisor's
Bitcoin/Ethereum chain-tip reads are public, read-only lookups.

### Continuous operation across hosts

The current Windows supervisor and agent-host daily schedule do not make
this project a 24/7 cross-host service. The supervisor's three nodes bind
to loopback and use local files; they do not coordinate with a cloud VM or
home server. A powered-off PC cannot run its local worker.

Running both a cloud host and a home server simultaneously would require
deployment configuration plus durable shared/reconciled task state,
idempotent task IDs, leases/heartbeats, retry/backoff, duplicate handling,
secure private connectivity, and backups. No cloud or home-server
deployment is configured by this repository yet. Before setting one up,
the user's selected cloud provider is AWS; the home-server device is not
yet identified. The AWS account ID is not stored here, and the CLI is not
installed or authenticated. Approve the exact network exposure, data
handling, and any ongoing cost before provisioning. Collection should continue with
deterministic code if an AI/chat provider is unavailable; switching models
or sending data to another provider must be explicitly configured and
approved.

### Local-first alternative to Supabase

Supabase is optional and is not part of the project's runtime. Its CLI and
`supabase/config.toml` are present only for optional future local Supabase
development; this project does not require Supabase, Docker, or a hosted
database to store its current state. Research topics, chains, audit records,
and node state already persist in local files.

To avoid a hosted database, the simpler path is to run the existing Python
supervisor on one always-on computer you control (for example, a home
server), and use the existing signed TCP peer nodes for explicitly trusted
devices. Start with a single host and local-only binding. The current
`node_supervisor.py` configuration is loopback-only and uses local files;
it does not automatically become a multi-host supervisor when moved to
another computer.

For remote access, prefer a private VPN between devices rather than
forwarding the node port directly from your router. A VPN still requires a
reachable, powered-on home host and secure key exchange; it does not provide
cloud uptime if your home power or internet connection is down. If multiple
hosts independently perform research, add shared task IDs and coordination
before enabling overlapping schedules to avoid duplicate work. The
provider-specific setup is intentionally not automated until the home
server OS/network and access method are known and approved.

### JSON interface and interpreter

The Blockchain-DNA skill uses a JSON request/response interface. For
example, run a source-backed lookup by piping this request to the tool:

```powershell
'{"action":"research","condition":"breast cancer","biomarker":"BRCA1"}' |
  python blockchain_dna_tool.py
```

The research operation reuses this project's ClinicalTrials.gov, PubMed,
and ClinVar connectors, records source status (including failures and
unconfigured sources), and updates `research_store.json`. It returns source
IDs and related IDs, not full text, and does not attach to a network node or
write to a chain. The `interpret` action checks supplied records for source
counts, duplicate IDs, and missing URLs; it does not assess scientific
quality or infer causation. Request and response shapes are documented in
[`schemas/`](schemas/).

An `execute_python` action exists only for user-reviewed code. It requires
both `--allow-code-execution` and `"user_confirmed": true`; execution is
limited to five seconds and captured output to 64 KB. These limits are not
a security sandbox: code runs with the current user's filesystem and
network permissions. Never execute untrusted code. See the
[Blockchain-DNA skill](.claude/skills/blockchain-dna-research/SKILL.md)
for the full contract and approval procedure.

---

## Owning your copy

This project belongs to you and does not depend on any paid service to
keep working:

- **It's just files.** Everything is plain `.py` on your disk. If any
  subscription lapsed tomorrow, nothing here stops working — you run it
  with the Python already on your machine.
- **Local version history (no account needed).** You can keep a full
  history entirely on your own disk, with no remote and no GitHub:

  ```bash
  git init
  git add .
  git commit -m "snapshot"
  ```

  That history lives in `.git/` in this folder. It never leaves your
  machine unless *you* choose to push it somewhere.

- **Back it up somewhere you hold.** Copy this whole folder to a second
  drive or a USB stick. Those copies are yours to keep, restore, or
  delete at any time.

You keep the off-switch. Nothing here runs on its own, reaches beyond
the APIs listed above, or persists anywhere you didn't put it.

---

## Project docs

- [`TRUST.md`](TRUST.md) — what stays open source, and why
- [`PROTOCOL.md`](PROTOCOL.md) — the wire/gossip protocol
- [`KNOWN_GAPS.md`](KNOWN_GAPS.md) — what's verified vs. structurally-correct-but-unrun, disclosed plainly
