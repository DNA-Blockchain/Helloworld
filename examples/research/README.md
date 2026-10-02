# A small, reproducible example dataset

Fifteen real public research records, three from each of five sources, with their provenance and the
same records exported to BibTeX, RIS and CSV. Enough to try the exports, the provenance format and an
importer without contacting anything.

| File | What it is |
|---|---|
| [`records.jsonl`](records.jsonl) | the records, one JSON object per line, each with a `provenance` block ([spec](../../docs/api/provenance.md)) |
| [`records.bib`](records.bib) | the same records as BibTeX, for Zotero, JabRef, Mendeley, Overleaf |
| [`records.ris`](records.ris) | the same as RIS, for EndNote, Mendeley, Zotero |
| [`records.csv`](records.csv) | the same as a flat table, for a spreadsheet or pandas |
| [`checksums.json`](checksums.json) | SHA-256 and byte size of each file, the queries used, and when they were fetched |
| [`fetch_example.py`](fetch_example.py) | regenerates all of it, or verifies it offline |

## Verify it without touching the network

```bash
python examples/research/fetch_example.py --check
```

It recomputes each file's SHA-256 and compares it with `checksums.json`, so you can confirm the files
are the ones the manifest describes before trusting them.

## Regenerate it

```bash
python examples/research/fetch_example.py --fetch     # asks first; contacts the five sources
```

The queries are in the script: `"BRCA1 breast cancer remission"` for PubMed, `"BRCA1 breast cancer"` for
Europe PMC, ClinicalTrials.gov and NIH RePORTER, and `"BRCA1[gene] AND pathogenic"` for ClinVar, three
records each.

**Different checksums after a re-fetch are expected, not a failure.** Sources add, correct and withdraw
records, so the content moves. `records.jsonl` changes on every run regardless, because its provenance
records the export time. What is reproducible is the **method**: the script, the queries and the
checksums together say exactly how this copy was made.

## What's in a record

```json
{
  "source": "clinvar",
  "external_id": "VCV004935318",
  "title": "NM_007294.4(BRCA1):c.3900_3904del (p.Cys1300_Glu1302delinsTer)",
  "record_type": "variant",
  "citation_key": "clinvarvcv004935318",
  "provenance": {
    "schema": "rabbitsoftware-provenance.v1",
    "source_id": "clinvar:VCV004935318",
    "source_url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/4935318/",
    "retrieved_at": 1790935242.424,
    "rights_status": "public metadata; review source terms",
    "terms_url": "https://www.ncbi.nlm.nih.gov/home/about/policies/"
  }
}
```

Each record keeps the source's own identifier, so every citation traces back. The adapters that produced
them, with the real request and response for each source, are documented in
[docs/sources/](../../docs/sources/README.md).

## Why it's this small

Three records per source is enough to exercise every format and every record type (`article`,
`clinical_trial`, `variant`, `grant`). Larger datasets are **not** copied into this repository, because
their terms and update schedules differ: GENIE forbids redistribution, MSK-CHORD is non-commercial with
no derivatives, and TRACERx and Hartwig need an institution's approval. Those are handled by the
catalogue in [docs/genomics/](../../docs/genomics/README.md), which records each one's licence and access
tier and refuses to download what it may not.

## Attribution

The records are the work of their sources and submitters: PubMed and ClinVar (NCBI), Europe PMC,
ClinicalTrials.gov, and NIH RePORTER. Each record carries its source's terms URL. Reuse terms differ per
record and often aren't knowable from the record alone, so `rights_status` says `unknown` unless the
source states otherwise. Read the terms before republishing.

These are bibliographic and variant records about published research. They contain no patient data.
