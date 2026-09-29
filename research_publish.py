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
