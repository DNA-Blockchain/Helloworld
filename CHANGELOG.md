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
- **UI kit (`ui/`), Web Components with no build step:**
  - **Design tokens:** big-text, high-contrast, dark and reduced-motion modes.
  - **Components:** `<rabbit-button>`, `<rabbit-card>`, `<rabbit-status>`, `<rabbit-choices>` (number keys pick), `<rabbit-dialog>` (yes/no, with "No" focused first) and `<rabbit-chat>` (read out by screen readers).
  - **Gallery:** a page at `/ui/gallery.html`.
  - **Safety:** text is always inserted as text, never as HTML.
  - **Serving:** the local app serves the kit's files by name only.

## [0.9.0] - 2026-10-01

The first versioned release. It covers RabbitSoftware.inc, the integrity team, the hosted model and sync
across devices; everything earlier is in the git history.

### Added
- **RabbitSoftware.inc**, an assistant in the terminal and on a local web page, built for people with grammar or word-finding difficulties:
  - spelling fixes, numbered choices, and a yes/no question before anything changes or leaves the PC (#20);
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
