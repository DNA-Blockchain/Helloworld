# Changelog

Each release lists what changed. The newest release comes first, and work merged since the last
release goes under **Unreleased**. Versions follow [semantic versioning](https://semver.org): MAJOR for
changes that break an API in `schemas/`, MINOR for new features, and PATCH for fixes. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). `RELEASING.md` explains how a release is made.

## [Unreleased]

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
