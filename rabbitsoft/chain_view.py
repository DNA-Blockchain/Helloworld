"""Reading the shared research chain: what's on it, finding entries, and the full text of any entry.

Everything published on the chain is public by design, so all of it can be shown. The chain itself
never changes here; this only reads the node ledgers (research_viewer.collect merges them, with
corrections applied).
"""
from __future__ import annotations

import json
import re

from . import tools

KIND_NAMES = {
    "public_research_records": "research record batches",
    "public_research_provenance": "research answer fingerprints",      # hashes of answers/summaries, no text
    "public_research_correction": "corrections",
    "public_variant_classification": "variant classifications",
    "public_crispr_relevance": "CRISPR relevance notes",
    "public_dataset_record": "datasets",
    "public_dataset_summary": "dataset summaries",
    "public_sequence_record": "sequences",
    "public_model_run_record": "model runs",
    "public_data_hash": "file fingerprints",
}
VIEWER = "To browse everything in a page: python research_viewer.py (http://127.0.0.1:8791)."


def collect(paths: tools.Paths) -> dict:
    import research_viewer

    return research_viewer.collect(str(paths.autonomous))


def _payload(event: dict) -> dict:
    block = event["block"]
    return block.get("research_provenance") or block.get("public_dataset_summary") or {}


def _nodes(ids) -> str:
    ids = sorted(ids)
    return "node " + str(ids[0]) if len(ids) == 1 else "nodes " + ", ".join(map(str, ids))


def summary(data: dict) -> list[str]:
    events, nodes = data["events"], data["nodes"]
    if not events:
        return ["Nothing has been published on the shared chain yet."]
    intact = all(n["ledger_ok"] for n in nodes.values())
    counts: dict[str, int] = {}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    kinds = ", ".join(f"{n} {KIND_NAMES.get(k, k)}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    newest = max(events, key=lambda e: _payload(e).get("created_at", ""))
    lines = [f"The shared research chain holds {len(events)} entries, copied across {len(nodes)} nodes; "
             f"every copy {'checks out' if intact else 'does NOT check out'}.",
             f"By kind: {kinds}.",
             f"Inside them: {len(data['records'])} published research records and {len(data['datasets'])} datasets.",
             f"Newest entry: {KIND_NAMES.get(newest['kind'], newest['kind'])}, "
             f"{_payload(newest).get('created_at', '')[:10]}.",
             "Say \"find\" and some words to search it, for example \"find BRCA1 on the chain\".", VIEWER]
    return lines


def find(data: dict, text: str, limit: int = 5) -> tuple[list[str], list[dict]]:
    """Published records (and other entries) matching every word; returns lines and the matched events,
    numbered in the same order, for "show entry N"."""
    terms = [t for t in re.findall(r"[\w-]+", text.lower()) if len(t) > 2 and t not in {"the", "and", "for"}]
    if not terms:
        return ["Tell me what to look for, for example \"find BRCA1 on the chain\"."], []
    matches, events_by_id = [], {e["event_id"]: e for e in data["events"]}
    for r in data["records"]:
        haystack = f"{r['title']} {r['source']} {r['external_id']} {r['query']}".lower()
        if all(t in haystack for t in terms):
            matches.append(("record", r, events_by_id.get(r["event_id"])))
    for e in data["events"]:
        if e["kind"] in ("public_research_records", "public_research_provenance"):
            continue                       # records are listed one by one above; fingerprints have no text
        if all(t in json.dumps(_payload(e)).lower() for t in terms):
            matches.append(("entry", None, e))
    if not matches:
        return [f"Nothing on the chain matches \"{' '.join(terms)}\"."], []
    lines = [f"{len(matches)} match{'es' if len(matches) != 1 else ''} on the chain"
             + (f"; the first {limit}:" if len(matches) > limit else ":")]
    shown = []
    for n, (what, record, event) in enumerate(matches[:limit], start=1):
        shown.append(event)
        if what == "record":
            line = (f"{n}. {record['title']} ({record['source']} {record['external_id']}, published "
                    f"{record['published_at'][:10]}, held by {_nodes(record['replicas'])}). {record['source_url']}")
            if record.get("correction"):
                c = record["correction"]
                line += f" Corrected {c['corrected_at'][:10]} ({c['reason']}); first published as \"{c['published_title']}\"."
        else:
            p = _payload(event)
            label = p.get("title") or p.get("accession") or p.get("gene") or event["event_id"]
            line = (f"{n}. {KIND_NAMES.get(event['kind'], event['kind'])}: {label} "
                    f"(published {p.get('created_at', '')[:10]}, held by {_nodes(event['replicas'])}).")
        lines.append(line)
    lines.append("Say \"show entry\" and a number for everything in it.")
    return lines, shown


def _flatten(value, prefix: str = "") -> list[str]:
    """Every field as "name: value" lines; long lists are counted and the first few shown."""
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            lines += _flatten(item, f"{prefix}{key}." if isinstance(item, (dict, list)) else f"{prefix}{key}")
    elif isinstance(value, list):
        name = prefix.rstrip(".")
        lines.append(f"{name}: {len(value)} item{'s' if len(value) != 1 else ''}")
        for i, item in enumerate(value[:5], start=1):
            lines += _flatten(item, f"{name}[{i}].")
        if len(value) > 5:
            lines.append(f"{name}: ... {len(value) - 5} more (see research_viewer.py)")
    else:
        lines.append(f"{prefix.rstrip('.')}: {value if value not in ('', None) else '(blank)'}")
    return lines


def entry(data: dict, event: dict) -> list[str]:
    p = _payload(event)
    lines = [f"Chain entry {event['event_id']}: {KIND_NAMES.get(event['kind'], event['kind'])}.",
             f"Published by node {event['origin']} as its block {event['origin_index']}, fingerprint "
             f"{event['block_hash_hex']}. Copies on {_nodes(event['replicas'])}.",
             "Everything in it:"]
    lines += ["  " + line for line in _flatten(p)]
    if event["kind"] == "public_dataset_record":
        dataset = next((d for d in data["datasets"] if d.get("event_id") == event["event_id"]), {})
        lines.append("The dataset's file is on this PC." if dataset.get("local_copy") else
                     "The dataset's file isn't on this PC; the chain holds its fingerprint, not the file.")
    return lines


def find_event(data: dict, reference: str) -> dict | None:
    """An entry by its ID, or by the first characters of its ID (at least 6)."""
    ref = reference.lower()
    if len(ref) < 6:
        return None
    found = [e for e in data["events"] if e["event_id"].startswith(ref)]
    return found[0] if len(found) == 1 else None
