#!/usr/bin/env python3
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

import auto_approve

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
import research_publish
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


# The kernel ranks at most this many requests per boot (task_bundle.rs).
KERNEL_BATCH = 50


def kernel_input(request: dict) -> bytes:
    """UTF-8 JSON, as research_fetch.py writes it. A request holding a lone
    surrogate (which UTF-8 cannot carry) falls back to \\u escapes, which the
    kernel's research task decodes to the same text."""
    try:
        return json.dumps(request, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(request).encode("ascii")


def rank_batch_in_kernel(requests: list[dict], timeout: int = 900) -> list[dict | None]:
    """Rank every request inside the Network OS in one boot: stage them on the
    QEMU data disk, run the boot check, and read each ranking back. None
    marks a request the kernel's research task rejected."""
    with tempfile.TemporaryDirectory() as scratch:
        inputs, outputs = Path(scratch) / "in", Path(scratch) / "out"
        inputs.mkdir()
        for index, request in enumerate(requests):
            (inputs / f"{index:02}.json").write_bytes(kernel_input(request))
        env = dict(os.environ)
        if os.name == "nt":
            env.setdefault("RUSTUP_TOOLCHAIN", WINDOWS_TOOLCHAIN)
            extra = [str(Path.home() / ".cargo" / "bin"), r"C:\Program Files\qemu"]
            env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
        result = subprocess.run(
            ["cargo", "run", "--locked", "--", "research-batch", str(inputs), str(outputs)],
            cwd=ROOT / "os", env=env, capture_output=True, text=True, timeout=timeout,
        )
        rankings = [
            json.loads(path.read_text(encoding="utf-8")) if (path := outputs / f"{index:02}.json").exists() else None
            for index in range(len(requests))
        ]
        if result.returncode != 0 and not any(rankings):
            tail = " | ".join((result.stdout + result.stderr).strip().splitlines()[-3:])
            raise RuntimeError(f"kernel ranking failed: {tail}")
        return rankings


def plan(topics, *, sources, max_results, kernel, already_published, already_queried, limit=None,
         time_anchor=None):
    """Returns (events, notes). Each event ranks one topic's not-yet-published
    records; topics whose query is already on the chain are skipped. Every
    topic is fetched first, then all are ranked together (with `kernel`, in
    one OS boot per 50 topics). A record is claimed by the first topic that
    fetches it, so no record is published twice in a run."""
    seen = set(already_published)
    pending, notes, processed = [], [], 0
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
        seen.update((r["source"], r["external_id"]) for r in request["records"])
        pending.append((query, request, fetched))

    rankings: list[dict | None] = []
    if kernel:
        for start in range(0, len(pending), KERNEL_BATCH):
            chunk = [request for _, request, _ in pending[start:start + KERNEL_BATCH]]
            try:
                rankings.extend(rank_batch_in_kernel(chunk))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                notes.append(f"kernel batch of {len(chunk)} failed ({error})")
                rankings.extend([None] * len(chunk))
    else:
        rankings = [research_analysis.run(request) for _, request, _ in pending]

    events = []
    for (query, request, fetched), ranking in zip(pending, rankings):
        if ranking is None:
            notes.append(f"{query}: ranking failed (rejected by the kernel)")
            continue
        if not ranking["ranked"]:
            notes.append(f"{query}: nothing ranked")
            continue
        event = create_public_research_records_event(ranking, confirm_publication=True, time_anchor=time_anchor)
        events.append(event)
        notes.append(f"{query}: {fetched} fetched, {len(request['records'])} new, "
                     f"{event['record_count']} published ranked {'in the kernel' if kernel else 'on the host'}")
    return events, notes


class SharedTopicResearch:
    """Work-sharing runner (work_sharing.py): the node assigned a research
    round publishes one queued topic itself. Topics already on the chain are
    skipped, and the starting topic rotates with the round, so a topic that
    yields nothing new does not block the others. Constructing it is the
    confirmation to publish (run_node_cli.py --publish-research-topics)."""

    wants_task = True
    attempts_per_round = 3

    def __init__(self, ledgers: Path, store_paths: list[Path], live_store: Path | None,
                 sources: list[str] | None = None, max_results: int = 5):
        self.ledgers = ledgers
        self.store_paths = store_paths
        self.live_store = live_store
        self.sources = sources or list(research_fetch.DEFAULT_SOURCES)
        self.max_results = max_results

    def __call__(self, task) -> dict:
        already_queried = published_queries(str(self.ledgers))
        pending = [(c, b) for c, b in queued_topics(
            [p for p in self.store_paths if p.exists()],
            self.live_store if self.live_store and self.live_store.exists() else None)
            if f"{c} {b}".strip().lower() not in already_queried]
        if not pending:
            return {"source": "research_queue", "status": "queue empty"}
        start = task.round_no % len(pending)
        rotated = pending[start:] + pending[:start]
        notes = []
        for topic in rotated[:self.attempts_per_round]:
            events, topic_notes = plan(
                [topic], sources=self.sources, max_results=self.max_results, kernel=False,
                already_published=published_record_keys(str(self.ledgers)),
                already_queried=already_queried, time_anchor=research_publish.current_time_anchor(),
            )
            notes.extend(topic_notes)
            if events:
                return {"source": "research_queue", "research_event": events[0], "notes": notes}
        return {"source": "research_queue", "status": "nothing new", "notes": notes}


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
    parser.add_argument("--kernel", action="store_true",
                        help="rank the topics inside the Network OS (QEMU), one boot per 50 topics")
    parser.add_argument("--ledgers", type=Path, default=ROOT / "autonomous")
    parser.add_argument("--outbox", type=Path, default=DEFAULT_OUTBOX)
    parser.add_argument("--confirm-publication", action="store_true",
                        help="queue the events for the permanent node chain")
    args = parser.parse_args(argv)
    if auto_approve.enabled():
        args.confirm_publication = True

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
        time_anchor=research_publish.current_time_anchor(),
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
