# Changelog

Each release lists what changed. The newest release comes first, and work merged since the last
release goes under **Unreleased**. Versions follow [semantic versioning](https://semver.org): MAJOR for
changes that break an API in `schemas/`, MINOR for new features, and PATCH for fixes. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). `RELEASING.md` explains how a release is made.

## [Unreleased]

### Added
- **Model versions across GitHub, Hugging Face and your PC** (`model_versions.py`, `docs/model/README.md`):
  - **Record:** `deploy/huggingface/model-versions.json` lists every version of the model: its GGUF SHA-256 and size, the Hugging Face commit, the GitHub commit it was built from, the base model, training and scores. Entries are only added. Version 1.0.0 (the current model, `8aa05e28…`) is recorded with notes on what was reconstructed.
  - **Candidates:** the Colab notebook's step 11 runs `python deploy/hf_publish.py candidate --version X --release vY`, which uploads to a `candidates` branch of the private repo with the version's entry. `hf_publish.py record X` adds that entry to the manifest on a PC, for a PR.
  - **Release:** a GitHub release promotes the versions it ships (`hf_publish.py promote`). The file is copied to `main` on Hugging Face's servers (no re-upload), tagged `model-v<version>`, its SHA-256 checked, and listed in the release notes. It needs an `HF_TOKEN` repository secret only when a model ships.
  - **Install:** `python rabbit.py model versions | install [--version X] [--candidate]` downloads with your Hugging Face login (no SSH key), uses a matching local copy when there is one, refuses a file whose SHA-256 doesn't match, and creates `rabbitsoftware:<version>` and `rabbitsoftware:latest` in Ollama with Llama 3.2's chat format.
- **TwinOS universal agent network, part 1** (`twinos/`, `python -m twinos`): a digital twin as one agent among coding, development, terminal, MicroPython, GPU and other agents, all speaking **U-A2A 1.0**:
  - **Identity:** a persistent Ed25519 key per agent. The agent id is derived from the key, so an id can't be claimed without the key.
  - **Messages:** each one is signed, and checked against `schemas/rabbitsoftware-agent-message-v1` (contract-tested, documented in `docs/api/agent-message.md`), a ±120 s clock window and a nonce against replays. Frames are length-prefixed, up to 1 MiB.
  - **Trust:** anyone can discover an agent, but only peers whose keys the owner has pinned (`twinos trust`) can ask for anything else. Nothing is pinned automatically.
  - **Policy and approvals:** the receiver builds each task from its type, description and parameters only, so a sender can't approve its own task. Capabilities outside `policy.json` wait for `twinos approve|deny`, which is written to the activity log. Code, terminal, file writes, network, MicroPython and GPU always wait. A node offers only task types it has a handler for (here, `status`), rather than reporting work it didn't do.
  - **Network:** listens on `127.0.0.1:8790` by default. Other machines need `--allow-remote` to listen or send, which is logged. At most 32 connections at a time and 100 waiting tasks per peer.
  - **Ledger:** keyed digests of messages from pinned peers and of every task decision and result, in `autonomous/twinos/ledger.jsonl` (the `neurovisual` provenance ledger, which can now name its genesis block). Nothing is published.
- **Research report: EEG to image reconstruction (2026)** in `docs/research/`, with its source notes (methods and models, datasets and benchmarks, imagery/memory/real-time, law and ethics). It gives the evidence base and design guidance for `neurovisual/` and is linked from the SDK guide. Deep-research working folders (`/research_notes/`, `/reports/`) are gitignored.
- **The AI everywhere in RabbitSoftware.inc** (opt-in with `python rabbit.py model-server --always on`):
  - **No yes/no each time:** AI steps go straight to the configured model server. If it doesn't answer, this PC's model does, and the reply says so. `--always off` restores asking; `model-server` shows the mode.
  - **AI summaries on status answers:** nodes, chain, ledger, agents, swarm, activity, reports, the pipeline report, the corpus, tools, jobs and the integrity report each get a 3–6 sentence technical summary from the model, labeled "AI summary". The exact figures computed on this PC stay below it as the reference. Before sending, the text is screened for personal information and your user folder is replaced with `~`. Summaries use only the model server, never the slow local model; with "always" off, status answers are unchanged and instant.
  - **The AI answers anything else:** questions that aren't research or a command go to the model with a short description of the project, instead of the menu. Research terms still go research-first.
