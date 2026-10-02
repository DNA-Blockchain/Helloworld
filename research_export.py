"""Research records out of RabbitSoftware in formats other tools read: BibTeX, RIS, CSV and JSONL.

    python research_export.py --format bibtex --out records.bib
    python research_export.py --format ris    --out records.ris --source pubmed --limit 50
    python research_export.py --format csv    --out records.csv --query "BRCA1"
    python research_export.py --format jsonl  --out records.jsonl        # with provenance per record

Every row carries its **source identifier and URL**, so a citation can be traced back to the record it
came from: `pubmed:42789486` with `https://pubmed.ncbi.nlm.nih.gov/42789486/`. BibTeX and RIS are what
Zotero, Mendeley, JabRef, EndNote and Papers import. CSV suits a spreadsheet or pandas. JSONL suits a
notebook and is the only one of the four that keeps the provenance block
(docs/api/provenance.md), because the citation formats have no field for it.

Only `public` records are exported by default: restricted and private ones stay on this PC unless
`--classification` names them, and the CLI says so when it does. What a source's terms allow is in each
record's `rights_status` and `terms_url`, which travel with the export (CSV and JSONL carry them as
columns; BibTeX and RIS carry them in a note field), so attribution survives the trip.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import sys
import time
from pathlib import Path

from research_catalog import DEFAULT_CATALOG, ResearchCatalog, author_list

FORMATS = ("bibtex", "ris", "csv", "jsonl")
# BibTeX entry type per record type; RIS reference type likewise.
BIBTEX_TYPES = {"article": "article", "preprint": "misc", "clinical_trial": "misc", "grant": "misc",
                "variant": "misc", "dataset": "misc", "other": "misc"}
RIS_TYPES = {"article": "JOUR", "preprint": "UNPB", "clinical_trial": "DBASE", "grant": "GRANT",
             "variant": "DBASE", "dataset": "DATA", "other": "GEN"}
# A record from before the citation fields existed has no record_type. Infer it from the source rather
# than exporting every old record as @misc.
SOURCE_RECORD_TYPES = {"pubmed": "article", "europe_pmc": "article", "clinicaltrials.gov": "clinical_trial",
                       "nih_reporter": "grant", "clinvar": "variant", "dbsnp": "variant"}
CSV_COLUMNS = ("source", "external_id", "citation_key", "record_type", "title", "authors", "container",
               "publisher", "volume", "issue", "pages", "published_at", "year", "doi", "source_url",
               "classification", "rights_status", "terms_url", "abstract")
NOT_PUBLIC_WARNING = ("Exporting {n} record(s) that are not classified public. Check each source's terms "
                      "before sharing the file.")


_TAG = re.compile(r"</?(?:i|b|em|strong|sub|sup|u|span|p|br)\s*/?>", re.I)


def plain_text(value) -> str:
    """Source text as one clean line. Sources put markup in titles and abstracts: Europe PMC returns
    HTML-escaped tags (`&lt;i&gt;BRCA1&lt;/i&gt;`) and PubMed returns real ones (`<i>BRCA1</i>`), both of
    which would otherwise reach a reference manager as literal angle brackets. Entities are unescaped
    once, simple inline tags dropped, and whitespace collapsed. The catalog keeps the source's own bytes;
    only the export is cleaned."""
    text = html.unescape(str(value or ""))
    return " ".join(_TAG.sub("", text).split())


def record_type_of(record: dict) -> str:
    return record.get("record_type") or SOURCE_RECORD_TYPES.get(record.get("source", ""), "other")


def year_of(record: dict) -> str:
    """The four-digit year in a published_at value, which sources write many ways ("2026 Sep 25",
    "2026", "2017-03-13"). Empty when there isn't one, rather than a guess."""
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", str(record.get("published_at", "")))
    return match.group(1) if match else ""


def citation_key(record: dict) -> str:
    """A stable, collision-free key: first author's surname, year and the source id (e.g.
    `chen2026pubmed42789486`). Derived only from the record, so re-exporting gives the same key and a
    reference manager can match an update to the entry it already has."""
    authors = author_list(record)
    surname = re.sub(r"[^a-z]", "", authors[0].split()[0].casefold()) if authors else ""
    source = re.sub(r"[^a-z0-9]", "", str(record.get("source", "")).casefold())
    identifier = re.sub(r"[^a-z0-9]", "", str(record.get("external_id", "")).casefold())
    return f"{surname}{year_of(record)}{source}{identifier}" or "record"


def attribution(record: dict) -> str:
    """One line naming where a record came from and under what terms, for formats with only a note
    field. The source and its identifier always appear, so the trail back is never lost."""
    parts = [f"Retrieved from {record.get('source', 'unknown source')} "
             f"({record.get('source', '')}:{record.get('external_id', '')})"]
    if record.get("rights_status"):
        parts.append(f"rights: {record['rights_status']}")
    if record.get("terms_url"):
        parts.append(f"terms: {record['terms_url']}")
    return ". ".join(parts) + "."


