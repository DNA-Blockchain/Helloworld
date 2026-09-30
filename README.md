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

See [NOTICE.md](NOTICE.md) for the author's authorship and ownership
declaration. It does not replace or narrow the existing CC0 license.

---

## What it actually does

| Piece | File | What's real |
|---|---|---|
| Identity + chain | `digital_dna.py`, `crypto_layer.py` | Real cryptographic signing; a per-node DNA-encoded strand |
| P2P networking | `network_os.py` | Real sockets; only connects to peers you name explicitly |
| Bare-metal OS prototype | `os/` | Experimental Rust x86_64 QEMU kernel; E1000 dual-stack tests, cooperative context switching, bounded static ELF64 ring-3 loader, limited file/stdout/DNS smoke-test syscalls, QEMU IDE block access, and experimental NOSFS flat-file storage. It does not run the Python research agent or provide general user sockets/TLS. |
| Research agent | `growing_research_agent.py`, `integrated_research_agent.py` | Live queries to ClinicalTrials.gov, PubMed, ClinVar, HGNC |
| Assistant definition | `.claude/agents/Blockchain-DNA.agent.md` | Browser-assisted research instructions for hosts that provide browser/MCP tools; not a standalone daemon |
| Coding research agent | `.claude/agents/Blockchain-DNA-Coding.agent.md` | Cross-language/platform coding and technical research guidance, including schema/environment practices and local/remote command approval boundaries |
| JSON research tool | `blockchain_dna_tool.py`, `.claude/skills/blockchain-dna-research/SKILL.md` | Validates structured research requests, reports source IDs/status, summarizes provenance, and offers opt-in local Python execution |
| Extra sources | `multi_source_research.py`, `extended_research_sources.py`, `maxwell_research.py` | arXiv, NIH RePORTER, Europe PMC, PubMed metadata |
| CRISPR suite | `crispr_research_suite.py`, `crispr_guide_design.py` | Literature tracking + a published GC-content guide heuristic |
| Ledger + audit | `token_ledger.py`, `audit_trail.py` | Local per-node score (not a cryptocurrency); append-only audit log |
| Provenance | `project_identifier.py` | Hash manifest tying each run to an exact code state |
| Live data store | `live_store.py`, `live_feed.py` | Local SQLite mirror of everything saved, streamed live over loopback-only HTTP/SSE |
| Entry points | `run_all.py`, `run_agent.py` | Launch everything, or just the research agent |
| RabbitSoftware assistant | `rabbit.py`, `rabbitsoft/` | Ask the OS about itself in your own words, in a terminal or a web page on this PC |

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

New PC? [GETTING_STARTED.md](GETTING_STARTED.md) is a step-by-step
checklist covering Windows and WSL, the software, the code and tests, the
nodes, the DNA twin and swarm, the local AI, the Alpine and Rust OS builds,
and EEG and radio hardware.

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
also validates a 100 Hz PIT timer, physical-frame allocation/release, and
kernel virtual-page mapping/unmapping. It serves a small HTTP health endpoint at
`http://127.0.0.1:18080/health` through a loopback-only QEMU port forward.
`cargo run -- check` verifies network checks and repeated real HTTP requests.

See [`os/README.md`](os/README.md) for toolchain requirements and how to
build, boot, and check it. Keep testing in the emulator; do not write its disk
image to a physical drive.

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

## Split research agent (host fetch, kernel analysis)

The kernel has no TLS, so the research agent is split. `research_fetch.py`
retrieves public records on the host through
`research_catalog.search_public_sources` (PubMed, Europe PMC,
ClinicalTrials.gov, NIH RePORTER) and writes a bounded `RESEARCH.JSON`
(public records only, abstracts trimmed, at most 64 KiB).
`research_analysis.py` validates, de-duplicates (by source ID and by
normalized title across sources), scores by query-term matches and recency,
ranks, and hashes every record; the output is capped at 16 KiB.

```powershell
python research_fetch.py --query "CRISPR cancer" --term crispr --term cancer --analyze
python research_fetch.py --query "CRISPR cancer" --output RESEARCH.JSON
python research_analysis.py RESEARCH.JSON --output RANKED.OUT
python research_fetch.py --fixture --analyze    # offline synthetic sample
```