- **SQL in the cloud: Cloudflare D1** for the sync service (`deploy/cloudflare-sync/migrations/0001_init.sql`), alongside R2:
  - **Shared answers:** stored in `training_answers` (no account or device) with a review status, instead of R2 files.
  - **Corpus:** every public record indexed once in `corpus_records`, searchable by anyone (`GET /v1/corpus/search`, `/v1/corpus/stats`).
  - **Exports:** each export to Hugging Face recorded in `exports`, together with marking its answers, in one transaction, so nothing is exported twice.
  - **Owner routes:** `/v1/admin/training` (by status), `/review`, `/export`, `/exported` and `/v1/admin/stats`, all in the sync API v1 schema and contract-tested on the wire.
  - **Writes:** bulk writes are single set-based statements.
- **Shared answers to the private HF dataset as Parquet** (#40): `python rabbit.py training stats | pending | approve | reject | export`:
  - an export re-screens every answer for personal information (failures are rejected), refuses a public repo, asks first, uploads `data/<date>.parquet` (zstd) with this PC's HF login, then records the file's SHA-256 and HF commit;
  - `training export --daily on` lets the supervisor export once a day (a failure marks the day "needs attention");
  - `pyarrow` added to the requirements.
- **Stable APIs between the parts:**
  - versioned JSON Schemas in `schemas/rabbitsoftware-*-v1.schema.json` for the local app API, the OS shell API, the node API, the model API, the sync API, and the integrity report and tool survey;
  - a page for each in `docs/api/`, with the rules for how an API may change;
  - contract tests that check real messages from each part against them (`tests/test_api_contracts.py`).
- **Versioned routes:** `/api/v1/message`, `/api/v1/poll` and `/api/v1/status`, with the old `/api/...` routes kept as aliases. The web page uses v1.
- **`GET /api/v1/shell`:** a read-only snapshot of nodes, jobs, AI, account and the latest integrity report, for the desktop shell.
- **`jsonschema`** added to `requirements.txt`, for the contract tests.
- **Authorship recorded at the repository level:**
  - `NOTICE.md` now covers every file;
  - `PRIVACY.md` is the privacy policy;
  - each release attaches a **code manifest** (`scripts/code_fingerprint.py`): the author, the license, the commit and the SHA-256 of every file, as stored in git, so it's reproducible on any OS;
  - `rabbit publish-code-fingerprint vX.Y.Z` records a release's fingerprint on the chain as the new `code_release` kind.

- **Research data pipeline report** (`rabbitsoft/pipeline_report.py`) follows mined research through every stage, with the figures for each:
  - **ingestion:** catalog records, abstracts, publication years and new records per source; the research agent's topics and per-source status; public searches and abstract fetches;
  - **corpus:** documents, current vectors per embedding model, search method, unindexed records, cutoffs;
  - **model:** training items kept and rejected per task, the latest evaluation, the model file, summaries, hosted questions, fallbacks and shared answers;
  - **chain:** entries per kind, each node's copy, published records per source, corrections, notes, datasets, Bitcoin timestamp proof state, outbox;
  - **nodes** and **integrity**.

  It's available as `rabbit pipeline-report [--hours N] [--json]`, in chat ("pipeline report", "data mining report") and as a section of the supervisor's daily report. It's read-only, and its JSON follows the new `rabbitsoftware-pipeline-report-v1` schema (`docs/api/pipeline-report.md`).

- **Neural → visual memory/imagination prototype** (`neurovisual/`, #70), simulated sensors only:
  - **Signals:** EEG band power per window (delta to gamma, Hann-windowed FFT), a per-person running baseline (Welford z-scores), and signal quality from dead or non-finite channels.
  - **Prediction:** a temporal predictor over an exponentially weighted sequence. Memory and imagination modes with explicit evidence, inference and generative weights; evidence is claimed only when a stored anchor exists, and confidence is computed from the mix, signal quality and baseline readiness.
  - **Learning:** reward-weighted learning from ratings, run in a background thread on a copy of the model and swapped in atomically, so real time never blocks.
  - **Provenance:** a local hash-chained ledger holding model fingerprints, config hashes, metrics and keyed (HMAC) data digests. No raw signals, notes or memories reach disk or the shared chain.
  - `python -m neurovisual` runs a simulated session.
- **Neurovisual SDK** (`docs/neurovisual/SDK.md`): every slot open, for research, gaming and AI development:
  - **Live EEG:** through BrainFlow (OpenBCI, Muse, Neurosity and others; synthetic board -1 needs no hardware) and Lab Streaming Layer.
  - **Any model:** loaded as `package.module:Class` and given the same evidence accounting through `model.compose()`; trainable if it has `trained()`. A PyTorch GRU example is included.
  - **Generators:** latent states conditioned into prompt, seed, guidance and strength requests for existing image and video generators: ComfyUI workflows (SDXL, Flux, AnimateDiff, SVD), AUTOMATIC1111, diffusers and any HTTP service. Remote destinations need https and a yes; `AsyncRenderer` keeps generation off the real-time path (newest request wins, errors counted).
  - **Game engines:** a UDP latent stream on localhost for Unity, Unreal, Godot and TouchDesigner.
  - **Session datasets:** every step, rating, memory and generation, encrypted with AES-256-GCM in authenticated frames (`docs/neurovisual/DATASET.md`); `sessions`, `export` (npz, jsonl) and `train` commands; datasets recorded in the provenance ledger.
  - **Profiles:** `research`, `gaming`, `development`.
- **Neurovisual training lineage:** `python -m neurovisual train` writes a linked chain of blocks to the provenance ledger:
  - a versioned **dataset**, then a **training-set hash** per mode;
  - memory- and imagination-model **training runs**, recording the device (GPU name and memory, or CPU), seconds, samples/s and the objective;
  - a **model version** with its fingerprint and checkpoint SHA-256.

  Each release continues from the verified previous checkpoint (v1.1 → v1.2 → v1.3). `chain` shows the blocks and `lineage` traces any version back to its data; `run --model latest` serves the newest verified release. PyTorch models train on CUDA when available.

### Fixed
- **Neurovisual:** training a model on sessions recorded by a different model now rebuilds that model's own input from the recorded features (the PyTorch model had been given the recording model's 7-value context instead of its 32-step window), and ratings are matched to steps within their own session.

### Changed
- **Sync service:** `ADMIN_ACCOUNT` is now a Wrangler secret instead of a var, so the owner's account ID isn't published in the repository. The dataset card describes the Parquet export and review.
- **Research answers are technical reports:**
  - three sections (Findings, with the reported figures; Methods and evidence, with each record's study type; Limitations), every claim cited;
  - a retrieval line on each answer: keyword and meaning matches with their scores and cutoff, the sources, publication years and abstract coverage;
  - answers up to 400 tokens, up from 220 (the gateway's cap);
  - records reach the model with their source and year;
  - "Explain that more simply" is replaced by "Summarize in brief", a 2–3 sentence summary that keeps every figure and citation.
- **Positioning:** RabbitSoftware.inc, the model card and the docs describe the project as advanced research, OS and blockchain software. Spelling correction, numbered choices and the display settings (text size, themes, keyboard and screen-reader support) stay as standard features.
- **Model cards in the repository:** the Hugging Face model and dataset cards now live in `deploy/huggingface/`, and `deploy/hf_publish.py model` uploads them.
- **Per-file headers removed:** the 53-line license and contact header is gone from all 190 source files (about 10,300 lines). The author's phone number and town are no longer published in the repository.
- **README license statement corrected:** it said CC0 1.0, but the license is UPL-1.0.

### Upgrade note
- Restart the nodes after updating, so they accept `code_release` entries.

## [0.9.0] - 2026-10-01

The first versioned release. It covers RabbitSoftware.inc, the integrity team, the hosted model and sync
across devices; everything earlier is in the git history.

### Added
- **RabbitSoftware.inc**, the operator assistant, in the terminal and on a local web page:
  - deterministic request routing with spelling correction, numbered choices, and a yes/no question before anything changes or leaves the PC (#20);
  - research answers with sources, using a local LoRA model where one is installed (#19);
  - reading everything on the shared research chain (#21), and challenging or improving entries with notes, with personal data refused (#22).
- **Integrity team:**
  - one check of chains, records, data and code fingerprints (#23), which now reads the Maxwell chain export too;
  - a tool check for Windows and WSL that asks before installing anything (#30);
  - a daily integrity run in the supervisor's report, with report fingerprints published to the chain only by choice (#31).
- **Research corpus:** search by meaning with a local embedding model, and research abstracts fetched only after a yes (#24).
- **One-line installers** for PowerShell and Linux/WSL, and answers from the hosted model, asked before each question (#26).
- **Model hosting:**
  - a private Hugging Face endpoint, used with the PC's own Hugging Face login (#27);
  - a public gateway on Cloudflare Workers with per-person and daily limits (#28).
- **Accounts across devices:**
  - a sync service on Cloudflare Workers + R2 (#32);
  - device pairing, chat history encrypted on the device, a shared research corpus, and answers shared for training, all asked first (#33).
- **Docs:** `ROADMAP.md`, plus READMEs for the Cloudflare services (#34).

### Fixed
- Answers by meaning no longer match unrelated questions: the cutoff was tuned, and everyday words in keyword matches are ignored (#25).
- The hosted-model test no longer needs `huggingface_hub` on GitHub's test machine (#29).
