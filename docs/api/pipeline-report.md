# Pipeline report v1

The research data pipeline report follows public research from its source to the chain, with the
figures for every stage. Schema:
[`rabbitsoftware-pipeline-report-v1`](../../schemas/rabbitsoftware-pipeline-report-v1.schema.json),
definition `report`.

- **Code:** `rabbitsoft/pipeline_report.py`, where `build()` returns the data and `render()` the text.
- **Where it appears:**
  - `python rabbit.py pipeline-report [--hours N] [--json]`;
  - in chat ("pipeline report", "data mining report");
  - as the "Research data pipeline" section of the supervisor's daily report.

It only reads: it opens the stores read-only, and nothing is changed, created or sent.

## Period

Figures named `new_in_period`, and the activity counts (searches, abstracts, hosted questions, shared
answers), cover `period`. The default period is the last 24 hours; in the daily report it's the report's
own period. Everything else is a running total.

## Stages

| Key | Source of the figures | What it reports |
|---|---|---|
| `ingestion.catalog` | `dna_shell_data/research_catalog.sqlite3` | records, abstracts and new records per source; publication year range; classifications |
| `ingestion.agent` | `research_store.json` | topics, queue, IDs found per source, per-source status per topic |
| `ingestion.*` counts | activity log (`system_audit.jsonl`) | public searches and records returned; abstracts requested and filled |
| `corpus` | `dna_shell_data/corpus_vectors.json` | documents; current vectors per embedding model; search method; catalog records not yet indexed; similarity cutoffs |
| `model` | `ollama/nos-lora/`, `autonomous/ai-tuning/`, `autonomous/summaries/`, activity log | training items kept and rejected per task; latest evaluation; model file; summaries; hosted questions, fallbacks and shared answers |
| `chain` | node research ledgers (`research_viewer.collect`) | entries per kind; each node's copy; published records per source; queries; corrections; notes; datasets and bases; Bitcoin timestamp proof state; outbox |
| `nodes` | `autonomous/node-*/status.json`, `autonomous/period_totals.json` | blocks, own-chain check, peers, research ledger, audits, blocks mined and verified in the supervisor's period |
| `integrity` | `autonomous/integrity/integrity-*.json` | latest report: checks per status, problems, SHA-256 fingerprint |

A stage is `null` until its store exists, for example `corpus` before the first research question.
