# Integrating with RabbitSoftware

What this project offers other research tools, what versions it has been tested against, and how to
raise something before either side builds against the other.

## Three things you can use without adopting any of the rest

| | What it is | Where |
|---|---|---|
| **Portable exports** | Research records as BibTeX, RIS, CSV or JSONL, each carrying the source's own identifier, URL and terms | [`research_export.py`](../research_export.py) |
| **A provenance format** | Plain JSON for "where did this record come from, when, under what terms, and which code exported it". No blockchain required. | [docs/api/provenance.md](api/provenance.md), [schema](../schemas/rabbitsoftware-provenance-v1.schema.json) |
| **Documented source adapters** | A worked request and real response for PubMed, Europe PMC, ClinicalTrials.gov, ClinVar and NIH RePORTER, with the failure behaviour and the traps | [docs/sources/](sources/README.md) |

A worked end-to-end example joining this project with a reference manager and a notebook is in
[docs/tutorials/literature-to-reference-manager.md](tutorials/literature-to-reference-manager.md), with a
committed [example dataset](../examples/research/README.md) so nothing has to be fetched to try it.

## Tested versions

Verified on 2 October 2026 on Windows 11 (26100) and WSL2 Ubuntu 24.04.

| | Version | How it was checked |
|---|---|---|
| Python | **3.14.6** (Windows), 3.12.3 (WSL) | the full test suite on both; 3.11 is the documented minimum |
| `jsonschema` | 4.26.0 | API contract tests, including the provenance schema |
| `cryptography` | 50.0.0 | agent identity, encrypted sessions and the vault |
| `numpy` | 2.5.2 | signal and model code |
| `pyarrow` | 25.0.1 | Parquet export of shared answers and the knowledge base |
| `huggingface_hub` | 1.28.0 (local), 2.1.1 (CI) | model publishing and the knowledge dataset; both work |
| `pytest` | 9.1.1 | 1,100+ tests |
| Ollama | 0.35.0 | local model, and `rabbit model install` |
| SQLite | bundled with Python | the research catalog |

**Public APIs** last exercised against live responses on 2 October 2026: PubMed and ClinVar
(E-utilities), Europe PMC REST, ClinicalTrials.gov **API v2** (v1 is retired and returns 404), NIH
RePORTER v2. Each adapter's captured request and response are in [docs/sources/](sources/README.md).

**Not verified here:** pandas (the notebook step in the tutorial is written for 2.x, and the
standard-library version beside it is the one that was run), Zotero/Mendeley/EndNote importers (the RIS
and BibTeX output is standard, but no importer was run as part of the test suite). If you try one and it
mis-imports, that is worth an issue.

## Stability

- **Exports and the provenance format are v1 and additive.** New optional fields can appear in v1;
  anything that would break a reader gets a `-v2` schema. The rules are in
  [docs/api/README.md](api/README.md).
- **Citation keys are stable.** They derive only from the record (first author, year, source and source
  id), so re-exporting the same record gives the same key and a reference manager can match an update to
  the entry it already has.
- **Record identifiers are the source's own.** PMIDs, NCT numbers, VCV accessions and project numbers are
  kept verbatim and paired with the source name, because neither half identifies a record alone.

## Before building a larger integration

Please open an [issue or discussion](https://github.com/DNA-Blockchain/Helloworld/issues) first, and say
what your users would actually do with it. Two reasons that is not a formality:

1. **The format may be wrong for you.** `source:id` as a composite string, free-text `rights_status`, and
   provenance only in JSONL are all decisions that could be made differently. They are easier to change
   now than after either project has shipped against them.
2. **Small and documented beats large and speculative.** A single adapter, a single export format or a
   correction to one of the documented responses is more useful than a broad integration nobody asked
   for.

Specific questions where an answer would change this project rather than just confirm it:

- Does `source:id` match how your tool identifies records, or do you use CURIEs (`pmid:42789486`) or DOIs
  as the primary key?
- Should `rights_status` carry an SPDX identifier when one is known, instead of free text?
- Is RIS `DB`/`AN` plus BibTeX `note` where your importer looks for source attribution?
- Would a provenance block in a notebook-friendly format other than JSONL be more useful?

## Contributing back

If something documented here is wrong about **your** project or API, a correction is as welcome as a
feature. If a general improvement belongs in a library this project depends on rather than here, it
should go there: a focused issue or patch that helps that library's users, not a change that only
benefits RabbitSoftware.

Repository conventions (branching, commit messages, PR labels and milestones) are in
[CLAUDE.md](../CLAUDE.md); release process in [RELEASING.md](../RELEASING.md); honest limitations in
[KNOWN_GAPS.md](../KNOWN_GAPS.md).
