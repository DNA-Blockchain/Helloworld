# Research provenance v1

**A format, not a pitch.** This page documents how RabbitSoftware records where a research record came
from, when, under what terms, and which code produced it. The format is plain JSON and **needs no
blockchain**: any research tool can emit or read it, and nothing in it depends on RabbitSoftware. If you
maintain a literature client, a notebook template or a data pipeline and want records that stay
traceable after they leave your tool, this is offered as something to copy, criticize or ignore.

Schema: [`rabbitsoftware-provenance-v1`](../../schemas/rabbitsoftware-provenance-v1.schema.json).
Exports that carry it: [`research_export.py`](../../research_export.py) (JSONL).

## The idea in one line

A research record is a **snapshot of someone else's data**, so it should travel with the source's own
identifier, the time it was taken, and the terms it came under.

```json
{
  "schema": "rabbitsoftware-provenance.v1",
  "source": "pubmed",
  "source_id": "pubmed:42789486",
  "source_url": "https://pubmed.ncbi.nlm.nih.gov/42789486/",
  "retrieved_at": 1790931234.567,
  "exported_at": 1790934009.949,
  "exported_by": "RabbitSoftware research_export.py",
  "rights_status": "unknown; review source and record terms",
  "terms_url": "https://www.ncbi.nlm.nih.gov/home/about/policies/",
  "code_fingerprint": "bc80e7ca3908ee9100293d62b01adb47ef2854ae90168086ef1e990549a00bbd"
}
```

Four pieces, each with a reason:

| Field | Why it's there |
|---|---|
| `source_id` as `source:id` | Neither half alone identifies a record. `42789486` is meaningless without `pubmed`, and two sources reuse each other's numbers (a Europe PMC result and a PubMed result can share a PMID). |
| `retrieved_at` | Sources correct, update and withdraw records. Without a time, a disagreement between two copies can't be explained. |
| `rights_status` and `terms_url` | Reuse terms differ per source and per record, and often aren't knowable from the record alone. Saying `"unknown; review source and record terms"` is more useful than guessing a licence. |
| `code_fingerprint` | Ties an export to the exact software state that produced it (`scripts/code_fingerprint.py`): SHA-256 of every file, plus one fingerprint over all of them. |

## The four objects

The schema defines four shapes you can adopt separately:

| Definition | What it describes | Produced by |
|---|---|---|
| `recordProvenance` | the block above, attached to one exported record | `research_export.py --format jsonl` |
| `auditEntry` | one entry of a hash-chained local action log | `audit_trail.py` |
| `codeFingerprint` | the SHA-256 manifest of a code state | `scripts/code_fingerprint.py`, attached to every GitHub release |
| `datasetRelease` | a dataset as it was used: file hash, source, licence, access tier | `python -m twinos record` |

## Checking an audit log without any special tools

`auditEntry` is a hash chain whose verification needs nothing but SHA-256. Each entry's hash covers its
own content and the previous entry's hash, so an edit, deletion or reordering breaks every hash from
that point on:

```python
import hashlib, json

previous = "0" * 64
for line in open("system_audit.jsonl", encoding="utf-8"):
    entry = json.loads(line)
    content = {k: entry[k] for k in ("timestamp", "module", "action", "node_id", "details")}
    content["prev_hash"] = previous
    expected = hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()
    assert entry["hash"] == expected and entry["prev_hash"] == previous, f"broken at {entry['action']}"
    previous = entry["hash"]
```

That property is the useful part, and it is independent of any ledger: a tamper-evident append-only log
is worth having whether or not you ever publish a fingerprint anywhere.

## Verifying a code fingerprint

```bash
python scripts/code_fingerprint.py --commit v0.11.0     # recompute and compare with a release manifest
```

It hashes git objects rather than files on disk, so the result is the same on Windows, macOS and Linux
regardless of line-ending settings.

## What is deliberately not in this format

- **No personal data.** `details` in an audit entry holds counts and fingerprints, never the content of
  a query, a genome or a message. RabbitSoftware's own rule is that personal data stays in an encrypted
  vault; where a digest is unavoidable, it is keyed (HMAC) so it cannot be confirmed by guessing the
  content.
- **No claim about correctness.** Provenance says where a record came from, not whether it is right.
  `rights_status: unknown` is a normal, honest value.
- **No chain requirement.** A fingerprint can be published on a ledger, emailed, or kept in a file. The
  format treats that as the user's choice, and RabbitSoftware's chain holds only fingerprints.

## If you maintain a related tool

Two things would be genuinely useful to hear, and would change this format rather than just validate it:

1. **Does `source:id` match how you already identify records?** If your tool uses a different convention
   (CURIEs such as `pmid:42789486`, or DOIs as the primary key), say so: a mapping or an added field is
   easy, a wrong assumption baked into exports is not.
2. **Is `rights_status` as free text the right call?** It is deliberately not an enum, because the honest
   answer is usually "unknown", but an SPDX identifier where one is known might serve readers better.

Open an issue or discussion on
[DNA-Blockchain/Helloworld](https://github.com/DNA-Blockchain/Helloworld/issues). This format is v1 and
additive: new optional fields can appear in v1, and anything that would break a reader gets a `-v2`
schema (see [docs/api/README.md](README.md)).