`research_analysis.py` is MicroPython-compatible (integer scores, no project
imports), and `build_task_bundles.py` packages it with the synthetic sample
as `os/tasks/research/`, which the kernel runs at every boot check. The
sample includes Greek letters, dashes, Unicode spaces and characters outside
the BMP, and the boot check fails unless the kernel's ranking matches
CPython's byte for byte (`OUTPUT.SHA256`). The kernel's MicroPython `str`
methods only know ASCII, so the module spells out its own text rules
(CPython's whitespace set, ASCII case folding). Scores order reading, not
evidence.

To have the kernel rank freshly fetched records, run the OS in research mode:

```powershell
python research_fetch.py --query "CRISPR cancer" --output RESEARCH.JSON
cd os
cargo run -- research ..\RESEARCH.JSON ..\RANKED.OUT
cargo run -- research-batch ..\requests ..\rankings   # every *.json (up to 50) in one boot
```

The runner mounts the QEMU data disk with the kernel's own NOSFS code,
stores the requests as `HOSTIN00.JSON`, `HOSTIN01.JSON`, ..., and runs the
full boot check once. The kernel runs the research task on each in ring-3
MicroPython (a manifest that pins the script; the records are a declared
data input) and saves the rankings as `HOSTOUTnn.JSON`, which the runner
copies out under each input's file name. A request that the task rejects,
such as a non-public source, is reported in the serial log and produces no
ranking; the others and the rest of the boot check still run.

### Publishing ranked records to the node chain

```powershell
python research_publish.py RANKED.OUT                        # dry run: shows what would go on-chain
python research_publish.py RANKED.OUT --confirm-publication  # queue it permanently
```

`research_publish.py` builds a `public_research_records` event holding each
ranked record's source, ID, title, URL, date and SHA-256 (at most 20
records, 32 KiB), validated by `research_provenance.py`. Abstracts are never
published: their reuse rights are unknown and a chain entry cannot be
withdrawn. The event goes into `autonomous/research-outbox`; node-0, which
`node_supervisor.py` starts with `--provenance-queue` alongside work sharing,
mines it into a signed block and gossips it to its peers. Patient, genomic
and other private data never go on the chain.

### Research ledger: every node keeps a copy, and you can browse it

Node chains are archived daily and the archive is pruned after 30 days, so
published research lives in a separate, permanent
`autonomous/node-N/research_ledger_node-N.json` on every node
(`research_ledger.py`). Each entry is the original signed block carrying a
`public_research_records` or other provenance event, or a
`public_dataset_summary` from `dataset_sharing.py`. A node adds an entry
when it mines or verifies such a block, backfills from its own current and
archived chains at startup, and every two minutes pulls new entries from
its peers' ledgers over the existing encrypted sessions, keeping only
blocks that verify against the origin node's pinned signing key. The ledger
file is itself hash-linked, so tampering is detectable.

```powershell
python research_viewer.py      # http://127.0.0.1:8791
```

The viewer is local and read-only: a searchable page of published records
and datasets with how many nodes hold each copy, plus JSON endpoints
(`/api/records?q=...&source=...`, `/api/records/<source>/<id>`,
`/api/datasets`, `/api/events`, `/api/status`) and `/api/export`, which
downloads everything with the original signed blocks for independent
verification.

To publish what the growing research agent collected earlier:

```powershell
python research_backfill.py                          # dry run
python research_backfill.py --confirm-publication    # queue for node-0
```

`research_store.json` keeps only IDs, so `research_backfill.py` re-fetches
each record's title, date and link by ID (`pubmed_summaries`,
`trials_by_id`, `clinvar_records_by_id`), ranks each source's records with
`research_analysis.py`, and queues one event per 20 records. Besides
`research_store.json` it reads the research stores and the research corpus
of past live runs mirrored in `live_store.db` (such as the CRISPR suite's
`crispr_store`). Records already in any node's ledger are skipped, so it can
be re-run safely; sources without a fetch-by-ID connector (such as `stjude`)
are reported and skipped.

New research comes from the agent's own queue of related topics it
discovered (`research_store.json` and the mirrored stores' `queue`):

```powershell
python research_queue.py                                  # dry run
python research_queue.py --kernel --confirm-publication   # rank the topics in the OS kernel
```

Every queued topic is fetched first, then all are ranked (in the kernel with
`--kernel`: one `cargo run -- research-batch` boot per 50 topics, about 30
seconds instead of 35 per topic), and published without repeating topics or
records already on the chain.

The nodes can also share this work. While
`autonomous/publish-research-topics.confirmed` exists, `node_supervisor.py`
starts every node with `--publish-research-topics`: each work-sharing
research round (every 15 minutes) is assigned to one node, which fetches and
ranks the next unpublished queued topic and mines the
`public_research_records` event in its work block. If that node is down, the
next in line takes over. Delete the file (and restart the nodes) to stop.

### Swarm-verified twin analyses

With `--work-sharing --swarm`, every round has two extra jobs
(`swarm_analysis.py`):
- **Scan:** one node runs the DNA twin's RNA analyses (siRNA scan and
  protein-change lookups) on a subject and publishes the result's SHA-256.
- **Check:** a different node recomputes the same subject and publishes its
  own SHA-256. The node that ran the scan is never in line for the check.

