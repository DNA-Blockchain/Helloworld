# RabbitSoftware

**Advanced research, operating-system and blockchain software in one codebase.**

RabbitSoftware runs research nodes on your own machine. They gather public biomedical literature, record what they
found on a replicated, signed chain, and answer technical questions from those records with citations. A research
OS kernel, a Linux image and a fine-tuned language model are developed in the same repository.

| | |
|---|---|
| Main repository | [**Helloworld**](https://github.com/DNA-Blockchain/Helloworld) |
| Version | 0.11.0 ([changelog](https://github.com/DNA-Blockchain/Helloworld/blob/master/CHANGELOG.md)) |
| License | [UPL-1.0](https://github.com/DNA-Blockchain/Helloworld/blob/master/LICENSE) |
| Author | Chase Allen Ringquist ([NOTICE.md](https://github.com/DNA-Blockchain/Helloworld/blob/master/NOTICE.md)) |
| Privacy | [PRIVACY.md](https://github.com/DNA-Blockchain/Helloworld/blob/master/PRIVACY.md) |

## What it is

| Component | What it does |
|---|---|
| **Research nodes and chain** | Three local nodes run under a supervisor. Each keeps its own signed chain, and they share a research ledger. Every kind of chain event has a validator, and nodes reject events that contain personal data. |
| **Research pipeline** | Live queries to PubMed, Europe PMC, ClinicalTrials.gov, ClinVar, HGNC, NIH RePORTER and arXiv. Results go into a SQLite catalog, a semantic vector index (nomic-embed-text, or TF-IDF as a fallback) and cited answers. A pipeline report measures each stage. |
| **RabbitSoftware.inc assistant** | A terminal and local web assistant that answers questions about the system and its research with `[1]`- and `[K1]`-style citations. It routes questions deterministically, uses read-only status tools and runs a local model by default. |
| **Project knowledge base** | Source-linked research reports in `docs/research/`, split into sections, indexed by meaning and used to answer questions. Each version is identified by a SHA-256 fingerprint. |
| **Model** | A fine-tuned Llama 3.2 served through an OpenAI-compatible client. It runs locally on Ollama, or on a hosted endpoint when you opt in. |
| **Research OS** | A `no_std` Rust x86_64 kernel tested in QEMU (E1000 networking, cooperative scheduling, a ring-3 ELF64 loader, block storage), plus an Alpine-based Linux image. |
| **Neural → visual prototype** | `neurovisual/` is an SDK for EEG signal capture (BrainFlow/LSL, or simulated sensors), encrypted session datasets and image-generation research, based on a published survey of the field. It is a simulation: EEG band power is a signal measurement, not a thought or an image. |
| **Agent network (TwinOS)** | A digital twin works as one agent among coding, terminal, MicroPython and GPU agents, over Ed25519-signed U-A2A messages. Only peers whose keys the owner pins can send tasks, and consequential work always waits for the owner's approval. |
| **Cancer genomics tooling** | Public cancer-genomics datasets with their licence and access tier, before/after variant comparison, and candidate Cas9 guides. Research tooling that computes candidates for a laboratory, never a treatment, and not medical advice. |
| **Model versions** | Every version of the model is recorded with its SHA-256, the commit it was built from, its training and its scores. One command installs a released version into Ollama. |
| **Integrity** | Tamper-evident audit logs and an integrity report. Every release ships a code manifest (SHA-256 of every file under one fingerprint) that can be recorded on the chain. |

## Design principles

- **Local-first.** Everything runs on your machine with plain Python 3.11+. No account, subscription or cloud
  service is required.
- **Consent before data leaves.** Hosted-model questions, public searches, publishes and shares each wait for a
  yes and are written to an activity log.
- **The chain holds only public data and fingerprints.** Personal data goes to an encrypted local vault and is
  never written to the chain.
- **Stable, versioned APIs.** JSON Schemas for the node, app, shell, model, sync, integrity and pipeline-report
  APIs are contract-tested. v1 only grows; breaking changes get a new version.
- **Honest limits.** [KNOWN_GAPS.md](https://github.com/DNA-Blockchain/Helloworld/blob/master/KNOWN_GAPS.md)
  lists what the system does not do. For example, the ledger's balances are a local score, not a currency; the
  CRISPR guide tooling computes candidates for a laboratory, not treatments; and no part of the project
  diagnoses or treats disease.

## Quality

- 99 test modules with 880+ test functions run on every pull request (`python -m pytest tests/ -q`).
- The kernel is checked with `cargo fmt`, `cargo check --locked` and its own check runner, and runs only in QEMU.
- The tag of every release matches `VERSION`, and the release carries its code manifest.

## Get started

Windows (PowerShell, no admin rights):

```powershell
irm https://raw.githubusercontent.com/DNA-Blockchain/Helloworld/master/install.ps1 | iex
```

Linux or WSL (no sudo):

```bash
curl -fsSL https://raw.githubusercontent.com/DNA-Blockchain/Helloworld/master/install.sh | bash
```

Then run `rabbit chat`, `rabbit web` or `rabbit ask "..."`. The installer installs nothing else by itself. If
Python or Ollama is missing, it tells you the command to run.

## Status

RabbitSoftware is active research software. The hosted model, its datasets and the cloud sync service are private
until launch. Issues and discussion are welcome in
[Helloworld](https://github.com/DNA-Blockchain/Helloworld/issues).
