#!/usr/bin/env python3
"""
research_corrections.py
=======================
Audits published research records against their public sources and queues
public_research_correction events for records damaged by the kernel
text-decoding fault: the Network OS MicroPython ran without Unicode strings
(and compared bytes as signed chars), so every character above U+00FF in a
record reached the ranking task cut to its low byte. The published title
showed the wrong character and the record hash covered the damaged text.

For each audited event the topic is fetched again and every published record
is checked:
  ok          its hash is the correct hash of the source record;
  corrected   a correction for it is already on the chain;
  damaged     its hash is exactly what the faulty kernel computes from the
              source record, and differs from the correct hash (proof);
  unverified  neither: the source record changed or is no longer returned.
Only damaged records are corrected. Without --confirm-publication this is a
dry run.

Usage:
    python research_corrections.py                       # audit every event
    python research_corrections.py --since 2026-09-29T07:49:00+00:00
    python research_corrections.py --confirm-publication # queue corrections
"""

from __future__ import annotations

import auto_approve

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import research_analysis
import research_fetch
import research_publish
from research_ledger import published_corrections, published_events
from research_provenance import ResearchProvenanceQueue, create_public_research_correction_event
from research_publish import DEFAULT_OUTBOX

ROOT = Path(__file__).resolve().parent
REASON = "kernel-text-decoding"
# MicroPython's str.strip() set, used by the faulty kernel.
_KERNEL_WHITESPACE = " \t\n\r\x0b\x0c"


def faulty_kernel_text(value: str) -> str:
    """`value` as the faulty kernel held it. The host wrote JSON with \\u
    escapes, and the byte-string MicroPython kept the low byte of each
    escape; a character outside the BMP was escaped as a surrogate pair."""
    out = []
    for ch in value:
        code = ord(ch)
        if code > 0xFFFF:
            code -= 0x10000
            out.append(chr((0xD800 + (code >> 10)) & 0xFF))
            out.append(chr((0xDC00 + (code & 0x3FF)) & 0xFF))
        else:
            out.append(chr(code & 0xFF))
    return "".join(out)


def faulty_kernel_record(raw: dict) -> dict:
    """research_analysis.validate_record as the faulty kernel ran it."""
    def text(field: str, limit: int) -> str:
        return faulty_kernel_text(str(raw.get(field) or "")).strip(_KERNEL_WHITESPACE)[:limit]

    return {
        "source": text("source", 32).lower(),
        "external_id": text("external_id", 64),
        "title": text("title", 400),
        "abstract": text("abstract", 1000),
        "source_url": text("source_url", 300),
        "published_at": text("published_at", 32),
    }


def record_hash(record: dict) -> str:
    return research_analysis.sha256_hex(research_analysis.canonical_json(record))


@dataclass
class Finding:
    event_id: str
    query: str
    source: str
    external_id: str
    status: str
    published_title: str
    published_sha256: str
    title: str = ""
    record_sha256: str = ""


def audit_event(event: dict, fresh: dict[tuple[str, str], dict], corrected: set[tuple[str, str, str]]) -> list[Finding]:
    """Classify each record of a public_research_records event against the
    freshly fetched source records, keyed by (source, external_id)."""
    findings = []
    for published in event["records"]:
        key = (published["source"], published["external_id"])
        finding = Finding(event["event_id"], event["query"], key[0], key[1], "unverified",
                          published["title"], published["record_sha256"])
        findings.append(finding)
        if (event["event_id"], *key) in corrected:
            finding.status = "corrected"
            continue
        raw = fresh.get(key)
        if raw is None:
            continue
        correct = research_analysis.validate_record(raw)
        finding.title = correct["title"][:research_analysis.MAX_TITLE_CHARS]
        finding.record_sha256 = record_hash(correct)
        if published["record_sha256"] == finding.record_sha256:
            finding.status = "ok"
        elif published["record_sha256"] == record_hash(faulty_kernel_record(raw)):
            finding.status = "damaged"
    return findings