Each node tallies what it sees. A result is **ACCEPTED** when two distinct
nodes published the same digest, **DISPUTED** when digests differ, and
**UNCONFIRMED** when no second node has checked yet. Every node logs verdicts,
and each node's summary lists them on exit.

Subjects are public sequences already on the chain (`public_sequence_record`),
or, when there are none, eight fixed synthetic sequences every node derives
identically. A person's sample is never a subject, and only digests and
subject ids go into blocks. Agreement shows that two nodes ran the same code
on the same input and got the same answer. It doesn't make an siRNA score
biologically right.

```sh
python run_node_cli.py --id 1 --port 9601 --peers 127.0.0.1:9602,127.0.0.1:9603 --tofu --work-sharing --swarm
python3 linux/swarm.py     # the same across three Alpine VMs (linux/README.md)
```

`swarm_explain.py` explains accepted results in plain language with local
Ollama. It first recomputes the subject's analysis and refuses unless the
SHA-256 matches the one the swarm accepted. It then prints the facts, written
by code, followed by the model's explanation of only those facts. Output that
drifts into treatment or medical language, states a number the facts don't
contain, or gets a hydropathy direction wrong is withheld. It uses
`nos-explain` (built by `python local_ai_tuning.py create`), which passed 8
of 8 test cases where plain `llama3.2:3b` passed 0, or `llama3.2:3b` if
`nos-explain` isn't built. Explanations are labelled "may be wrong" and are
never published.

```sh
python run_node_cli.py ... --work-sharing --swarm --status-file node1_status.json
python swarm_explain.py --status-file node1_status.json      # AI explanations of ACCEPTED rounds
python swarm_explain.py --subject synthetic:3 --no-ai        # the verified facts only
```

### Signal lab: EEG, radio and network signals

`signal_lab.py` moves real or simulated signals between any source and any
sink (`signal_io.py`). Only the spec string changes when hardware arrives:

