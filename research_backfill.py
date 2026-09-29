#!/usr/bin/env python3
# ============================================================================
#  SPDX-License-Identifier: UPL-1.0
#
#  Copyright (c) 2026 Chase Allen Ringquist
#
#  This file is part of an operating system, software, and network Work
#  conceived and authored by Chase Allen Ringquist. The Author retains
#  copyright and authorship. Use of this file is licensed as follows.
#
#  ----------------------------------------------------------------------------
#  The Universal Permissive License (UPL), Version 1.0
#
#  Subject to the condition set forth below, permission is hereby granted to
#  any person obtaining a copy of this software, associated documentation
#  and/or data (collectively the "Software"), free of charge and under any
#  and all copyright rights in the Software, and any and all patent rights
#  owned or freely licensable by each licensor hereunder covering either
#  (i) the unmodified Software as contributed to or provided by such
#  licensor, or (ii) the Larger Works (as defined below), to deal in both
#
#  (a) the Software, and
#
#  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
#  if one is included with the Software (each a "Larger Work" to which the
#  Software is contributed by such licensors),
#
#  without restriction, including without limitation the rights to copy,
#  create derivative works of, display, perform, and distribute the Software
#  and make, use, sell, offer for sale, import, export, have made, and have
#  sold the Software and the Larger Work(s), and to sublicense the foregoing
#  rights on either these or other terms.
#
#  This license is subject to the following condition:
#
#  The above copyright notice and either this complete permission notice or
#  at a minimum a reference to the UPL must be included in all copies or
#  substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#  ----------------------------------------------------------------------------
#
#  Do not remove or alter this notice or any record of origin.
#  See NOTICE.md in the project root for authorship and ownership terms.
#
#  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
#            Bixby, OK, United States
# ============================================================================

"""
research_backfill.py
====================
Publishes research records collected in the past to the node chain.
Sources of past records:

  - research_store.json, the growing research agent's topics (plus any
    further --store files)
  - the research stores and research corpus mirrored in live_store.db:
    e.g. the CRISPR suite's crispr_store and the new IDs past live runs found

The stores keep only IDs, so this re-fetches each record's title, date and
link by ID (PubMed, ClinicalTrials.gov, ClinVar), ranks each source's records
with research_analysis.py, and queues one public_research_records event per
20 records for node-0 to mine.

Records already in any node's research ledger, or already planned from an
earlier source in the same run, are skipped, so running it again only
publishes what is new. Without --confirm-publication it is a dry run.

Usage:
    python research_backfill.py                          # dry run
    python research_backfill.py --confirm-publication
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import research_analysis
from research_ledger import published_record_keys
from research_provenance import (
    MAX_PUBLISHED_RECORDS,
    ResearchProvenanceQueue,
    create_public_research_records_event,
)
from research_publish import DEFAULT_OUTBOX

ROOT = Path(__file__).resolve().parent


def _pubmed(ids: list[str]) -> list[dict]:
    from multi_source_research import pubmed_summaries

    return [
        {"source": "pubmed", "external_id": paper["pmid"], "title": paper["title"] or "",
         "source_url": paper["url"], "published_at": paper["pub_date"] or ""}
        for paper in pubmed_summaries(ids)
    ]


def _clinicaltrials(ids: list[str]) -> list[dict]:
    from research_matcher import trials_by_id

    return [
        {"source": "clinicaltrials.gov", "external_id": trial["nct_id"], "title": trial["title"] or "",
         "source_url": trial["url"], "published_at": trial["start_date"] or ""}
        for trial in trials_by_id(ids)
    ]


def _clinvar(ids: list[str]) -> list[dict]:
    from public_variant_sources import clinvar_records_by_id

    return clinvar_records_by_id(ids)


# store key -> (public source name, fetch-by-ID function)
FETCHERS = {
    "pubmed": ("pubmed", _pubmed),
    "clinicaltrials": ("clinicaltrials.gov", _clinicaltrials),
    "clinvar": ("clinvar", _clinvar),
}


@dataclass
class Group:
    """One topic's stored IDs from one source of past records."""
    label: str
    query: str
    ids: dict[str, list[str]] = field(default_factory=dict)   # FETCHERS key -> stored IDs


def bare_id(stored: str) -> str:
    """'PMID:123' -> '123', 'ClinVar:456' -> '456', 'NCT01' -> 'NCT01'."""
    return stored.split(":", 1)[1] if ":" in stored else stored


def classify_id(stored: str) -> str | None:
    """FETCHERS key for an unlabelled stored ID, or None if unrecognized."""
    if re.fullmatch(r"NCT\d{8}", stored):
        return "clinicaltrials"
    prefix = stored.split(":", 1)[0].lower() if ":" in stored else ""
    return {"pmid": "pubmed", "clinvar": "clinvar"}.get(prefix)


def _query(item: dict) -> str:
    return " ".join(part for part in (item.get("condition"), item.get("biomarker")) if part)


def groups_from_store(store: dict, origin: str) -> list[Group]:
    """Topics of a growing-research-agent store (research_store.json format)."""
    return [
        Group(f"{origin} {key}", _query(topic), {k: list(v) for k, v in topic.get("all_ids", {}).items()})
        for key, topic in store.get("topics", {}).items()
    ]


