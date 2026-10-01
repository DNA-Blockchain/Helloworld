# Changelog

Each release lists what changed. The newest release comes first, and work merged since the last
release goes under **Unreleased**. Versions follow [semantic versioning](https://semver.org): MAJOR for
changes that break an API in `schemas/`, MINOR for new features, and PATCH for fixes. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). `RELEASING.md` explains how a release is made.

## [Unreleased]

### Added
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

### Changed
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