| Source | Simulated today | Real hardware later |
|---|---|---|
| EEG | `eeg:synthetic` (BrainFlow's simulated board) | `eeg:cyton?serial_port=COM3`, `eeg:ganglion?...`, or any BrainFlow board (`signal_lab.py devices`) |
| Radio | `rf:sim`, recordings `rf:file:x.cu8?rate=2.4e6` (.cu8 .cs8 .cf32) | `rf:soapy:driver=rtlsdr?freq=100e6&rate=2.4e6`, any SoapySDR radio |
| Network | `udp:127.0.0.1:9700` in and out | `udp:<host>:<port>` with `--allow-remote` |

```sh
python signal_lab.py bridge --source eeg:synthetic --sink stats --seconds 5
python signal_lab.py send-twin --twin run.json --sink file:twin.cs8           # the twin as a radio packet
python signal_lab.py receive-twin --source "rf:file:twin.cs8?rate=250e3" --twin run.json
python signal_lab.py eeg-control --source eeg:synthetic --twin run.json      # alpha rhythm steps the twin
```

`send-twin` sends a twin's sequence as an ordinary digital radio packet:
2 bits per base, a sync word, a CRC-32, and continuous-phase binary FSK.
`receive-twin` decodes it from a recording, a radio or the network, and only
returns a sequence whose CRC matches. In tests it decodes exactly with 12 dB
SNR and a 3 kHz tuning error. The DNA has no radio frequency of its own; the
radio is simply carrying data. `eeg-control` calibrates a per-person
baseline, then emits `select` when alpha (8-12 Hz) rises well above it (eyes
closed) and `next` when it drops back. That's a band-power threshold, not a
medical measurement.

The rules:
- **Network:** traffic stays on this machine unless `--allow-remote` is given.
  Leaving it requires `SIGNAL_LINK_KEY` on both ends, which signs every
  datagram with HMAC-SHA256 and drops unsigned, forged, replayed and stale
  frames. EEG is personal data.
- **Transmitting is regulated,** and interference can hit emergency and
  aviation services. An over-the-air sink only opens with `--transmit` **and**
  a `signal_tx_policy.json` naming the operator and the bands they may use
  (see `signal_tx_policy.example.json`). The whole signal must fit inside one
  band, and airtime is capped per band. The policy file is git-ignored.
  Receiving, recordings and simulation are unrestricted.
- **Real radios:** `sudo apt install python3-soapysdr soapysdr-module-all`,
  create the venv with `--system-site-packages`, and attach the USB device to
  WSL with `usbipd`.

### When was it published?

Every event published by these tools carries a `time_anchor`: the Bitcoin
block at the tip when it was created (from blockstream.info, or
mempool.space), which proves the event is no older than that block.
OpenTimestamps proves the other side, that the event existed by a later
block:

```powershell
python research_timestamps.py stamp     # submit each ledger event's digest to public calendars
python research_timestamps.py upgrade   # hours later: fetch the Bitcoin attestations
python research_timestamps.py status
```

Proofs are stored as `autonomous/timestamps/<event_id>.ots` and served by the
viewer at `/api/timestamps/<event_id>.ots`; the viewer shows both times.

### RabbitSoftware assistant

RabbitSoftware answers questions about this OS in short, plain sentences:
how the nodes are doing, blockchain checks and audits, the token ledger,
the research agents, the activity log, the latest daily report, swarm
subjects, and research questions answered from saved records with
citations. It's built for people who find the right words or spelling hard:
misspellings are fixed and shown back ("I read that as…"), choices are
numbered, and the web page has large text, full keyboard use, screen-reader
announcements and works with Windows voice typing (Windows key + H).

```powershell
python rabbit.py chat                        # terminal
python rabbit.py web                         # web page at http://127.0.0.1:8792
python rabbit.py ask "how are the nodes"     # one question
```

It runs on this PC's own AI through Ollama and reaches no other service,
except a public research search, which asks first ("This sends the words …
Send it?") and is written to the activity log as a hash of the query, not
its text. The web page answers only on 127.0.0.1 and refuses requests from
other websites open in the same browser.

### Plain-language summaries (local AI)

`research_summaries.py` rewrites each published record's title as one
plain-language sentence with a local Ollama model: `nos-summary`, which is
`llama3.2:3b` (free, about 2 GB) with instructions for this job, or
`llama3.2:3b` itself if `nos-summary` isn't built. It only ever talks to
Ollama on this machine. Summaries are machine-generated and can be wrong;
the viewer shows them under the real title, labelled "may be wrong, not
evidence". `local_ai_tuning.py` measures the models against each other.

```powershell
ollama pull llama3.2:3b
python local_ai_tuning.py create                                    # builds nos-summary and nos-explain
python research_summaries.py run --limit 5                          # local only
python research_summaries.py run --limit 10 --confirm-publication   # also hash-only events on the chain
python research_summaries.py status
```

Summaries live in `autonomous/summaries/summaries.json`. With
`--confirm-publication`, each batch of up to 20 gets a hash-only provenance
event (SHA-256 of the records and of the summaries, plus the model name, with
no text on the chain), and the viewer marks a summary "hash on chain" once
its batch verifies against the mined event. Runs use half the CPU threads
and stop early when the PC is over 75% busy. While
`autonomous/research-summaries.confirmed` exists, `node_supervisor.py` runs
a batch of 10 every 10 minutes at below-normal priority; delete the file to
stop.

### Linking research to CRISPR work and to modeled runs

```powershell
python research_crispr_link.py tag                       # dry run
python research_crispr_link.py tag --confirm-publication
python research_crispr_link.py link-run run.json --gene BRCA1 --sequence-file brca1.txt
python research_crispr_link.py status
```

`tag` reads each published record's own title and publishes a
`public_crispr_relevance` event with the CRISPR work it mentions (`crispr`,
`base_editing`, `guide_rna`, `knockout`, `screen`, `delivery`,
`gene_therapy`, ...) and the gene symbols it names. A tag describes the
title's wording; it is never a judgment that the research supports an edit or
a treatment. The method (`title-keywords-v1`) is published with it.

`link-run` publishes a `public_model_run_record` for one
`remission_workflow.py` result: its hash, what the model reported, its
hash-linked stage ledger (so the difference detection, the modeled edit and
the verification are each provable in order), an optional PAM-scan summary,
and the tagged records for that gene. The model-only disclaimer is carried
verbatim and enforced by the validator.

**Sequences on the chain.** `--publish-sequences` puts the run's reference,
sample and edited sequences on the chain as `public_sequence_record` events,
but only for a `public_reference` (with `--accession`, e.g. an NCBI RefSeq
entry that is already public) or a `synthetic` case. A sequence from a
person's sample is refused, by the constructor and again by the validator: a
genome identifies its owner and their relatives for life, the chain is
append-only and replicated to every node, and consent cannot be taken back
from it. For those cases only hashes are published.

### Variant significance and clinical context

Neither of these is published: one is a cache of someone else's public
assessments, the other is clinical detail about a person.

```powershell
python twin_context.py clinvar BRCA1 --fetch    # cache ClinVar's classifications
python twin_context.py clinvar BRCA1            # read the cache offline
python twin_context.py context --set ER+ --set HER2- --set G2 --label "case A"
```

`twin_context.py clinvar` fetches **ClinVar's own** reported classification for
a gene's variants (`Pathogenic`, `Likely pathogenic`, `Uncertain significance`,
...) with its review status, when it was last evaluated, the conditions named,
and a link, and caches it under `autonomous/clinvar/`. Every row is attributed
to ClinVar and its submitters; the project never restates it as its own
judgment, and a reported significance is not a treatment.

Those cached rows can go on the chain, since they are public metadata from a
public database:

```powershell
python twin_context.py clinvar BRCA1 --publish                       # dry run
python twin_context.py clinvar BRCA1 --publish --confirm-publication
```

A `public_variant_classification` event carries, per variant, the accession,
gene, variant title, **ClinVar's** reported significance, its review status,
when it was last evaluated, the conditions named, a link to the source record,
and a hash of the row so it can be checked for alteration later. The event
must attribute the classification to ClinVar and its submitters, and the
validator enforces that wording; accessions already on the chain are skipped,
so it can be re-run.

`twin_context.py context` records reported tumour annotations for a case (ER,
PR, HER2, triple-negative, grade G1-G3, stage 0-IV). Anything it does not
recognise is refused rather than guessed at. **Context never changes the
modeled edit**: receptor status describes which proteins a tumour makes and
hormones change what a gene transcribes, not which bases it carries, so there
is no step from an annotation to a base to change. What it does is choose
which published research the twin shows first, through the tags below.

Research tags cover that regulatory side too (`hormone_signalling`,
`methylation`, `expression` alongside `crispr`, `base_editing`, `guide_rna`,
...), so endocrine, epigenetic and expression research is linked and
searchable next to the editing literature.

### DNA digital twin

```powershell
python remission_workflow.py --output run.json
python dna_twin_viewer.py run.json --gene BRCA1 --frame 1 --open
python dna_twin_viewer.py --baseline brca1_reference.txt --export-dataset twinset
python dna_twin_viewer.py --from-chain <run_event_id>
```

`dna_twin_viewer.py` writes one local, self-contained HTML page for a modeled
run:

- **The double helix**, verified double: every rung is an A-T or C-G pair and
  the second strand's 2-bit code is exactly the bitwise NOT of the first. The
  complement comes from `dna_binary_codec.complement_strand`, not from the
  page, and the check is shown on screen.
- **The binary code** of each strand (A=00 C=01 G=10 T=11), with the
  complementary strand beside it.
- **The edit as bit flips**: restoring the baseline at a position is an XOR
  with a 2-bit mask, and the whole edit is one mask over the sequence. The
  page reports how many bits flip and verifies that applying the mask to the
  sample reproduces the baseline.
- **The protein consequence**: the codon each difference falls in, read
  through the standard genetic code, with the amino acid change and its class
  (synonymous, missense, nonsense, stop_lost, start_lost). A table lookup,
  meaningful only in the sequence's real reading frame (`--frame`).
- **Guide-RNA candidates** near a difference, as an efficiency heuristic.
- **The chain's tagged research** for the gene, and the run's stage ledger.

`--baseline` builds a **cancer-free baseline twin** from a reference sequence:
the baseline every modeled edit restores. `--export-dataset` writes the twin
as packed 2-bit binary (4 bases per byte, round-tripping through the
project's own codec) with a manifest of hashes and a `SAMPLE.JSON` in the
shape `os/tasks/remission` already takes, so the kernel's MicroPython can
model the same sequences. `--from-chain` rebuilds the twin from published
sequence events alone, recomputing the differences from the chain.

The twin's RNA layer (`twin_rna.py`) reads the sample as mRNA and adds three
lookups to the page:
- **The tRNA anticodon of each changed codon:** the exact reverse complement,
  5'→3', with wobble pairing ignored.
- **The side-chain class and Kyte-Doolittle hydropathy on each side of a
  missense change:** for example, Val → Asp is nonpolar → negative with charge −1.
- **An siRNA candidate scan:** 19-base windows of the sample scored with the
  Reynolds et al. 2004 criteria, with windows covering a difference from the
  reference listed first. These are design heuristics. No siRNA is tested,
  off-target matches aren't checked, and a window covering a difference isn't
  shown to spare the reference allele.

The page is local and is not published: a run of a person's sample holds
their genomic data. Nothing in the twin is a treatment. The modeled edit is a
string substitution, `MODELED_REFERENCE_MATCH` is a statement about strings,
and clinical remission is only ever copied from supplied, attributed clinical
evidence.

### Corrections

The chain is append-only, so a published record is fixed by publishing a
`public_research_correction` event that names the event and records it
supersedes, the corrected title and hash, and the hash it replaces:

```powershell
python research_corrections.py                        # audit: re-fetch and check every record
python research_corrections.py --confirm-publication  # queue corrections for proven damage
```

It corrects only records whose published hash is exactly what the kernel's
earlier text-decoding fault computes from the source record. The viewer
shows the corrected title and hash, and what was first published.

Public reference datasets are published as metadata plus a hash; the
sequence stays off the chain:

```powershell
python dataset_publish.py NM_007294.4 NM_000059.4 NM_000546.6 --confirm-publication
```

`dataset_publish.py` downloads each NCBI nucleotide accession as FASTA into
`autonomous/datasets/`, validates it with `dna_shell.py`'s FASTA checks, and
queues a `public_dataset_record` (accession, title, counts, SHA-256, NCBI
link). The viewer lists datasets and serves the local FASTA at
`/api/datasets/<dataset_id>/fasta` only while it matches the published hash.
Node-0 publishes queued events about one per second, and sets aside any
outbox entry it cannot validate in `research-outbox/rejected/` instead of
stopping.

## Cancer -> modeled reference match workflow

`remission_core.py` runs the whole computational workflow in one pass:
reference/sample comparison, `MUT-000001`-style mutation records, 2-bit
binary DNA (`A=00 C=01 G=10 T=11`, matching `dna_binary_codec.py`), a
string-level CRISPR edit model, post-edit verification, follow-up
comparisons over time, and a SHA-256 hash-linked ledger of every stage.

```powershell
python remission_workflow.py                         # synthetic demo (ACGTACATACGT -> ACGTACGTACGT)
python remission_workflow.py --input case.json --output result.json
$env:REMISSION_VAULT_PASSPHRASE = "..."; python remission_workflow.py --vault
```

The ledger holds only digests; the full records (which contain sequences)
are returned separately and `--vault` encrypts them with
`EncryptedDataVault`, so sequences never go on a chain. The CRISPR step is
a string transformation, not guide-RNA design or a biological edit.
`MODELED_REFERENCE_MATCH` is kept separate from
`CLINICALLY_CONFIRMED_REMISSION`, which is only ever copied from supplied,
attributed clinical evidence (`clinical_evidence.assessed_by`/`assessed_on`).
Insertions/deletions are not modeled (sequences must be equal length).

The same file is packaged for the Network OS as a MicroPython task bundle
in `os/tasks/remission/` (`REMISSION.PY`, `SAMPLE.JSON`, `RMTASK.JSON`,
`RMFLOW.JSON`, following `os/schemas/`). Regenerate it after editing
`remission_core.py` with `python build_task_bundles.py`; the tests fail
if it is stale. The kernel embeds this bundle and runs it at every boot check:
`REMISSION.PY` executes in its ring-3 MicroPython runtime, reads the declared
`SAMPLE.JSON` input, and writes the declared `RESULT.OUT` output (on the OS,
`main()` writes `RESULT.OUT`; elsewhere pass `--output PATH`). The boot check
requires the output to be byte-identical to CPython's (`OUTPUT.SHA256`). The
bundle also runs under the WSL MicroPython Unix port.

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

### Live data store

`live_store.py` mirrors everything the modules save into one local SQLite
file as it happens: chain blocks, audit entries and token-ledger
transactions as append-only events, plus the latest DNA strand state,
network ledger, research store, corpus, node status and supervisor totals
as snapshots. The JSON files stay the source of truth (their hash chains
are what `verify_chain()` checks); the database is a queryable, live copy.
A failed database write is logged once and never stops a node.

It is on in `run_all.py` (`live_store.db`, feed on port 8790; set
`LIVE_DB` / `LIVE_FEED_PORT` to `None` to turn off) and in
`node_supervisor.py` (`autonomous/live_store.db`, shared by all nodes). For
a single node, pass `--live-db PATH` to `run_node_cli.py` or set
`NETWORK_OS_LIVE_DB`.

Watch it live with `live_feed.py`, which binds loopback only because the
database includes your DNA strand state:

```bash
python live_feed.py --db autonomous/live_store.db     # supervisor's nodes
curl -N "http://127.0.0.1:8790/stream?stream=chain"   # Server-Sent Events
curl "http://127.0.0.1:8790/events?after=0&stream=audit"
curl "http://127.0.0.1:8790/snapshot?stream=status&key=node-0"
```

The kernel prototype reports into the same store: `os_live_bridge.py`
runs `cargo run -- check` (or `--mode check-slaac`) in `os/` and records
each boot milestone (PIT timer, frame allocator, E1000, DHCP, ICMP,
IPv6, HTTP health) as stream `os`, plus a pass/fail snapshot tied to the
git commit it tested:

```bash
python os_live_bridge.py --audit system_audit.jsonl
curl "http://127.0.0.1:8790/snapshot?stream=os&key=check"
```

### Data retention

`retention.py` decides how long each live-store stream is kept and
enforces it. By default chain blocks, audit entries and ledger
transactions are kept forever (the tamper-evidence depends on them),
node status ages out after 30 days, other operational streams after
90-365 days, and personal DNA state is never deleted by age -- only by
an explicit `forget`. Deleted rows are overwritten and the database is
compacted, so they don't linger in the file; each run is logged to the
audit trail as counts only. `node_supervisor.py` applies it daily (policy
override: `autonomous/retention_policy.json`).

```bash
python retention.py show-policy
python retention.py plan                       # dry run
python retention.py apply --audit system_audit.jsonl
python retention.py forget --stream dna --key my-research-node --confirm
```

`forget` removes data from the live store only; the module's own state
file (e.g. `dna_state.json`) still holds it until you delete that too.
Backups and copies elsewhere are not touched.

### Encrypted backups

`backup.py` snapshots the project source, Git history, schemas, tests,
documentation, runtime state, and engineering logs, then encrypts the archive
as one `encrypted_data_vault.py` object and decrypts it end to end to verify
it before it counts. SQLite databases use SQLite's online backup API, so a
running node's database is copied consistently. Private-key directories and
common key/credential file patterns are excluded. Build caches, dependencies,
and generated targets are excluded, except the OS persistent QEMU disk image
(`os/target/network-os-persistent.img`) so guest checkpoints are preserved.
Backups go to `~/network-os-backups` outside the repository, but on the same
machine/disk; they do not protect against disk loss. Cloud copy remains
disabled unless separately configured. Anything older than 30 days is pruned,
always keeping the newest 7.

```powershell
python backup.py init                        # once: passphrase, stored with Windows DPAPI
.\install_backup_task.ps1                    # nightly at 02:30 (retention first, then backup)
python backup.py list
python backup.py verify
python backup.py restore latest --to C:\restore-test   # never writes over existing files
python backup_health.py test-restore          # verify restore into a temporary directory
```

The guest also keeps local-only OS analytics in two rotating, checksummed
event-log files and two alternating boot-checkpoint files on the QEMU data
disk. The latest valid generation is selected on boot; the previous intact
copy is the fallback if one copy is damaged. The bounded log contains stage
IDs, status, sequence numbers, and uptime ticks only—not research content,
prompts, credentials, or network payloads. If both copies are invalid or a
write/readback fails, guest analytics disables itself and the OS continues
booting with a serial warning. These are engineering diagnostics/checkpoints,
not a journaled filesystem or a substitute for the encrypted host backup.

The DPAPI copy of the passphrase only works for your Windows account on
this PC. Keep your own copy (a password manager): if this PC is lost,
the backups can't be decrypted without it.

### Off-site copy (Amazon S3)

`offsite_s3.py` uploads each encrypted backup (and the name-free index)
to S3 after every nightly run, with an S3-verified SHA-256 on upload and
a checksum comparison afterwards; a backup only counts as off-site once
they match. Uploads never overwrite an existing object, and anything that
fails (offline, AWS down) is retried on the next run, before local
pruning. AWS only ever receives ciphertext; the passphrase stays here.

`aws_backup_setup.ps1` prepares a private, versioned, TLS-only S3 bucket
with a lifecycle policy. It does not create IAM users or long-lived access
keys and does not upload data by default. Use separate short-lived AWS IAM
Identity Center profiles for administration and backup access; the backup
role's narrowly scoped permissions must be granted separately. S3 versioning
is a recovery window, not immutable retention, and this setup does not yet
configure CloudTrail or Object Lock. The script requires exact bucket-name
confirmation, reports the resource/cost categories, and requires a second
confirmation before enabling local upload configuration. Review the script
and current regional pricing before running it. No AWS resources are
provisioned by the repository's tests.

```powershell
python offsite_s3.py status
python offsite_s3.py sync
python offsite_s3.py pull all-missing     # new PC: fetch backups, then backup.py restore
```

### Backup health and test restores

`backup_health.py` checks that backups are really happening: the newest
is under 36 hours old and verified, the passphrase loads, every backup
older than that is confirmed in S3, the last sync had no errors, there's
at least 1 GB free, and the nightly task exists and last ran cleanly.
Once a week, after the nightly backup, it restores the newest backup into
a throwaway folder -- every file checked against its SHA-256, every SQLite
database integrity-checked, every JSON file parsed -- and downloads and
decrypts the newest S3 copy too. Problems raise a desktop notification
and appear in the supervisor's daily report; results go to
`test_restores.jsonl` and the audit trail.

```powershell
python backup_health.py check          # [ALERT] lines, exit 1 if any
python backup_health.py test-restore   # run a test restore now
```

### Finding work across local disks

`recovery_index.py` builds a local, read-only SHA-256 inventory for directories
you name, such as a project folder, backup directory, or mounted external drive.
It does not scan other disks automatically, retain or display file contents,
change source files, or contact a network; it reads file bytes locally to
compute hashes. The index stores paths, sizes, timestamps, and hashes in
`~/.network-os/recovery-index.sqlite3` by default; pass `--db` to put it on a
protected local disk. Credential directories and common key/secret file types
are skipped. Disconnecting a drive leaves its old inventory entries available
and search reports whether a recorded path currently exists.

```powershell
python recovery_index.py scan C:\Users\you\Documents E:\old-projects
python recovery_index.py search "research"
python recovery_index.py duplicates
```

This can find an indexed file that moved, an exact duplicate on another
selected disk, or a path that is no longer accessible. It cannot recover file
contents from a hash alone; use a verified encrypted backup or another
surviving copy. The existing local `chain_store.py` verifies its own
tamper-evident hash links, but it has no consensus and by itself proves neither
the current identity's ownership of a file nor theft. The peer protocol has
signed identities and chain-block checks, but not a cross-peer file recovery
or ownership-claim protocol yet. A future opt-in network search should verify
the user's pinned public key and signed content digests, disclose no file
contents or local paths by default, and treat matches as evidence to review,
not proof of theft. Network/chain searches and uploads are not run by this
local index. The proposed policy contract in
[`schemas/recovery-search-v1.schema.json`](schemas/recovery-search-v1.schema.json)
allows either a separate user recovery key or an existing pinned node key, or
both, while keeping private-key material out of the configuration. It is
disabled by default; local-only recovery does not require a remote endpoint.
Remote recovery additionally requires its own explicit network-enabled setting
and a configured peer endpoint. This remains a policy contract, not yet a
peer/chain search implementation.

Use a host terminal for recovery and administration first; the existing
PowerShell/CLI workflow can safely target chosen disks without exposing a guest
shell. A terminal inside the guest would be useful later for local diagnostics,
but requires a bounded command parser, process isolation, and file/socket
permissions that the current OS doesn't provide. A cloud shell is optional and
not required for recovery; if added, it should be a separate, user-controlled
hosted environment with short-lived credentials and explicit remote-data
consent, never a privileged shell inside the guest.

### Cloud networking, audit, and contribution trail

Cloud destinations use a provider-neutral endpoint contract in
[`schemas/cloud-endpoint-v1.schema.json`](schemas/cloud-endpoint-v1.schema.json).
It describes AWS S3, Azure Blob, Google Cloud Storage, S3-compatible services,
generic HTTPS APIs, and self-hosted endpoints without embedding credentials or
creating resources. Every endpoint is disabled by default, requires HTTPS with
peer verification, declares allowed data classes, and sets upload/queue/timeout
and retention bounds. This is a configuration contract, not an uploader or a
provisioned endpoint; provider adapters still need to be implemented and
reviewed before sending data.

The guest now proves a bounded ring-3 DNS lookup through the kernel's network
owner; QEMU also exercises kernel TCP/HTTP and UDP DNS. The guest still lacks
general user-process TCP/UDP sockets, TLS, and an upload client. A cloud endpoint
will not supply those missing guest interfaces. Start cloud connectivity from
the existing host supervisor, which can perform outbound work while the guest
remains isolated. The proposed sequence is:

1. Implement provider adapters behind the endpoint schema, beginning with
   client-encrypted backup upload and checksum-verified restore. Then add
   redacted, schema-versioned event upload and a bounded encrypted retry queue.
   Cloud unavailability must not stop OS boot or local research.
2. For multi-host access, use a private WireGuard tunnel from an explicitly
   enrolled host to a small AWS relay/VPC. Do not expose QEMU, SSH, the local
   node ports, or guest control endpoints publicly. Require peer identity,
   task IDs, idempotency, leases, rate limits, and a revoke path before more
   than one worker can act.
3. Upload only client-encrypted backup archives to S3 using a separate
   short-lived backup role. Verify remote checksums and restore from a clean
   machine before calling disaster recovery ready. Add an external-drive copy
   for a 3-2-1 recovery plan; S3 alone is not the only backup.
4. Keep CloudTrail as the AWS account/control-plane audit, and add narrowly
   scoped S3 data-event logging only if needed after reviewing its additional
   event/storage charges. Separately ship redacted, schema-versioned OS and
   supervisor events with event IDs, timestamps, component/version, status,
   and content digest. Exclude prompts, research payloads, credentials,
   personal data, and raw network contents by default. Buffer locally with a
   strict size/age cap and visible drop/queue alerts.
5. Keep the local signed chain and token ledger as the current source of
   truth. The existing token balances are non-transferable contribution
   scores, not currency and not OS permissions. A future cross-host trail
   should use signed, idempotent contribution attestations with explicit
   verification rules; anchor only a reviewed digest/checkpoint to the
   permissioned project chain. Never put raw logs or research records on-chain.
   Training data is a separate, opt-in, human-reviewed export—not an automatic
   consequence of logging or earning points.

These are implementation boundaries and a rollout plan, not a live cloud
connection. AWS setup, cloud networking, event upload, and chain anchoring
remain disabled until the exact account/region, resource names, retention,
costs, data fields, and network exposure are presented and explicitly
approved. An offline queue must replay events idempotently after reconnect;
cloud/chain failures must be visible and must not create duplicate token
credits or block local operation.

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
