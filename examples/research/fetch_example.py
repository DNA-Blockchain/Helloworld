#!/usr/bin/env python3
"""Regenerate the example research dataset from the public sources, and check it against its checksums.

    python examples/research/fetch_example.py --check       # verify the committed files (no network)
    python examples/research/fetch_example.py --fetch       # re-fetch from the sources (asks first)

The committed dataset is deliberately tiny: a handful of public records per source, enough to try the
exports and the provenance format without copying anyone's database. Large datasets are not vendored
here, because their terms and update schedules differ (see docs/genomics/README.md for the catalogue
that handles those by licence and access tier).

`--check` recomputes the SHA-256 of each committed file and compares it with checksums.json, so a
reviewer can confirm the files are the ones the manifest describes without contacting any source.

`--fetch` contacts PubMed, Europe PMC, ClinicalTrials.gov, ClinVar and NIH RePORTER, so it asks first.
Results change as the sources add records, so a re-fetch is expected to produce different files and
different checksums; it rewrites checksums.json and prints what moved. That is the point of keeping the
script: the data is reproducible in method, not frozen in content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

QUERIES = {
    "pubmed": "BRCA1 breast cancer remission",
    "europe_pmc": "BRCA1 breast cancer",
    "clinicaltrials.gov": "BRCA1 breast cancer",
    "clinvar": "BRCA1[gene] AND pathogenic",
    "nih_reporter": "BRCA1 breast cancer",
}
PER_SOURCE = 3
RECORDS = HERE / "records.jsonl"
CHECKSUMS = HERE / "checksums.json"
EXPORTS = {"records.bib": "bibtex", "records.ris": "ris", "records.csv": "csv"}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check() -> int:
    """Every committed file against its recorded SHA-256. No network."""
    if not CHECKSUMS.exists():
        print(f"No checksums at {CHECKSUMS}. Generate the dataset with --fetch.", file=sys.stderr)
        return 1
    manifest = json.loads(CHECKSUMS.read_text(encoding="utf-8"))
    problems = []
    for name, expected in sorted(manifest["files"].items()):
        path = HERE / name
        if not path.exists():
            problems.append(f"{name}: missing")
            continue
        actual = sha256_of(path)
        if actual != expected["sha256"]:
            problems.append(f"{name}: SHA-256 is {actual[:12]}..., the manifest says {expected['sha256'][:12]}...")
        elif path.stat().st_size != expected["bytes"]:
            problems.append(f"{name}: {path.stat().st_size} bytes, the manifest says {expected['bytes']}")
    print(f"{len(manifest['files'])} file(s) checked against checksums.json "
          f"(fetched {manifest.get('fetched_at_human', 'unknown')}).")
    if problems:
        print("Problems:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print("Every file matches its checksum.")
    return 0


def fetch(ask=input) -> int:
    """Re-fetch from the public sources, rewrite the files, and record new checksums."""
    sources = ", ".join(QUERIES)
    print(f"This contacts {sources} and sends only the search terms in this script.")
    if ask(f"Fetch up to {PER_SOURCE} records from each? (yes/no) ").strip().lower() not in ("y", "yes"):
        print("Nothing was fetched.")
        return 1

    from research_catalog import ResearchCatalog, search_public_sources
    import research_export

    catalog = ResearchCatalog(HERE / "_catalog.sqlite3")      # a scratch catalog, not the project's
    found: dict[str, int] = {}
    for source, query in QUERIES.items():
        try:
            records = search_public_sources(query, sources=(source,), max_results=PER_SOURCE)
        except Exception as error:                            # one source failing must not lose the rest
            print(f"  {source}: failed ({type(error).__name__}: {error})", file=sys.stderr)
            found[source] = 0
            continue
        catalog.add_records(records)
        found[source] = len(records)
        print(f"  {source}: {len(records)} record(s)")
    rows = catalog.all_records(classification="public")
    if not rows:
        print("No records were fetched, so nothing was written.", file=sys.stderr)
        return 1

    fetched_at = time.time()
    RECORDS.write_text(research_export.to_jsonl(rows, exported_at=fetched_at), encoding="utf-8")
    for name, fmt in EXPORTS.items():
        (HERE / name).write_text(research_export.export(rows, fmt), encoding="utf-8")
    (HERE / "_catalog.sqlite3").unlink(missing_ok=True)

    files = {name: {"sha256": sha256_of(HERE / name), "bytes": (HERE / name).stat().st_size}
             for name in ["records.jsonl", *EXPORTS]}
    previous = (json.loads(CHECKSUMS.read_text(encoding="utf-8")).get("files", {})
                if CHECKSUMS.exists() else {})
    CHECKSUMS.write_text(json.dumps({
        "schema": "rabbitsoftware-example-dataset.v1",
        "description": "A few public research records per source, with their provenance, for trying the "
                       "exports. Regenerate with: python examples/research/fetch_example.py --fetch",
        "fetched_at": round(fetched_at, 3),
        "fetched_at_human": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(fetched_at)),
        "queries": QUERIES, "records_per_source": PER_SOURCE, "records": len(rows),
        "records_found": found, "files": files,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"\n{len(rows)} record(s) written to {HERE.relative_to(ROOT)}/ and checksummed.")
    for name, entry in sorted(files.items()):
        was = previous.get(name, {}).get("sha256", "")
        state = "new" if not was else ("unchanged" if was == entry["sha256"] else f"changed from {was[:12]}...")
        print(f"  {name:<16} {entry['sha256'][:12]}...  {entry['bytes']:>7} bytes  ({state})")
    print("\nSources add and correct records, so different checksums after a re-fetch are expected, not a "
          "failure. Commit the new files together with checksums.json.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="verify the committed files (no network)")
    group.add_argument("--fetch", action="store_true", help="re-fetch from the public sources (asks first)")
    args = parser.parse_args(argv)
    return check() if args.check else fetch()


if __name__ == "__main__":
    sys.exit(main())
