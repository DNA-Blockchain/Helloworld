# Research reports

Source-linked research reports that inform RabbitSoftware's design. Each report sits beside a folder of the
notes it was written from, so every figure can be traced to its source.

| Report | Date | Notes | Informs |
|---|---|---|---|
| [EEG to image reconstruction](eeg-to-image-reconstruction.md) | October 2026 | [notes/](eeg-to-image-reconstruction/notes/): methods and models, datasets and benchmarks, imagery/memory/real-time, law and ethics | `neurovisual/` ([SDK](../neurovisual/SDK.md)) |

## Where the knowledge goes

- **RabbitSoftware.inc:** every report and note here is split into sections and indexed by meaning (`rabbitsoft/knowledge.py`). Questions the reports cover are answered from the matching sections, with `[K1]`-style citations. Use `python rabbit.py knowledge status | search "..." | sync`, or ask "knowledge base" in chat.
- **Your model on Hugging Face:** the matching sections go to the model with each question, under the usual consent and privacy rules.
- **Hugging Face, for retention and training:** `python rabbit.py knowledge publish` asks first, then uploads the sections as Parquet, plus a SHA-256 manifest and a card, to the private dataset `rabbitsoftware-knowledge`. It uploads only when something changed.
- **Building agents:** `CLAUDE.md` and `.claude/agents/` tell the agents to read the matching report before changing what it covers.

To add a report: put it at `docs/research/<topic>.md`, its notes in `docs/research/<topic>/notes/`, add a row above, then run `knowledge sync` (and `knowledge publish`).

These reports are research summaries, not legal advice. Preprint results are marked as unreplicated where
that applies. Working copies are produced in the gitignored `/research_notes/` and `/reports/` folders and
copied here once final.
