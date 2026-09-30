# network-os-project

A local-first, peer-to-peer research node. It keeps a signed personal
data strand (`digital_dna.py`), gossips signed blocks to peers you
explicitly connect to (`network_os.py`), and runs an autonomous
literature-research agent over **real public biomedical APIs**. Every
module logs to one tamper-evident audit trail, and every run is tied to
a verifiable hash of the exact code state (`project_identifier.py`).

Project material is offered under [CC0 1.0 Universal](LICENSE), to the
extent the person applying CC0 holds or is authorized to waive the
relevant rights. This does not change rights in third-party software,
provider data, datasets, or contributions not authorized for CC0. It
runs on plain Python. It does
not require Claude, an internet account, a subscription, or GitHub to
run — see [Owning your copy](#owning-your-copy).

---

## What it actually does

| Piece | File | What's real |
|---|---|---|
| Identity + chain | `digital_dna.py`, `crypto_layer.py` | Real cryptographic signing; a per-node DNA-encoded strand |
| P2P networking | `network_os.py` | Real sockets; only connects to peers you name explicitly |
| Research agent | `growing_research_agent.py`, `integrated_research_agent.py` | Live queries to ClinicalTrials.gov, PubMed, ClinVar, HGNC |
| Assistant definition | `.claude/agents/Blockchain-DNA.agent.md` | Browser-assisted research instructions for hosts that provide browser/MCP tools; not a standalone daemon |
| JSON research tool | `blockchain_dna_tool.py`, `.claude/skills/blockchain-dna-research/SKILL.md` | Structured source-ID research, provenance/count checks, and explicitly opt-in Python execution |
| Coding research agent | `.claude/agents/Blockchain-DNA-Coding.agent.md` | Cross-language/platform coding and technical research guidance, including schema/environment practices and local/remote command approval boundaries |
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

Run everything (opens a loopback-only node on `127.0.0.1:8765`, seeds one research
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
HOST, PORT = "127.0.0.1", 8765
CONDITION  = "breast cancer"
BIOMARKER  = "BRCA1"
```

## Local DNA-format shell

`dna_shell.py` is a small, local-first command interface built on the
existing A/C/G/T codec and tamper-evident audit trail. The DNA letters
are a reversible encoding of bytes, not biological DNA. Each explicit
encode/decode command records operation metadata and SHA-256 hashes in
`dna_shell_data/audit.jsonl`; it does not put file contents in the audit.
Nothing monitors the computer, collects activity in the background, or
uploads these files.

```bash
python dna_shell.py encode ./document.bin ./document.dna
python dna_shell.py decode ./document.dna ./document-restored.bin
python dna_shell.py inspect-fasta ./dataset.fasta
python dna_shell.py validate-fasta ./dataset.fasta
python dna_shell.py import-fasta ./dataset.fasta
python dna_shell.py import-fasta ./institutional.fasta --classification restricted
python dna_shell.py import-fasta ./known-public.fasta --classification public
python dna_shell.py audit
python dna_shell.py verify
```

Existing output files are preserved unless `--force` is supplied. The
audit file is local and tamper-evident, not tamper-proof: someone with
write access can alter it, and verification will report a broken chain.
Network sharing remains a separate, explicit step using
[`run_node_cli.py`](run_node_cli.py); only configure peers you trust and
review its `--bind`, `--trust`, and firewall guidance before exposing a
node beyond your own machine.

The separate FASTA commands inspect nucleotide sequences as biological
data; they do not use the byte-to-A/C/G/T encoding. Validation accepts
IUPAC nucleotide symbols (`A/C/G/T`, ambiguity codes, and `U`), plus
alignment gaps (`-` and `.`), and reports ambiguous bases, RNA `U`, and
gaps. It rejects empty records and invalid symbols without modifying
the input. `import-fasta` copies a valid file unchanged into
`dna_shell_data/datasets/`, named by its SHA-256, and writes a local
metadata manifest. Imports are classified `private` by default; use
`restricted` for controlled-access EDU/Gov data. Neither classification
can be gossiped. Public status must be explicitly selected and does not
by itself authorize sharing. The audit records counts and a random
dataset ID, not sequences, record names, or the content hash.

For an already-running, trusted `NetworkNode`, public metadata sharing
is an explicit API call:

```python
await publish_public_fasta_summary(
    node, "dna_shell_data/datasets/<local-content-hash>.json",
    confirm_public_metadata_sharing=True,
)
```

That asks the node to send a signed/encrypted block to **all peers
configured on that node**, containing only a random dataset ID, format,
classification, and the dataset SHA-256 digest. It verifies the stored
file against its local manifest first, disables automatic enrichers for
that block, and refuses private/restricted data or missing confirmation.
It never sends the sequence or record names. A digest can still enable
matching/linkage to a known dataset, so sharing is an informed choice,
not anonymization.
Review consent, institutional approval, dataset licenses, and each
peer's identity before sharing; public data is not automatically
cleared for every use.
The local audit records that a broadcast was requested, not that every
peer received it.

For the standalone network runner, research enrichment is opt-in. When
enabled with `--allow-research-gossip`, it shares only hashes and source
provenance, not the returned record. Bitcoin/Ethereum snapshots are also
off by default and require `--allow-external-info`; those are hashed
before they enter a block. Work-sharing results are likewise represented
by a digest and minimal status/provenance rather than the fetched result.
The peer network encrypts data in transit but is not a shared-consensus
blockchain, and data on disk is not encrypted by this feature. Research
API calls still disclose search terms to those external services; never
submit private institutional queries to a public API unless its terms
and your authorization allow it.

### Local encrypted data channel

Raw biological/research files can be stored as authenticated, encrypted
objects in a local vault rather than copied in plaintext. The vault uses
AES-256-GCM in independently authenticated chunks and derives a key from
an interactively entered passphrase with scrypt. File names, source
labels, access class, byte count, and SHA-256 are encrypted inside the
object; the local directory listing reveals only random object IDs. The
encrypted object's total length still reveals an approximate size
(within one 1 MiB chunk).

```bash
python dna_shell.py data-vault-store ./authorized-data.fasta --classification restricted
python dna_shell.py data-vault-list
python dna_shell.py data-vault-inspect <vault-id>
python dna_shell.py data-vault-restore <vault-id> ./restored-data.fasta
```

The vault never stores its passphrase and cannot recover data if the
passphrase is lost. Restore verifies the content hash before finalizing
the output. Existing `import-fasta`, catalog SQLite, and research-session
SQLite paths remain separate local stores and are not retroactively
encrypted by this vault; secure those other files with approved
OS/disk encryption and access controls.

For public data only, a separate explicit command can queue its SHA-256
for publication through the existing signed peer network:

```bash
python dna_shell.py data-vault-publish-hash <vault-id> \
  --data-kind biological_sequence --confirm-public-hash-publication
python run_node_cli.py --id 0 --port 9601 --bind 127.0.0.1 \
  --peers <trusted-host:port> --trust <peer-id>=<peer-signing-key> \
  --provenance-queue dna_shell_data/research_provenance_outbox \
  --workdir ./node_data
```

The vault refuses hash publication unless the encrypted object's
classification is `public`; the additional confirmation is still
required. Private and restricted data hashes stay local. Even a hash can
reveal identity through comparison with a known file or a guessing
attack, so only publish hashes after governance approval. A published
hash is an integrity/linkage value, not a safe substitute for a
de-identified dataset.

### MPC and remote storage boundary

The encrypted vault is local storage, not an MPC implementation. Secure
multi-party computation requires independent participating institutions,
a selected audited protocol/runtime, authenticated identities, agreed
input/output policies, and operational governance. No biomedical data
or hashes are currently sent to an MPC vendor/server. Hashes alone are
not secret shares and cannot be used to compute over underlying data.
If MPC is added later, share creation should happen at each data owner's
site, with raw inputs and keys kept there; the network/ledger should
receive only an approved job identifier and minimal public provenance
after separate review.

`run_all.py` uses the separate legacy peer layer. It now listens only on
loopback by default and configures no peers, but its preset research
condition still goes to public APIs and its research modules can gossip
topics/derived event hashes if you explicitly connect peers. Treat that
path as public-research-only; do not configure private EDU/Gov queries
or connect research peers unless you intend those events to leave the
machine.

## Local research catalog and AI retrieval

The optional catalog stores citation metadata and abstracts in a local
SQLite database. Available public sources include PubMed,
ClinicalTrials.gov, NIH RePORTER, Europe PMC, NCBI ClinVar/dbSNP,
Ensembl, and gnomAD. NCBI E-utilities reads `NCBI_API_KEY` from the
environment when set; it is never stored in the catalog or printed by
the shell. Ensembl lookups expect a human gene symbol, while gnomAD
lookups expect a normalized variant such as `7-140753336-A-T`.
Provider-specific sources can be searched separately:

```bash
python dna_shell.py research-search "BRCA1" --sources clinvar,dbsnp --confirm-public-query
python dna_shell.py research-search "BRCA1" --sources ensembl --confirm-public-query
python dna_shell.py research-search "7-140753336-A-T" --sources gnomad --confirm-public-query
```

For NCBI API-key use in PowerShell, enter it at a masked prompt. The key
is held in the current process environment only; do not put it in source
files:

```powershell
$secureKey = Read-Host "NCBI API key" -AsSecureString
$env:NCBI_API_KEY = (New-Object System.Net.NetworkCredential("", $secureKey)).Password
python dna_shell.py research-search "BRCA1" --sources clinvar,dbsnp --confirm-public-query
Remove-Item Env:NCBI_API_KEY
Remove-Variable secureKey
```

Public API searches require explicit confirmation because they disclose
the query to those providers. For a single public query-to-answer path,
`research-ask` searches selected sources, updates the local catalog,
retrieves matching citations, and sends the query plus retrieved
context to local Ollama:

```bash
python dna_shell.py research-ask "BRCA1" --sources clinvar,dbsnp \
  --model llama3.2 --confirm-public-query
```

To make a later “return to this research” possible, save a run as an
explicitly local-only session:

```bash
python dna_shell.py research-ask "BRCA1" --sources clinvar,dbsnp \
  --model llama3.2 --confirm-public-query --save-session
python dna_shell.py research-history
python dna_shell.py research-recall <session-id>
python dna_shell.py research-forget <session-id>
```

Session saving is off by default. A saved session includes the query,
model answer, model tag, selected source names, and citations so it can
be reviewed later; it is stored in an ordinary local SQLite file and is
not encrypted by this feature or sent to peers. Do not save sensitive
questions unless local storage is authorized and appropriately secured.
`research-forget` removes the database row but cannot securely erase
filesystem remnants or backups. This is research-history recall, not
biological self-recognition and not a remission measure.

Authorized local records can instead be imported from JSONL; they are
private unless an access class is explicitly assigned:

```bash
python dna_shell.py catalog-import-jsonl ./authorized-records.jsonl
python dna_shell.py catalog-context "BRCA1 breast cancer"
```

`catalog-context` formats local retrieved records as citation-linked
JSON for deliberate use elsewhere; it makes no AI request. For a direct
answer, `catalog-ask` can send only the retrieved context to an Ollama
server on a numeric loopback address:

```bash
python dna_shell.py catalog-ask "What does the catalog say about BRCA1?" --model llama3.2
python dna_shell.py catalog-ask "Summarize the cohort" --model llama3.2 \
  --classification restricted --confirm-local-sensitive-context
```

Install Ollama and fetch a model first, for example with
`ollama pull llama3.2`; then ensure the Ollama service is running. Use a
model hosted locally by that instance. This command rejects non-loopback
endpoints and uses direct
HTTP without proxy settings or redirects. The project does not send the
query or retrieved text to a hosted model API, but it cannot verify how
an Ollama server or model is configured; do not use cloud-backed models
for sensitive records. Restricted/private retrieval requires the
separate confirmation flag. Answers include source citations and are
research assistance, not validated scientific conclusions.

To optionally publish research provenance, `research-ask` can place an
event in a local outbox. The event contains only hashes of the query,
retrieved records, and answer, plus source names, the local model tag,
record count, and timestamp.
It excludes query text, record IDs, abstracts, answer text, and sequence
data. Hashes are not anonymization; only do this for public research
where publishing that metadata is acceptable:

```bash
python dna_shell.py research-ask "BRCA1" --sources clinvar,dbsnp \
  --model llama3.2 --confirm-public-query --publish-provenance
python run_node_cli.py --id 0 --port 9601 --bind 127.0.0.1 \
  --provenance-queue dna_shell_data/research_provenance_outbox \
  --workdir ./node_data
```

The first command only queues the digest locally. The second consumes
queued events into signed blocks and gossips them to explicitly
configured, pinned peers. Add `--peers` and `--trust` as described by
`python run_node_cli.py --help` to connect peers. Provenance-queue mode
disables all other enrichers, so retrieved content is not put on-chain.
Every peer that publishes these blocks should use that mode; the peer
protocol cannot force a differently configured remote node to follow
the same payload policy.

NCBI RAS/GA4GH Passport controlled-access integration is not enabled.
It is deferred until an institutional PI authorizes the study and
provides the approved identity provider, repository, scopes, and consent
requirements. API keys do not grant access to controlled datasets.

## Local research/wiki agent

`wiki_agent.py` is a local research librarian, not an autonomous
downloader or a medical decision system. It searches this repository
without indexing hidden/runtime data directories, can query explicitly
selected public catalog providers after confirmation, and can download
a file only when the operator supplies an allowlisted HTTPS URL, a
recognized license declaration, and a download confirmation:

```bash
python wiki_agent.py search "research catalog" --root .
python wiki_agent.py search "BRCA1" --root . --sources clinvar,dbsnp \
  --confirm-public-query
python wiki_agent.py fetch "https://ftp.ncbi.nlm.nih.gov/<reviewed-public-file>" \
  --license CC0-1.0 --confirm-public-download
```

Downloads are capped at 50 MiB by default, redirects are rejected, and
the agent never unpacks or executes downloaded content. Files are
content-addressed under `dna_shell_data/wiki_downloads/` with a
provenance manifest. The license is recorded as **user-declared**, not
independently verified; check the source-specific terms and dataset
license before declaring reuse rights. Unknown/restricted datasets and
authentication bypasses are not supported. Downloads are local only;
they are not automatically added to the catalog, vault, peer network,
or any model prompt.

## Running the tests

```bash
python -m pytest -q
```

The tests deliberately do **not** hit live external APIs (those are
verified by manual runs — see [`KNOWN_GAPS.md`](KNOWN_GAPS.md)) so the
suite stays deterministic.

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

- Nodes split recurring work between them (`work_sharing.py`). The
  supervisor's default configuration performs chain audits only; public
  research and Bitcoin/Ethereum lookups require explicit runner opt-ins.
  When enabled, their network results are reduced to hashes and minimal
  provenance. Each job is assigned to one node; if it's down or slow,
  the next node takes it over after 20 seconds.
- A node that exits is restarted (5s, 10s, 20s ... up to 5 min apart).
- Every day at 08:00 (or at the next logon if the PC was off) the
  supervisor runs the test suite and `run_self_tests.py`, writes `autonomous/reports/<date>.md`,
  archives the day's chains/logs to `autonomous/archive/` (30 days kept)
  and shows a Windows notification saying OK or what needs attention.
- Everything lives under `autonomous/` (gitignored). Signing keys are in
  `autonomous/node-N/keys/` and are never archived or deleted.

## Agent collaboration and daily autonomy

The Blockchain-DNA research and coding agents can complete bounded tasks
when invoked and pass each other source-backed handoffs. If the host cannot
delegate between agents, they follow the companion agent's instructions
sequentially and state that directly.

The host also schedules a daily check at 09:00 local time in the current
project workspace: refresh at most one oldest tracked research topic using
read-only configured public APIs, update its local research store, inspect
repository status, and run the local test suite. It does not edit source
code, install packages, execute remote/cloud terminal commands, or write to
cloud/public chains. These agent processes do not stay alive continuously;
the host starts a new scheduled run.

### Continuous operation across hosts

The daily schedule is not a 24/7 deployment. This repository's local
supervisor uses local files and loopback-bound nodes, so it cannot continue
on a powered-off PC or coordinate with an independent cloud VM. Running
cloud and home-server workers together requires explicit deployment,
secure connectivity, durable shared/reconciled state, leases, idempotent
tasks, retries, duplicate handling, and backups. No such deployment is
configured here. AWS is the selected cloud provider; the home-server
device is not yet identified. The AWS account ID is not stored here, and
the CLI is not installed or authenticated. Provider/model alternatives must be explicitly configured;
the code should have deterministic fallback behavior and must not silently
send data to another AI service.

### Local-first alternative to Supabase

Supabase is optional and is not part of the project's runtime. Its CLI and
`supabase/config.toml` are present only for optional future local Supabase
development; this project does not require Supabase, Docker, or a hosted
database to store its current state. Research topics, chains, audit records,
and node state already persist in local files.

To avoid a hosted database, run the existing Python supervisor on one
always-on computer you control, such as a home server, and use signed TCP
peer nodes for explicitly trusted devices. Start with a single host and
local-only binding. The current supervisor uses local files and loopback;
moving it to another computer does not automatically create a multi-host
supervisor.

For remote access, prefer a private VPN between devices over forwarding
node ports directly from your router. A VPN still requires a powered-on,
reachable home host and secure key exchange; it cannot provide cloud
uptime if home power or internet is down. If multiple hosts perform
research, add shared task IDs and coordination before enabling overlapping
schedules. Provider-specific setup needs the home server OS/network and
approved access method.

---

## Blockchain-DNA JSON research tool

The project's JSON interface offers source-backed research and
deterministic provenance checks:

```powershell
'{"action":"research","condition":"breast cancer","biomarker":"BRCA1"}' |
  python blockchain_dna_tool.py
```

`research` reuses `GrowingResearchAgent` and its existing public API
connectors, and updates the existing `research_store.json` in the current
working directory. It returns source IDs and related-topic IDs rather than
full text, and it does not write to a network node or chain. This action
contacts the APIs; run it only when a live lookup is intended. The existing
runtime's actual connectors are ClinicalTrials.gov, PubMed, ClinVar and a
St. Jude no-op (not configured). HGNC is used when validating candidate
genes for related-topic queuing. This worktree's runtime does not report
per-source status; St. Jude is identified as `skipped` because it is an
explicit no-op, while other sources are marked `not_reported_by_runtime`
rather than guessing success or failure.

`interpret` reports record counts by source, duplicate source/ID pairs and
missing source URLs. It only checks counts and provenance; it does not
assess study quality, scientific validity or causation. Request and response
shapes are documented in [`schemas/`](schemas/).

`execute_python` requires both the CLI `--allow-code-execution` option and
`"user_confirmed": true` in the request, with a maximum five-second timeout
and 64,000-byte captured output. **This is not a security sandbox**: code
runs with the current user's filesystem and network permissions, and those
limits do not prevent side effects. Never execute untrusted code. See the
[Blockchain-DNA research skill](.claude/skills/blockchain-dna-research/SKILL.md)
for the full interface and approval procedure.

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