# -- BibTeX --------------------------------------------------------------------------------------------
_BIBTEX_ESCAPES = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "%": r"\%",
                   "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def bibtex_escape(text: str) -> str:
    """BibTeX's special characters, escaped. The backslash is replaced first, or its own replacement
    would be escaped again."""
    out = str(text).replace("\\", _BIBTEX_ESCAPES["\\"])
    for character, replacement in _BIBTEX_ESCAPES.items():
        if character != "\\":
            out = out.replace(character, replacement)
    return " ".join(out.split())


def to_bibtex(records: list[dict]) -> str:
    entries = []
    for record in records:
        kind = BIBTEX_TYPES.get(record_type_of(record), "misc")
        fields: list[tuple[str, str]] = [("title", bibtex_escape(plain_text(record.get("title"))))]
        authors = author_list(record)
        if authors:
            fields.append(("author", " and ".join(bibtex_escape(a) for a in authors)))
        for name, key in (("journal", "container"), ("publisher", "publisher"), ("volume", "volume"),
                          ("number", "issue"), ("pages", "pages"), ("doi", "doi")):
            value = plain_text(record.get(key, ""))
            if value:
                # journal belongs to @article only; anything else carries it as howpublished.
                name = "howpublished" if name == "journal" and kind != "article" else name
                fields.append((name, bibtex_escape(value)))
        if year_of(record):
            fields.append(("year", year_of(record)))
        if record.get("source_url"):
            fields.append(("url", bibtex_escape(record["source_url"])))
        fields.append(("note", bibtex_escape(attribution(record))))
        body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
        entries.append(f"@{kind}{{{citation_key(record)},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


# -- RIS -----------------------------------------------------------------------------------------------
def to_ris(records: list[dict]) -> str:
    """RIS: two-letter tags, "  - " between tag and value, ER as the last line of each reference.
    Newlines inside a value are flattened, because RIS is line-oriented."""
    flat = plain_text
    out = io.StringIO()
    for record in records:
        lines = [("TY", RIS_TYPES.get(record_type_of(record), "GEN"))]
        lines += [("AU", flat(name)) for name in author_list(record)]
        lines.append(("TI", flat(record.get("title", ""))))
        for tag, key in (("JO", "container"), ("PB", "publisher"), ("VL", "volume"), ("IS", "issue"),
                         ("SP", "pages"), ("DO", "doi"), ("UR", "source_url")):
            if record.get(key):
                lines.append((tag, flat(record[key])))
        if year_of(record):
            lines.append(("PY", year_of(record)))
        if record.get("published_at"):
            lines.append(("DA", flat(record["published_at"])))
        if record.get("abstract"):
            lines.append(("AB", flat(record["abstract"])))
        lines.append(("DB", flat(record.get("source", ""))))
        lines.append(("AN", flat(record.get("external_id", ""))))      # accession number in the source
        lines.append(("N1", flat(attribution(record))))
        for tag, value in lines:
            out.write(f"{tag}  - {value}\n")
        out.write("ER  - \n\n")
    return out.getvalue()


# -- CSV and JSONL -------------------------------------------------------------------------------------
def to_csv(records: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for record in records:
        row = {name: record.get(name, "") for name in CSV_COLUMNS}
        row.update(authors="; ".join(author_list(record)), citation_key=citation_key(record),
                   record_type=record_type_of(record), year=year_of(record),
                   title=plain_text(record.get("title")), container=plain_text(record.get("container")),
                   abstract=plain_text(record.get("abstract")))
        writer.writerow(row)
    return out.getvalue()


def to_jsonl(records: list[dict], *, exported_at: float | None = None, code_fingerprint: str = "") -> str:
    """One JSON object per line, each with a `provenance` block: where the record came from, when it was
    retrieved and exported, and the code fingerprint of the exporting software
    (schemas/rabbitsoftware-provenance-v1.schema.json)."""
    exported_at = time.time() if exported_at is None else exported_at
    out = io.StringIO()
    for record in records:
        row = {name: record.get(name, "") for name in
               ("source", "external_id", "title", "abstract", "source_url", "published_at",
                "container", "publisher", "volume", "issue", "pages", "doi", "record_type",
                "classification")}
        row.update(authors=author_list(record), citation_key=citation_key(record), year=year_of(record),
                   record_type=record_type_of(record), title=plain_text(record.get("title")),
                   abstract=plain_text(record.get("abstract")), container=plain_text(record.get("container")),
                   provenance=provenance_block(record, exported_at=exported_at,
                                               code_fingerprint=code_fingerprint))
        out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return out.getvalue()


def provenance_block(record: dict, *, exported_at: float, code_fingerprint: str = "") -> dict:
    """The provenance of one exported record, in the shape documented at docs/api/provenance.md."""
    block = {"schema": "rabbitsoftware-provenance.v1", "source": record.get("source", ""),
             "source_id": f"{record.get('source', '')}:{record.get('external_id', '')}",
             "source_url": record.get("source_url", ""),
             "rights_status": record.get("rights_status", ""), "terms_url": record.get("terms_url", ""),
             "exported_at": round(exported_at, 3), "exported_by": "RabbitSoftware research_export.py"}
    if record.get("retrieved_at"):
        block["retrieved_at"] = round(float(record["retrieved_at"]), 3)
    if code_fingerprint:
        block["code_fingerprint"] = code_fingerprint
    return block


def export(records: list[dict], fmt: str, *, code_fingerprint: str = "") -> str:
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}, not {fmt!r}")
    if fmt == "bibtex":
        return to_bibtex(records)
    if fmt == "ris":
        return to_ris(records)
    if fmt == "csv":
        return to_csv(records)
    return to_jsonl(records, code_fingerprint=code_fingerprint)


# -- the command line ----------------------------------------------------------------------------------
def backfill_citations(catalog: ResearchCatalog, *, limit: int = 100, summaries=None, log=print) -> dict:
    """Fetches citation metadata for records that have none, from the source's own summary endpoint.

    Records retrieved before the citation fields existed carry only title, date and URL, which exports as
    an entry with no author. PubMed and Europe PMC records are keyed by PMID, so one esummary request
    covers both. Other sources are skipped rather than guessed at: a wrong journal in a citation is
    worse than a missing one."""
    if summaries is None:
        from multi_source_research import pubmed_summaries as summaries
    pending = catalog.missing_citations(limit=limit)
    by_pmid = {external_id: source for source, external_id in pending if external_id.isdigit()}
    skipped = len(pending) - len(by_pmid)
    if not by_pmid:
        return {"checked": len(pending), "updated": 0, "skipped": skipped, "not_found": 0}
    updated = 0
    found = set()
    for start in range(0, len(by_pmid), 200):              # the endpoint takes at most 200 ids a request
        batch = list(by_pmid)[start:start + 200]
        try:
            papers = summaries(batch)
        except Exception as error:                         # offline, rate-limited, or the source is down
            log(f"citation backfill stopped: {type(error).__name__}: {error}")
            break
        for paper in papers:
            pmid = str(paper.get("pmid", ""))
            if pmid not in by_pmid:
                continue
            found.add(pmid)
            if catalog.set_citation(by_pmid[pmid], pmid, paper):
                updated += 1
    return {"checked": len(pending), "updated": updated, "skipped": skipped,
            "not_found": len(by_pmid) - len(found)}


def select(catalog: ResearchCatalog, *, query: str = "", source: str = "", classification: str = "public",
           limit: int = 200) -> list[dict]:
    """The records to export: whole rows, filtered here rather than by `catalog.retrieve`, which returns
    the nested citation shape the assistant's answers use instead of a full row."""
    records = catalog.all_records(classification=classification)
    if source:
        records = [r for r in records if r.get("source") == source]
    terms = [t for t in re.findall(r"[\w-]+", query.casefold()) if t]
    if terms:
        records = [r for r in records
                   if any(t in f"{r.get('title', '')} {r.get('abstract', '')}".casefold() for t in terms)]
    return records[:limit]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    parser.add_argument("--format", required=True, choices=FORMATS)
    parser.add_argument("--out", type=Path, help="write here instead of standard output")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--query", default="", help="only records matching these words")
    parser.add_argument("--source", default="", help="only this source, e.g. pubmed")
    parser.add_argument("--classification", default="public", choices=["public", "restricted", "private"])
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--backfill", action="store_true",
                        help="first fetch citation metadata for records that have none (contacts the source)")
    parser.add_argument("--fingerprint", action="store_true",
                        help="record this code state's fingerprint in JSONL provenance (needs git)")
    args = parser.parse_args(argv)
    if not Path(args.catalog).exists():
        print(f"No research catalog at {args.catalog}. Fill one with:\n"
              f'  python dna_shell.py research-search "your terms" --confirm-public-query\n'
              f"or by answering yes to a public search in: python rabbit.py chat", file=sys.stderr)
        return 1
    catalog = ResearchCatalog(args.catalog)
    if args.backfill:
        result = backfill_citations(catalog, log=lambda m: print(m, file=sys.stderr))
        print(f"Citation backfill: {result['updated']} record(s) filled in, {result['skipped']} skipped "
              f"(no PMID), {result['not_found']} not found at the source, of {result['checked']} missing.",
              file=sys.stderr)
    records = select(catalog, query=args.query, source=args.source,
                     classification=args.classification, limit=args.limit)
    if not records:
        print("No records matched, so nothing was written.", file=sys.stderr)
        return 1
    not_public = [r for r in records if r.get("classification") != "public"]
    if not_public:
        print(NOT_PUBLIC_WARNING.format(n=len(not_public)), file=sys.stderr)
    fingerprint = ""
    if args.fingerprint and args.format == "jsonl":
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "code_fingerprint", Path(__file__).resolve().parent / "scripts" / "code_fingerprint.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            fingerprint = module.manifest(module.ROOT, "HEAD")["fingerprint"]
        except Exception as error:                      # no git, or not a checkout
            print(f"No code fingerprint recorded: {error}", file=sys.stderr)
    text = export(records, args.format, code_fingerprint=fingerprint)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{len(records)} record(s) to {args.out} ({args.format}).", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
