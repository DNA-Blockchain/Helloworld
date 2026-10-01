#!/usr/bin/env python3
"""
research_publish.py
===================
Queues the public bibliographic records from a research ranking (a
RANKED.OUT from research_analysis.py or `cargo run -- research`) for the
node chain. node-0, started by node_supervisor.py with
--provenance-queue autonomous/research-outbox, mines each queued event
into a signed block and gossips it to its peers.

The chain is append-only and replicated, so nothing is queued without
--confirm-publication; without it this prints what would be published.
Only source, ID, title, URL, date and record hash are published, never
abstracts (their reuse rights are unknown) and never private data.

Usage:
    python research_publish.py RANKED.OUT                        # dry run
    python research_publish.py RANKED.OUT --confirm-publication
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from research_provenance import ResearchProvenanceQueue, create_public_research_records_event

DEFAULT_OUTBOX = Path(__file__).resolve().parent / "autonomous" / "research-outbox"


def current_time_anchor() -> dict | None:
    """The current Bitcoin block, recorded in the events created in this run
    to prove they are no older than it. None (with a note) if no public
    explorer is reachable; events are valid without an anchor."""
    try:
        from external_chain_bridge import fetch_bitcoin_anchor

        anchor = fetch_bitcoin_anchor()
    except Exception as error:
        print(f"note: no Bitcoin time anchor ({error}); publishing without one")
        return None
    print(f"time anchor: created after Bitcoin block {anchor['height']} ({anchor['block_hash'][:16]}...)")
    return anchor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("ranking", type=Path, help="research-ranking.v1 JSON (RANKED.OUT)")
    parser.add_argument("--outbox", type=Path, default=DEFAULT_OUTBOX, help="provenance queue directory")
    parser.add_argument("--confirm-publication", action="store_true",
                        help="actually queue the records for the permanent node chain")
    args = parser.parse_args(argv)

    ranking = json.loads(args.ranking.read_text(encoding="utf-8"))
    try:
        # Build with confirmation so the event is fully validated even in a
        # dry run; it is only queued when the flag is given.
        event = create_public_research_records_event(
            ranking, confirm_publication=True, time_anchor=current_time_anchor())
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"{event['record_count']} public records from {', '.join(event['sources'])} "
          f"(ranking {event['ranking_sha256'][:16]}...):")
    for record in event["records"]:
        print(f"  {record['source']}:{record['external_id']}  {record['title'][:90]}")
    if not args.confirm_publication:
        print("Dry run: nothing queued. Add --confirm-publication to publish these permanently.")
        return 0
    path = ResearchProvenanceQueue(args.outbox).enqueue(event)
    print(f"Queued event {event['event_id']} at {path}; node-0 will mine it into the chain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
