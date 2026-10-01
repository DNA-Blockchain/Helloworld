# RabbitSoftware roadmap to release

The to-do list for getting RabbitSoftware (the OS, its nodes and chain, and RabbitSoftware.inc with its
model) to a public 1.0. The steps are in the order they depend on each other. Each one ends in a PR, and a
step is checked off when that PR is merged.

**Decisions so far**
- **User interfaces:** JavaScript Web Components with no build step. They work offline and inside the OS image, with no npm packages to keep patched.
- **Frameworks:** stable, documented APIs between the parts, plus a real release structure.
- **The model:** private until launch.

Legend: **[me]** is work Claude does in this repo; **[you]** needs the owner's sign-in, card or decision.

## Done

- [x] RabbitSoftware.inc assistant: chat, research answers with sources, chain reading and notes, integrity checks.
- [x] Integrity team: chains, records, data, code fingerprints, tool checks, daily integrity runs, fingerprints on the chain by choice.
- [x] Search by meaning (local `nomic-embed-text`), with research abstracts.
- [x] One-line installers for PowerShell and Linux/WSL.
- [x] Hosted model on a private Hugging Face endpoint, plus the Cloudflare gateway.
- [x] Accounts across devices: pairing, encrypted history, a shared corpus, answers shared for training.

## Phase 0: frameworks, before any new screens

### 0.1 Release structure [me]
- [ ] `VERSION` file (semantic versioning, starting at `0.9.0`), and `rabbit --version`.
- [ ] `CHANGELOG.md`, with each merged PR listed under the next version.
- [ ] `RELEASING.md`, the release checklist: tests green, schemas checked, changelog, tag, GitHub release with notes.
- [ ] Installers download a **tagged release**, not master, so day-to-day work never reaches users until it's released. `RABBIT_CHANNEL=dev` keeps master for testing.
- [ ] `rabbit update`: compares the version with the latest release and re-runs the installer after a yes.

### 0.2 Stable APIs between the parts [me]
Each API gets a versioned JSON Schema in `schemas/` and a page in `docs/api/`. Contract tests check real messages against the schemas, so a change that breaks a part fails the tests.
- [ ] **Local app API** (UI ↔ RabbitSoftware.inc): `/api/v1/message`, `/api/v1/poll`, `/api/v1/status`. The current routes stay as aliases.
- [ ] **Node API:** `status.json`, chain entries and research events (already validated in `research_provenance.py`; to be written down as schemas).
- [ ] **Model API:** the OpenAI-compatible subset the gateway accepts, its limits and its errors.
- [ ] **Sync API v1:** every route of `deploy/cloudflare-sync`, with its request signing.
- [ ] **Integrity report v1** (exists in code; schema to add) and **tool survey**.
- [ ] **OS shell API:** what the desktop shell reads (nodes, jobs, AI, files), as a read-only JSON API.

### 0.3 UI kit: Web Components, no build [me]
- [ ] `ui/` folder: design tokens (colors, type sizes, spacing) with **big-text** and **high-contrast** modes, and light/dark.
- [ ] Base components: `<rabbit-button>`, `<rabbit-card>`, `<rabbit-choices>`, `<rabbit-chat>`, `<rabbit-status>`, `<rabbit-dialog>` (the yes/no questions).
- [ ] Accessibility rules every component follows: keyboard use, screen-reader labels, no colour-only meaning, and text that never depends on the AI to be readable.
- [ ] A component gallery page, used for checking and for screenshots.

## Phase 1: RabbitSoftware.inc app (replaces `rabbitsoft/page.html`) [me]
- [ ] App shell with sections: **Chat**, **Research**, **Chain** (browse entries and notes), **Account & devices**, **Settings** (model server, notes, integrity publishing, bigger text).
- [ ] A cookie session (HttpOnly, SameSite=Strict, local only) so a reload keeps the conversation. No tracking cookies.
- [ ] Thumbs up/down on answers, feeding the `rating` of shared training answers.
- [ ] It runs the same in the browser on Windows and inside the OS image.

## Phase 2: AI model dashboard (owner only) [me]
- [ ] **Part C of syncing:** daily export of shared answers to the private HF dataset `rabbitsoftware-training`. **[you]** first create your account so `ADMIN_ACCOUNT` can be set.
- [ ] Endpoint panel: awake or asleep, recent cost estimate, wake it, gateway limits.
- [ ] Training review: read shared answers with their sources, approve or reject, with only approved answers going into the next training set.
- [ ] Test bench: a fixed set of questions with known right answers, run against a candidate model on a temporary endpoint and compared with the current one. The model is swapped only if it's at least as good. This guards against slips like the reversed sickle-cell mutation.
- [ ] LoRA round 3 from approved answers plus research abstracts.

## Phase 3: RabbitSoftware OS (bootable, with the AI built in)
- [ ] **[me]** OS image profile: the Alpine image (`linux/`) with the full project, its Python packages, nodes and RabbitSoftware.inc starting at boot.
- [ ] **[me]** Desktop shell (Web Components): nodes, AI app, files, status and integrity, settings. Shown full-screen by a small kiosk browser at boot.
- [ ] **[me]** AI inside the OS: the hosted model, asked each time, by default; optionally Ollama in the image when there's enough memory.
- [ ] **[me]** Tests: the image boots in QEMU and the shell answers; this joins the integrity checks.
- [ ] **[me]** USB/ISO image for real PCs, with a written install and recovery guide.
- [ ] **[you]** Test boot on a spare PC or USB stick.
- [ ] Later: graphics in the from-scratch Rust kernel (`os/`), which is needed before any UI can run there.

## Phase 4: integrity engineer role [me]
- [ ] When a check or test fails, the AI explains it in plain words, and a proposed fix goes on a separate review branch with its test results. It's never merged without the owner.

## Phase 5: launch
- [ ] **[me]** Launch website (static, Cloudflare Pages): what it is, the install lines, model card, privacy policy, terms.
- [ ] **[you]** Approve the privacy policy and terms; they're legal text you're responsible for.
- [ ] **[me]** Open sign-up (`OPEN_SIGNUP=true`), make the gateway the installers' default model server, and review the abuse limits.
- [ ] **[me]** Tag `v1.0.0` by following `RELEASING.md`.

## Owner's to-dos [you], any time before launch
- [ ] Two-factor sign-in on GitHub, Hugging Face and Cloudflare.
- [ ] Hugging Face spending limit (Settings → Billing), and a Cloudflare usage alert (Notifications).
- [ ] Rename the Cloudflare workers.dev subdomain to `rabbitsoftware` (then [me] update the addresses in code).
- [ ] Create your RabbitSoftware account: `python rabbit.py account create`, and keep the recovery phrase safe.
- [ ] Decide about the public HF repo `rabbit-2.2.8-…`: it holds `.exe` installers and a Bitcoin node log, so make it private or remove them.
- [ ] Restart the nodes after the integrity merge (`python node_supervisor.py --stop`, then start), so they accept integrity fingerprints.