def groups_from_corpus(corpus: list, origin: str) -> list[Group]:
    """Past live-run corpus blocks, grouped by topic, IDs sorted by source."""
    by_topic: dict[str, Group] = {}
    for block in corpus:
        if not isinstance(block, dict):
            continue
        query = _query(block)
        group = by_topic.setdefault(query, Group(f"{origin} {query}", query))
        for stored in block.get("new_ids", []):
            group.ids.setdefault(classify_id(str(stored)) or "unrecognized", []).append(str(stored))
    return list(by_topic.values())


def live_store_snapshots(db_path: Path) -> list[tuple[str, str, object]]:
    """(stream, key, value) of the research-store and corpus snapshots in
    live_store.db, read-only; [] if the database does not exist."""
    if not db_path.exists():
        return []
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT stream, key, data FROM snapshots WHERE stream IN ('research', 'corpus') ORDER BY stream, key"
        ).fetchall()
    finally:
        connection.close()
    return [(stream, key, json.loads(data)) for stream, key, data in rows]


def live_store_groups(db_path: Path) -> list[Group]:
    """Research stores and the research corpus mirrored in live_store.db."""
    groups = []
    for stream, key, value in live_store_snapshots(db_path):
        if stream == "research" and isinstance(value, dict) and "topics" in value:
            groups.extend(groups_from_store(value, f"live_store {key}"))
        elif stream == "corpus" and isinstance(value, list):
            groups.extend(groups_from_corpus(value, f"live_store {key}"))
    return groups


def plan(groups: list[Group], already_published: set[tuple[str, str]]) -> tuple[list[dict], list[str]]:
    """Fetch and rank every group's records. Returns (batches, notes): each
    batch is a research ranking of at most 20 not-yet-published records from
    one source for one topic."""
    seen = set(already_published)
    batches, notes = [], []
    for group in groups:
        terms = group.query.lower().split()
        for store_key, stored_ids in group.ids.items():
            ids = list(dict.fromkeys(stored_ids))
            if not ids:
                continue
            if store_key not in FETCHERS:
                notes.append(f"{group.label}: {len(ids)} {store_key} IDs skipped (no fetch-by-ID support)")
                continue
            source, fetch = FETCHERS[store_key]
            # PubMed and trial IDs are the published external IDs, so known
            # ones are skipped before fetching; ClinVar publishes accessions,
            # which are only known after fetching.
            pending = ids if store_key == "clinvar" else [i for i in ids if (source, bare_id(i)) not in seen]
            records = []
            try:
                for start in range(0, len(pending), 100):
                    records.extend(fetch([bare_id(i) for i in pending[start:start + 100]]))
            except (OSError, ValueError, RuntimeError) as error:   # URLError is an OSError
                notes.append(f"{group.label}: {source} fetch failed ({error}); nothing from it is published")
                continue
            fresh = [r for r in records if r.get("title") and (source, str(r["external_id"])) not in seen]
            seen.update((source, str(r["external_id"])) for r in fresh)
            notes.append(
                f"{group.label}: {source} {len(ids)} IDs, {len(ids) - len(pending)} already published or planned, "
                f"{len(records)} fetched, {len(fresh)} to publish"
            )
            for start in range(0, len(fresh), MAX_PUBLISHED_RECORDS):
                chunk = fresh[start:start + MAX_PUBLISHED_RECORDS]
                batches.append(research_analysis.run({
                    "schema": research_analysis.INPUT_SCHEMA,
                    "query": group.query,
                    "terms": terms,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "records": [{**r, "classification": "public"} for r in chunk],
                }))
    return batches, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--store", type=Path, action="append",
                        help="research-store JSON (repeatable; default: research_store.json)")
    parser.add_argument("--live-store", type=Path, default=ROOT / "live_store.db",
                        help="live_store.db with research-store and corpus snapshots")
    parser.add_argument("--no-live-store", action="store_true", help="ignore live_store.db")
    parser.add_argument("--ledgers", type=Path, default=ROOT / "autonomous",
                        help="directory holding node-*/research_ledger_node-*.json")
    parser.add_argument("--outbox", type=Path, default=DEFAULT_OUTBOX)
    parser.add_argument("--confirm-publication", action="store_true",
                        help="queue the events for the permanent node chain")
    args = parser.parse_args(argv)

    groups = []
    for store_path in args.store or [ROOT / "research_store.json"]:
        groups.extend(groups_from_store(json.loads(store_path.read_text(encoding="utf-8")), store_path.name))
    if not args.no_live_store:
        groups.extend(live_store_groups(args.live_store))
    batches, notes = plan(groups, published_record_keys(str(args.ledgers)))
    for note in notes:
        print(note)
    events = [create_public_research_records_event(batch, confirm_publication=True)
              for batch in batches if batch["ranked"]]
    total = sum(event["record_count"] for event in events)
    print(f"{total} records in {len(events)} event(s)")
    for event in events:
        print(f"  {event['sources'][0]}: {event['record_count']} records, "
              f"first {event['records'][0]['external_id']}  {event['records'][0]['title'][:70]}")
    if not args.confirm_publication:
        print("Dry run: nothing queued. Add --confirm-publication to publish these permanently.")
        return 0
    queue = ResearchProvenanceQueue(args.outbox)
    for event in events:
        queue.enqueue(event)
    print(f"Queued {len(events)} event(s) in {args.outbox} for node-0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