def fetch_records(query: str, sources: list[str], max_results: int) -> dict[tuple[str, str], dict]:
    """The topic's source records, fetched as research_queue.py fetches them."""
    terms = list(dict.fromkeys(query.lower().split()))
    request = research_fetch.fetch(query, terms, sources, max_results)
    return {(r["source"], r["external_id"]): r for r in request["records"]}


def audit(events: list[dict], *, sources: list[str], max_results: int,
          corrected: set[tuple[str, str, str]]) -> tuple[list[Finding], list[str]]:
    findings, notes, fetched = [], [], {}
    for event in events:
        query = event["query"]
        if query not in fetched:
            try:
                fetched[query] = fetch_records(query, sources, max_results)
            except (OSError, ValueError, RuntimeError) as error:
                notes.append(f"{query}: fetch failed ({error})")
                fetched[query] = {}
        findings.extend(audit_event(event, fetched[query], corrected))
    return findings, notes


def correction_events(findings: list[Finding], *, time_anchor: dict | None = None) -> list[dict]:
    """One correction event per damaged event, listing its damaged records."""
    by_event: dict[str, list[Finding]] = {}
    for finding in findings:
        if finding.status == "damaged":
            by_event.setdefault(finding.event_id, []).append(finding)
    return [
        create_public_research_correction_event(
            corrects_event_id=event_id,
            reason=REASON,
            records=[{
                "source": f.source, "external_id": f.external_id, "title": f.title,
                "record_sha256": f.record_sha256, "published_record_sha256": f.published_sha256,
            } for f in damaged],
            confirm_publication=True,
            time_anchor=time_anchor,
        )
        for event_id, damaged in by_event.items()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", help="audit events created at or after this ISO time")
    parser.add_argument("--source", action="append", choices=research_analysis.PUBLIC_SOURCES,
                        help="sources to fetch (default: research_queue.py's defaults)")
    parser.add_argument("--max-results", type=int, default=5, help="records per source (research_queue.py's default)")
    parser.add_argument("--ledgers", type=Path, default=ROOT / "autonomous")
    parser.add_argument("--outbox", type=Path, default=DEFAULT_OUTBOX)
    parser.add_argument("--confirm-publication", action="store_true",
                        help="queue the corrections for the permanent node chain")
    args = parser.parse_args(argv)
    if auto_approve.enabled():
        args.confirm_publication = True

    events = sorted(published_events(str(args.ledgers), "public_research_records").values(),
                    key=lambda event: event["created_at"])
    if args.since:
        since = datetime.fromisoformat(args.since)
        events = [event for event in events if datetime.fromisoformat(event["created_at"]) >= since]
    corrected = set(published_corrections(str(args.ledgers)))
    findings, notes = audit(events, sources=args.source or list(research_fetch.DEFAULT_SOURCES),
                            max_results=args.max_results, corrected=corrected)
    for note in notes:
        print(note)
    for finding in findings:
        if finding.status == "damaged":
            print(f"damaged  {finding.source}:{finding.external_id} in '{finding.query}' ({finding.event_id})")
            if finding.title != finding.published_title:
                print(f"   published: {finding.published_title!a}")
                print(f"   source:    {finding.title!a}")
            else:
                print("   title intact; the hash covered damaged abstract text")
    counts = {status: sum(f.status == status for f in findings)
              for status in ("ok", "corrected", "damaged", "unverified")}
    print(f"{len(events)} event(s), {len(findings)} record(s): "
          + ", ".join(f"{count} {status}" for status, count in counts.items()))
    events_out = correction_events(findings, time_anchor=research_publish.current_time_anchor()
                                   if args.confirm_publication and counts["damaged"] else None)
    if not args.confirm_publication:
        print(f"Dry run: {len(events_out)} correction event(s) not queued. "
              "Add --confirm-publication to publish them permanently.")
        return 0
    queue = ResearchProvenanceQueue(args.outbox)
    for event in events_out:
        queue.enqueue(event)
    print(f"Queued {len(events_out)} correction event(s) for node-0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
