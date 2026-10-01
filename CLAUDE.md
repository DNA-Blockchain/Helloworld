# RabbitSoftware: guide for Claude Code

RabbitSoftware is a research OS, an AI model and a blockchain in one repository
(`DNA-Blockchain/Helloworld`, UPL-1.0, authorship in `NOTICE.md`, privacy in `PRIVACY.md`).

## Map

| Area | Where | Notes |
|---|---|---|
| Nodes and chains | `node_supervisor.py` (persistent worker), `work_sharing.py`, `research_provenance.py` (every chain event kind and its validator), `maxwell_chain_agent.py` | 3 local nodes, each with its own chain plus a replicated research ledger |
| Research pipeline | `research_catalog.py` (SQLite catalog) → `corpus_vector_store.py` (nomic-embed-text / TF-IDF) → `rabbitsoft/assistant.py` (answers) → chain events via `autonomous/research-outbox/` | `rabbitsoft/pipeline_report.py` measures every stage |
| Assistant | `rabbitsoft/` (`assistant.py` Session, `words.py` deterministic routing, `tools.py` read-only status, `web.py` + `page.html`, `sync.py`, `integrity.py`, `contracts.py`), CLI `rabbit.py` | name: RabbitSoftware.inc |
| Model | `hosted_ai.py` (OpenAI-compatible client), `local_ai_tuning.py`, `ollama/`, `deploy/hf_publish.py`, cards in `deploy/huggingface/` | HF endpoint `rabbitsoftware-model` (llama.cpp, T4, scale to zero) |
| Cloud | `deploy/cloudflare/` (model gateway Worker), `deploy/cloudflare-sync/` (accounts and sync, R2) | private until launch |
| APIs | `schemas/rabbitsoftware-*-v1.schema.json`, `docs/api/` | contract-tested; v1 only grows, breaking changes need `-v2` |
| OS | `os/` (no_std Rust kernel, QEMU only), `linux/` (Alpine image), `os/tasks/` (generated bundles) | never write images to physical disks |
| Neural → visual prototype | `neurovisual/` (core: `signals.py`, `model.py`, `system.py`, `provenance.py`; open slots: `interfaces.py`, `sensors.py`, `generators.py`, `conditioning.py`, `stream.py`, `datasets.py`, `profiles.py`); `python -m neurovisual run/sessions/export/train`; docs in `docs/neurovisual/` | sensors via BrainFlow/LSL or simulated; session datasets AES-GCM-encrypted under `autonomous/neurovisual/`; remote generators need https and a yes; the ledger holds keyed digests only |
| UI kit | `ui/` (tokens.css, Web Components, no build step) | |
| Releases | `VERSION`, `CHANGELOG.md`, `RELEASING.md`, `.github/workflows/release.yml`, `scripts/code_fingerprint.py` | tag `vX.Y.Z` must match `VERSION` |

Runtime state is gitignored and must stay that way: `autonomous/`, `dna_shell_data/`, `research_store.json`, `system_audit.jsonl`.

## Commands

```powershell
python -m pytest tests/ -q                 # full suite (~4 min); CI runs the same (verify.yml)
python -m pytest tests/test_rabbitsoft.py -q
python node_supervisor.py                  # start/keep the 3 nodes running; --status to check
python rabbit.py chat | web | ask "..."    # the assistant
python rabbit.py pipeline-report --hours 24 [--json]
python -m rabbitsoft.integrity --no-tests  # integrity report into autonomous/integrity/
python build_task_bundles.py               # regenerate os/tasks/* after changing files they embed
cd deploy/cloudflare-sync; npm test        # Worker tests (node --test); deploy with wrangler only when asked
```

The Rust kernel in `os/` uses the pinned nightly from `os/rust-toolchain.toml`. Run `cargo fmt --all -- --check`, `cargo check --locked` and `cargo run --locked -- check`, and run the result in QEMU only.

## Rules

- **Ask first:** installs, anything that costs money, deploys, and anything that sends data off the PC. In the app, every hosted-model question, public search, publish and share waits for a yes and is written to the activity log.
- **Secrets:** never put tokens or keys in chat, code, logs or examples. The owner types them into a terminal prompt or web form. On Windows, set Worker secrets with bash `printf '%s'`, not a PowerShell pipe (which adds CRLF).
- **The chain is public and permanent:** it holds only public data and fingerprints. Personal data (emails, phones, IDs, birth dates, addresses, long DNA sequences) goes to the encrypted vault (`dna_shell.py data-vault-store`), never to the chain. Nodes enforce this in `research_provenance.personal_information`.
- **Private until launch:** keep the HF model and dataset private and the gateway unadvertised. Installers don't set a default model server.
- **No per-file license headers:** authorship lives in `NOTICE.md` and the release code manifest. `tests/test_authorship.py` fails if headers come back. Never publish the owner's phone number or town.
- **Positioning:** describe the project as advanced research, OS and blockchain software. Spelling correction, numbered choices and the display settings are standard features, not a target audience.
- **Writing style:** answers, reports and PR descriptions are detailed and technical: figures, methods, sources and limits.

## Git and PRs

- Branch from `master`; stack dependent PRs and retarget them as each one below merges. Never use `--delete-branch` on a stacked base.
- **Commit messages** end with `Co-Authored-By: Claude <model> <noreply@anthropic.com>`.
- **PR bodies** end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. They use `Closes #N` where an issue exists, a milestone (Phase 0–5 or "Owner to-dos") and labels (`claude`, `owner`, `frameworks`, `ui`, `ai-model`, `os-image`, `integrity`, `launch`, `security`).
- **Merging:** merge only when the owner says "merge N". After merging changes to chain event kinds or validation, restart the nodes (`python node_supervisor.py`).
- **Before calling work done:**
  - run the full suite;
  - for answer or prompt changes, also try the real local model;
  - review the diff with the installed review agents (`pr-review-toolkit`: code-reviewer, silent-failure-hunter, pr-test-analyzer).

## Gotchas

- **Python on Windows:** PowerShell 5.1's `Set-Content -Encoding utf8` writes a BOM. Write files from Python, or with `[IO.File]::WriteAllText`.
- **Code manifest:** `scripts/code_fingerprint.py` hashes git objects, not the working tree, so it's identical on Windows and WSL whatever the line-ending settings.
- **Retrieval cutoffs:** `corpus_vector_store.MIN_SIMILARITY` is tuned per method (TF-IDF 0.12, neural 0.62). Unrelated questions scored up to 0.55 with nomic-embed-text.
- **Model limits:** the gateway caps answers at 400 tokens (`MAX_TOKENS`). On CPU, the local 3B model takes about 4 minutes for a full answer; the T4 endpoint about 5 s once warm, 30–60 s cold.
- **Menu tests:** `tests/test_rabbitsoft.py` counts the menu entries; update the count when adding an intent to `words.LABELS`.
