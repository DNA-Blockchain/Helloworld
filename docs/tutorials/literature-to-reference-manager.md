# Tutorial: public literature into Zotero, with its provenance intact

Fifteen minutes, no account, nothing paid. You will retrieve a few public literature records, keep their
citations and provenance, import them into **Zotero** (or Mendeley, JabRef, EndNote), and read the same
records in a **pandas** notebook. The point is the join: RabbitSoftware does the retrieval and the
provenance, and your reference manager and notebook do what they are good at.

Everything here runs on your own machine. The only outbound traffic is the literature search itself.

## What you need

| | |
|---|---|
| Python | 3.11 or newer (developed on 3.14.6) |
| RabbitSoftware | `git clone https://github.com/DNA-Blockchain/Helloworld` and `pip install -r requirements.txt` |
| Zotero | 7.x, or any manager that imports BibTeX or RIS |
| pandas | 2.x, optional, for the last step |

Tested versions are listed in [the integration guide](../integration.md).

## 1. Retrieve a few records

```bash
python dna_shell.py research-search "BRCA1 breast cancer remission" \
    --sources pubmed,europe_pmc --max-results 5 --confirm-public-query
```

That queries the sources, normalizes each result, and saves it in the local catalog with its source
identifier, URL and terms. Nothing is published anywhere. `--confirm-public-query` is required and is
not a formality: a search term is disclosed to whoever runs the API, so the tool makes you say so.

In RabbitSoftware.inc (`python rabbit.py chat`) the same thing happens when you ask a research question
and answer yes to the offer to search public sources.

Prefer not to make any network call? Use the committed example dataset instead, which holds 15 real
records across five sources:

```bash
python examples/research/fetch_example.py --check     # verifies the files against their checksums
```

## 2. Export for your reference manager

```bash
python rabbit.py export --format ris --out records.ris
```

Each entry keeps the source's own identifier, so a citation can always be traced back:

```
TY  - JOUR
AU  - Dhungyal B
TI  - Phytochemical Characterization of Tupistra nutans Inflorescence...
JO  - Applied biochemistry and biotechnology
DO  - 10.1007/s12010-026-05649-8
UR  - https://pubmed.ncbi.nlm.nih.gov/42301569/
DB  - pubmed
AN  - 42301569
N1  - Retrieved from pubmed (pubmed:42301569). rights: unknown; review source and record terms. terms: https://www.ncbi.nlm.nih.gov/home/about/policies/
```

`DB` and `AN` are the source and its accession number; `N1` carries the attribution, which most managers
show as a note. BibTeX works the same way with `--format bibtex`, putting the attribution in `note`.

**Import into Zotero:** File → Import → *A file* → choose `records.ris` → Next. Zotero reads the authors,
journal, DOI and URL, and keeps the note. A tip worth taking: import into a **new collection** (Zotero
offers this in the import dialog), so a re-export later doesn't mix with your existing library.

**If your records import without authors,** they were retrieved before citation metadata was captured.
Fill them in from the source and export again:

```bash
python rabbit.py export --format ris --out records.ris --backfill
```

## 3. Keep the provenance that citation formats can't carry

BibTeX and RIS have no field for "when was this retrieved, and under what terms". JSONL does:

```bash
python rabbit.py export --format jsonl --out records.jsonl --fingerprint
```

```json
{
  "citation_key": "dhungyal2026pubmed42301569",
  "title": "Phytochemical Characterization of Tupistra nutans Inflorescence...",
  "authors": ["Dhungyal B", "Ramachandran B"],
  "doi": "10.1007/s12010-026-05649-8",
  "provenance": {
    "schema": "rabbitsoftware-provenance.v1",
    "source_id": "pubmed:42301569",
    "retrieved_at": 1790934385.749,
    "exported_at": 1790934400.112,
    "rights_status": "unknown; review source and record terms",
    "terms_url": "https://www.ncbi.nlm.nih.gov/home/about/policies/",
    "code_fingerprint": "bc80e7ca3908ee9100293d62b01adb47ef2854ae90168086ef1e990549a00bbd"
  }
}
```

`--fingerprint` records the SHA-256 of the exact code state that produced the file, so months later you
can tell which version of which software made it. The format is documented at
[docs/api/provenance.md](../api/provenance.md) and is yours to use without any of the rest of this
project.

## 4. Read the same records in a notebook

The file is JSON Lines, so the standard library is enough:

```python
import json
from datetime import datetime, timezone

records = [json.loads(line) for line in open("records.jsonl", encoding="utf-8")]
for r in records[:5]:
    print(r["year"], r["citation_key"], "|", r["container"] or r["record_type"])

# How old is this copy, and may it be reused?
newest = max(r["provenance"]["retrieved_at"] for r in records)
print("newest record retrieved:", datetime.fromtimestamp(newest, timezone.utc))
print("terms seen:", {r["provenance"]["rights_status"] for r in records})
```

With **pandas** (2.x), the provenance flattens into columns:

```python
import pandas as pd

records = pd.read_json("records.jsonl", lines=True)
provenance = pd.json_normalize(records["provenance"])
records["retrieved"] = pd.to_datetime(provenance["retrieved_at"], unit="s")
print(records[["citation_key", "year", "container", "doi"]].head())
print(records.groupby(provenance["source"])["retrieved"].max())
```

The same file therefore serves the reference manager (through step 2) and the analysis, and both keep the
link back to the source record.

## 5. Optional: check the trail later

Two things stay verifiable after the fact, both without a server or a ledger:

```bash
python scripts/code_fingerprint.py --commit v0.11.0   # does the fingerprint in the export still match?
```

and the local audit log, which is a hash chain any SHA-256 implementation can verify. The
[provenance page](../api/provenance.md) has a 10-line Python checker.

## What this does not do

- It does not judge the records. Retrieval order is by query-term match and recency, which is a reading
  order, not a relevance or quality judgment.
- It does not resolve reuse terms for you. `rights_status: unknown` is the common and honest answer;
  read the source's terms before republishing anything.
- It is not a literature-review method. It gets records out of five APIs with their provenance intact.

## Questions worth asking back

If you maintain a reference manager, a notebook template or a literature client, two specific answers
would change this rather than just confirm it:

1. **Is `DB`/`AN` (RIS) and `note` (BibTeX) where your importer expects source attribution?** If your
   tool reads provenance from somewhere else, say where and this will emit it there too.
2. **Would the JSONL provenance block be useful to you at all,** or is a per-record `retrieved_at` enough?

[Open an issue or discussion](https://github.com/DNA-Blockchain/Helloworld/issues). A worked example that
is wrong about your tool is worth correcting, so corrections are as welcome as features.
