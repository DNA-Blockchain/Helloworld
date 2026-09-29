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
research_queue.py
=================
New research for the node chain, driven by the growing research agent's
own queue: the related topics it discovered (research_store.json "queue",
plus the queues of the research stores mirrored in live_store.db, such as
the CRISPR suite's). For each queued topic this fetches public records
(research_fetch.py), ranks them (research_analysis.py on the host, or with
--kernel inside the Network OS via `cargo run -- research`), and queues a
public_research_records event for node-0.

Topics already published and records already on the chain are skipped, so
it can run repeatedly. Without --confirm-publication it is a dry run.

Usage:
    python research_queue.py                                 # dry run, host ranking
    python research_queue.py --limit 5 --confirm-publication
    python research_queue.py --kernel --confirm-publication  # rank each topic in the OS kernel
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import research_analysis
import research_fetch
from research_backfill import live_store_snapshots
from research_ledger import published_queries, published_record_keys
from research_provenance import ResearchProvenanceQueue, create_public_research_records_event
from research_publish import DEFAULT_OUTBOX

ROOT = Path(__file__).resolve().parent
# The OS README's Windows build setting (the GNU host needs no MSVC linker).
WINDOWS_TOOLCHAIN = "nightly-2026-09-27-x86_64-pc-windows-gnu"


def queued_topics(store_paths: list[Path], live_store: Path | None) -> list[tuple[str, str]]:
    """(condition, biomarker) pairs from every store's queue, de-duplicated
    case-insensitively, in first-seen order."""
    queues = []
    for path in store_paths:
        queues.append(json.loads(path.read_text(encoding="utf-8")).get("queue", []))
    if live_store is not None:
        queues.extend(value.get("queue", []) for stream, _, value in live_store_snapshots(live_store)
                      if stream == "research" and isinstance(value, dict))
    topics, seen = [], set()
    for queue in queues:
        for item in queue:
            if not (isinstance(item, list) and len(item) == 2 and all(isinstance(p, str) for p in item)):
                continue
            key = (item[0].strip().lower(), item[1].strip().lower())
            if key not in seen and item[0].strip():
                seen.add(key)
                topics.append((item[0].strip(), item[1].strip()))
    return topics


def rank_in_kernel(request: dict, timeout: int = 600) -> dict:
    """Rank one topic inside the Network OS: stage the request on the QEMU
    data disk, run the boot check, and read the kernel's ranking back."""
    with tempfile.TemporaryDirectory() as scratch:
        source, ranked = Path(scratch) / "RESEARCH.JSON", Path(scratch) / "RANKED.OUT"
        source.write_text(json.dumps(request), encoding="utf-8")
        env = dict(os.environ)
        if os.name == "nt":
            env.setdefault("RUSTUP_TOOLCHAIN", WINDOWS_TOOLCHAIN)
            extra = [str(Path.home() / ".cargo" / "bin"), r"C:\Program Files\qemu"]
            env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
        result = subprocess.run(
            ["cargo", "run", "--locked", "--", "research", str(source), str(ranked)],
            cwd=ROOT / "os", env=env, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0 or not ranked.exists():
            tail = " | ".join((result.stdout + result.stderr).strip().splitlines()[-3:])
            raise RuntimeError(f"kernel ranking failed: {tail}")
        return json.loads(ranked.read_text(encoding="utf-8"))


def plan(topics, *, sources, max_results, kernel, already_published, already_queried, limit=None):
    """Returns (events, notes). Each event ranks one topic's not-yet-published
    records; topics whose query is already on the chain are skipped."""
    seen = set(already_published)
    events, notes, processed = [], [], 0
    for condition, biomarker in topics:
        query = f"{condition} {biomarker}".strip()
        if query.lower() in already_queried:
            notes.append(f"{query}: already published, skipped")
            continue
        if limit is not None and processed >= limit:
            break
        processed += 1
        terms = list(dict.fromkeys((condition + " " + biomarker).lower().split()))
        try:
            request = research_fetch.fetch(query, terms, sources, max_results)
        except (OSError, ValueError, RuntimeError) as error:
            notes.append(f"{query}: fetch failed ({error})")
            continue
        fetched = len(request["records"])
        request["records"] = [
            r for r in request["records"] if (r["source"], r["external_id"]) not in seen
        ]
        if not request["records"]:
            notes.append(f"{query}: {fetched} records fetched, none new")
            continue
        try:
            ranking = rank_in_kernel(request) if kernel else research_analysis.run(request)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            notes.append(f"{query}: ranking failed ({error})")
            continue
        if not ranking["ranked"]:
            notes.append(f"{query}: nothing ranked")
            continue
        event = create_public_research_records_event(ranking, confirm_publication=True)
        seen.update((r["source"], r["external_id"]) for r in event["records"])
        events.append(event)
        notes.append(f"{query}: {fetched} fetched, {len(request['records'])} new, "
                     f"{event['record_count']} published ranked {'in the kernel' if kernel else 'on the host'}")
    return events, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--store", type=Path, action="append",
                        help="research-store JSON with a queue (repeatable; default: research_store.json)")
    parser.add_argument("--live-store", type=Path, default=ROOT / "live_store.db")
    parser.add_argument("--no-live-store", action="store_true")
    parser.add_argument("--source", action="append", choices=research_analysis.PUBLIC_SOURCES,
                        help="public source to query (repeatable; default: pubmed, europe_pmc, clinicaltrials.gov)")
    parser.add_argument("--max-results", type=int, default=5, help="records per source per topic")
    parser.add_argument("--limit", type=int, help="process at most this many new topics")
    parser.add_argument("--kernel", action="store_true", help="rank each topic inside the Network OS (QEMU)")
    parser.add_argument("--ledgers", type=Path, default=ROOT / "autonomous")
    parser.add_argument("--outbox", type=Path, default=DEFAULT_OUTBOX)
    parser.add_argument("--confirm-publication", action="store_true",
                        help="queue the events for the permanent node chain")
    args = parser.parse_args(argv)

    topics = queued_topics(args.store or [ROOT / "research_store.json"],
                           None if args.no_live_store else args.live_store)
    print(f"{len(topics)} queued topic(s)")
    events, notes = plan(
        topics,
        sources=args.source or list(research_fetch.DEFAULT_SOURCES),
        max_results=args.max_results,
        kernel=args.kernel,
        already_published=published_record_keys(str(args.ledgers)),
        already_queried=published_queries(str(args.ledgers)),
        limit=args.limit,
    )
    for note in notes:
        print(note)
    print(f"{sum(e['record_count'] for e in events)} records in {len(events)} event(s)")
    if not args.confirm_publication:
        print("Dry run: nothing queued. Add --confirm-publication to publish these permanently.")
        return 0
    queue = ResearchProvenanceQueue(args.outbox)
    for event in events:
        queue.enqueue(event)
    print(f"Queued {len(events)} event(s) for node-0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
