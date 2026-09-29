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
Publishes the records the growing research agent collected in the past
(research_store.json) to the node chain. The store keeps only IDs, so this
re-fetches each record's title, date and link by ID (PubMed, ClinicalTrials.gov,
ClinVar), ranks each source's records with research_analysis.py, and queues
one public_research_records event per 20 records for node-0 to mine.

Records already in any node's research ledger are skipped, so running it
again only publishes what is new. Without --confirm-publication it is a dry
run that shows what would be published.

Usage:
    python research_backfill.py                          # dry run
    python research_backfill.py --confirm-publication
"""

from __future__ import annotations

import argparse
import json
import sys
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


# research_store.json key -> (public source name, fetch-by-ID function)
FETCHERS = {
    "pubmed": ("pubmed", _pubmed),
    "clinicaltrials": ("clinicaltrials.gov", _clinicaltrials),
    "clinvar": ("clinvar", _clinvar),
}


def bare_id(stored: str) -> str:
    """'PMID:123' -> '123', 'ClinVar:456' -> '456', 'NCT01' -> 'NCT01'."""
    return stored.split(":", 1)[1] if ":" in stored else stored


def plan(store: dict, already_published: set[tuple[str, str]]) -> tuple[list[dict], list[str]]:
    """Fetch and rank every stored topic's records. Returns (batches, notes):
    each batch is a research ranking of at most 20 not-yet-published records
    from one source for one topic."""
    batches, notes = [], []
    for key, topic in store.get("topics", {}).items():
        query = " ".join(part for part in (topic.get("condition"), topic.get("biomarker")) if part)
        terms = query.lower().split()
        for store_key, ids in topic.get("all_ids", {}).items():
            if not ids:
                continue
            if store_key not in FETCHERS:
                notes.append(f"{key}: {len(ids)} {store_key} IDs skipped (no fetch-by-ID support for that source)")
                continue
            source, fetch = FETCHERS[store_key]
            records = []
            try:
                for start in range(0, len(ids), 100):
                    records.extend(fetch([bare_id(i) for i in ids[start:start + 100]]))
            except (OSError, ValueError) as error:   # URLError is an OSError
                notes.append(f"{key}: {source} fetch failed ({error}); nothing from it is published")
                continue
            found = len(records)
            records = [
                r for r in records
                if r.get("title") and (source, str(r["external_id"])) not in already_published
            ]
            notes.append(
                f"{key}: {source} {found} of {len(ids)} IDs found, "
                f"{found - len(records)} already published or untitled, {len(records)} to publish"
            )
            for start in range(0, len(records), MAX_PUBLISHED_RECORDS):
                chunk = records[start:start + MAX_PUBLISHED_RECORDS]
                batches.append(research_analysis.run({
                    "schema": research_analysis.INPUT_SCHEMA,
                    "query": query,
                    "terms": terms,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "records": [{**r, "classification": "public"} for r in chunk],
                }))
    return batches, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--store", type=Path, default=ROOT / "research_store.json")
    parser.add_argument("--ledgers", type=Path, default=ROOT / "autonomous",
                        help="directory holding node-*/research_ledger_node-*.json")
    parser.add_argument("--outbox", type=Path, default=DEFAULT_OUTBOX)
    parser.add_argument("--confirm-publication", action="store_true",
                        help="queue the events for the permanent node chain")
    args = parser.parse_args(argv)

    store = json.loads(args.store.read_text(encoding="utf-8"))
    batches, notes = plan(store, published_record_keys(str(args.ledgers)))
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
    print(f"Queued {len(events)} event(s) in {args.outbox}; node-0 mines one per heartbeat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
