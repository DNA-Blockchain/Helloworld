"""The research data pipeline report: what was mined from public sources and how it moved through the system.

It follows the data through each stage, with the figures for each:

  ingestion   public sources -> the research catalog (records per source, abstracts, publication years,
              new records in the period), the research agent's topics and per-source status, public searches
  corpus      catalog -> search-by-meaning corpus (documents, vectors per embedding model, coverage, cutoffs)
  model       training items kept and rejected per task, the latest evaluation run, the merged model file,
              research summaries written, hosted-model questions and answers shared for training
  chain       corpus -> shared research chain (entries per kind, records per source, Bitcoin timestamp proofs,
              corrections and notes, datasets, the outbox waiting to publish), every node's copy checked
  nodes       blocks, verification, peers, audits and research-ledger growth per node
  integrity   the latest integrity report: checks per status, problems, its fingerprint

    python rabbit.py pipeline-report               # the last 24 hours, as text
    python rabbit.py pipeline-report --hours 168 --json

It only reads: no store is changed or created and nothing leaves this PC. The daily report includes it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path

from .tools import Paths, _load, _statuses

SCHEMA = "rabbitsoft-pipeline-report.v1"
NOS_LORA = Path("ollama") / "nos-lora"


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds")


def _epoch(text: str) -> float:
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _year(text: str) -> str:
    return text[:4] if str(text)[:4].isdigit() else ""


def _jsonl(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


def build(paths: Paths | None = None, now: float | None = None, since: float | None = None) -> dict:
    """The report as data (schemas/rabbitsoftware-pipeline-report-v1.schema.json). The period, by default
    the last 24 hours, applies to the "new" and activity figures; the rest are totals."""
    paths = paths or Paths()
    now = time.time() if now is None else now
    since = now - 86400 if since is None else since
    activity = _activity(paths, since)
    return {"schema": SCHEMA, "created_at": _iso(now), "period": {"start": _iso(since), "end": _iso(now)},
            "ingestion": _ingestion(paths, since, activity), "corpus": _corpus(paths),
            "model": _model(paths, activity), "chain": _chain(paths, since), "nodes": _nodes(paths, now),
            "integrity": _integrity(paths)}


# -- stages ---------------------------------------------------------------------------------------------
def _activity(paths: Paths, since: float) -> Counter:
    """Pipeline actions from the activity log in the period, summed."""
    totals: Counter = Counter()
    try:
        from audit_trail import AuditTrail

        entries = AuditTrail(str(paths.audit)).read_all() if paths.audit.exists() else []
    except (OSError, ValueError, ImportError):
        entries = []
    for e in entries:
        if e.get("timestamp", 0) < since:
            continue
        action, details = e.get("action"), e.get("details") or {}
        if action == "public_search":
            totals["public_searches"] += 1
            totals["records_returned"] += int(details.get("records", 0))
        elif action == "abstracts_fetched":
            totals["abstracts_requested"] += int(details.get("asked", 0))
            totals["abstracts_filled"] += int(details.get("filled", 0))
        elif action == "model_server_used":
            totals["hosted_questions"] += 1
            totals["hosted_fallbacks"] += bool(details.get("fell_back"))
        elif action == "training_answer_shared":
            totals["training_answers_shared"] += 1
    return totals


def _catalog(paths: Paths, since: float) -> dict | None:
    if not paths.catalog.exists():
        return None
    connection = sqlite3.connect(f"file:{paths.catalog.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT source, abstract != '', published_at, retrieved_at, classification "
                                  "FROM research_records").fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    sources: dict[str, dict] = {}
    for source, has_abstract, published, retrieved, _ in rows:
        s = sources.setdefault(source, {"records": 0, "with_abstract": 0, "new_in_period": 0, "years": []})
        s["records"] += 1
        s["with_abstract"] += bool(has_abstract)
        s["new_in_period"] += retrieved >= since
        if year := _year(published):
            s["years"].append(year)
    for s in sources.values():
        years = sorted(s.pop("years"))
        s["published"] = f"{years[0]}-{years[-1]}" if years and years[0] != years[-1] else (years[0] if years else "")
    return {"records": len(rows), "with_abstract": sum(bool(r[1]) for r in rows),
            "new_in_period": sum(r[3] >= since for r in rows),
            "last_retrieved": _iso(max(r[3] for r in rows)) if rows else None,
            "classifications": dict(Counter(r[4] for r in rows)), "sources": dict(sorted(sources.items()))}


def _agent(paths: Paths) -> dict | None:
    store = _load(paths.research_store)
    if not isinstance(store, dict):
        return None
    topics = list((store.get("topics") or {}).values())
    ids: Counter = Counter()
    status: dict[str, Counter] = {}
    for t in topics:
        for source, found in (t.get("all_ids") or {}).items():
            ids[source] += len(found)
        for source, s in (t.get("source_status") or {}).items():
            status.setdefault(source, Counter())[s.get("status", "unknown")] += 1
    return {"topics": len(topics), "queued": len(store.get("queue") or []), "ids_by_source": dict(ids),
            "new_ids_last_run": sum(len(t.get("new_ids_last_run") or []) for t in topics),
            "source_status": {s: dict(c) for s, c in sorted(status.items())},
            "last_checked": _iso(max(t.get("last_checked", 0) for t in topics)) if topics else None}


def _ingestion(paths: Paths, since: float, activity: Counter) -> dict:
    return {"catalog": _catalog(paths, since), "agent": _agent(paths),
            "public_searches": activity["public_searches"], "records_returned": activity["records_returned"],
            "abstracts_requested": activity["abstracts_requested"], "abstracts_filled": activity["abstracts_filled"]}


def _corpus(paths: Paths) -> dict | None:
    from corpus_vector_store import MIN_SIMILARITY, _text_sha

    state = _load(paths.corpus)
    if not isinstance(state, dict):
        return None
    docs, vectors = state.get("documents") or [], state.get("vectors") or {}
    current: Counter = Counter()
    for d in docs:
        v = vectors.get(d["id"])
        if v and v.get("text_sha256") == _text_sha(d["text"]):
            current[v["model"]] += 1
    complete = [m for m, n in current.items() if n == len(docs)] if docs else []
    in_catalog = None
    if paths.catalog.exists():
        connection = sqlite3.connect(f"file:{paths.catalog.as_posix()}?mode=ro", uri=True)
        try:
            in_catalog = {f"{s}:{e}" for s, e in connection.execute(
                "SELECT source, external_id FROM research_records WHERE classification = 'public'")}
        except sqlite3.Error:
            pass
        finally:
            connection.close()
    doc_ids = {d["id"] for d in docs}
    return {"documents": len(docs), "with_abstract": sum(bool(d.get("abstract")) for d in docs),
            "mean_characters": round(sum(len(d["text"]) for d in docs) / len(docs)) if docs else 0,
            "current_vectors": dict(current), "method": complete[0] if complete else "tfidf",
            "catalog_records_missing": len(in_catalog - doc_ids) if in_catalog is not None else None,
            "cutoffs": dict(MIN_SIMILARITY)}


def _model(paths: Paths, activity: Counter) -> dict:
    lora = paths.root / NOS_LORA
    kept, rejected = _jsonl(lora / "kept.jsonl"), _jsonl(lora / "rejected.jsonl")
    tasks = sorted({r.get("task", "?") for r in kept + rejected})
    training = {t: {"kept": sum(r.get("task") == t for r in kept), "rejected": sum(r.get("task") == t for r in rejected)}
                for t in tasks}
    runs = sorted((paths.autonomous / "ai-tuning").glob("run-*.json"))
    run = _load(runs[-1]) if runs else None
    evaluation = None
    if isinstance(run, dict):
        evaluation = {"created_at": run.get("created_at"), "results": [
            {k: r.get(k) for k in ("variant", "task", "model", "passed", "cases", "seconds")}
            for r in run.get("results") or []]}
    gguf = next(iter(sorted(lora.glob("*.gguf"))), None)
    summaries = _load(paths.autonomous / "summaries" / "summaries.json")
    return {"training": training, "evaluation": evaluation,
            "model_file": {"name": gguf.name, "bytes": gguf.stat().st_size} if gguf else None,
            "research_summaries": len((summaries or {}).get("summaries") or {}) if isinstance(summaries, dict) else 0,
            "hosted_questions": activity["hosted_questions"], "hosted_fallbacks": activity["hosted_fallbacks"],
            "training_answers_shared": activity["training_answers_shared"]}


def _chain(paths: Paths, since: float) -> dict | None:
    from . import chain_view

    try:
        data = chain_view.collect(paths)
    except (OSError, ValueError, KeyError):
        return None
    events = data["events"]
    created = [_epoch(chain_view._payload(e).get("created_at", "")) for e in events]
    proofs = Counter("none" if e.get("timestamp_proof") is None else
                     "pending" if e.get("timestamp_proof") == "pending" else "complete" for e in events)
    records = data["records"]
    outbox = paths.autonomous / "research-outbox"
    return {"entries": len(events), "new_in_period": sum(c >= since for c in created),
            "by_kind": dict(Counter(e["kind"] for e in events).most_common()),
            "newest": _iso(max(created)) if created and max(created) else None,
            "copies": {str(n): {"entries": v.get("entries"), "ok": bool(v.get("ledger_ok"))}
                       for n, v in sorted(data["nodes"].items(), key=lambda kv: str(kv[0]))},
            "records": len(records), "records_by_source": dict(Counter(r["source"] for r in records).most_common()),
            "distinct_queries": len({r.get("query") for r in records if r.get("query")}),
            "corrected_records": sum(bool(r.get("correction")) for r in records),
            "notes": sum(len(e.get("notes") or []) for e in events), "timestamp_proofs": dict(proofs),
            "datasets": len(data["datasets"]),
            "dataset_bases": sum(int(d.get("total_bases") or 0) for d in data["datasets"]),
            "outbox_pending": len(list(outbox.glob("*.json"))) if outbox.exists() else 0,
            "outbox_rejected": len(list((outbox / "rejected").glob("*"))) if (outbox / "rejected").exists() else 0}


def _nodes(paths: Paths, now: float) -> dict:
    from .tools import STALE_SECONDS

    totals = _load(paths.autonomous / "period_totals.json") or {}
    stats: dict[str, Counter] = {}
    for snap in (totals.get("snapshots") or {}).values():
        c = stats.setdefault(f"node-{snap.get('node_id')}", Counter())
        for k in ("blocks_mined", "blocks_verified", "blocks_failed_verification", "research_ledger_added"):
            c[k] += (snap.get("stats") or {}).get(k, 0)
    nodes = {}
    for name, s in _statuses(paths):
        audits = (s.get("work") or {}).get("recent_audits") or []
        nodes[name] = {"blocks": s.get("chain_blocks", 0), "chain_ok": bool(s.get("chain_ok")),
                       "peers": len(s.get("connected_peers") or []),
                       "running": now - s.get("updated_at", 0) <= STALE_SECONDS,
                       "research_ledger": (s.get("research_ledger") or {}).get("entries", 0),
                       "audits": len(audits), "audit_problems": sum(not a.get("ok") for a in audits),
                       "since_supervisor_period": dict(stats.get(name, {}))}
    return nodes


def _integrity(paths: Paths) -> dict | None:
    reports = sorted((paths.autonomous / "integrity").glob("integrity-*.json"))
    if not reports:
        return None
    raw = reports[-1].read_bytes()
    try:
        report = json.loads(raw)
    except ValueError:
        return None
    checks = report.get("checks") or []
    return {"created_at": report.get("created_at"), "ok": bool(report.get("ok")),
            "checks": dict(Counter(c.get("status") for c in checks)),
            "problems": [c.get("name") for c in checks if c.get("status") == "problem"],
            "fingerprint": hashlib.sha256(raw).hexdigest(), "file": reports[-1].name}


# -- text -----------------------------------------------------------------------------------------------
def _n(count: int, word: str, plural: str = "") -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def render(report: dict) -> list[str]:
    """The report as Markdown lines, for the chat, the terminal and the daily report."""
    period = report["period"]
    lines = [f"Research data pipeline, {period['start'][:16].replace('T', ' ')} to "
             f"{period['end'][:16].replace('T', ' ')} UTC (\"new\" figures are for this period).", ""]
    ing, cat, agent = report["ingestion"], report["ingestion"]["catalog"], report["ingestion"]["agent"]
    lines += ["### 1. Ingestion: public sources to the research catalog", ""]
    if cat:
        lines.append(f"Catalog: {cat['records']} records ({cat['new_in_period']} new), abstracts for "
                     f"{cat['with_abstract']} ({_pct(cat['with_abstract'], cat['records'])}); last retrieval "
                     f"{(cat['last_retrieved'] or '-')[:16].replace('T', ' ')}.")
        lines += ["", "| Source | Records | New | With abstract | Published |", "|---|---|---|---|---|"]
        lines += [f"| {name} | {s['records']} | {s['new_in_period']} | {s['with_abstract']} "
                  f"({_pct(s['with_abstract'], s['records'])}) | {s['published'] or '-'} |"
                  for name, s in cat["sources"].items()]
        lines.append("")
    else:
        lines.append("No research catalog on this PC yet.")
    if agent:
        found = ", ".join(f"{s} {n}" for s, n in sorted(agent["ids_by_source"].items(), key=lambda kv: -kv[1]))
        status = "; ".join(f"{s}: " + ", ".join(f"{k} {v}" for k, v in c.items())
                           for s, c in agent["source_status"].items())
        lines.append(f"Research agent: {_n(agent['topics'], 'topic')} checked, {agent['queued']} queued; IDs found by "
                     f"source: {found or 'none'}; {agent['new_ids_last_run']} new on the last run. "
                     f"Source status per topic: {status or '-'}.")
    lines.append(f"Activity: {_n(ing['public_searches'], 'public search', 'public searches')} returning {ing['records_returned']} records; "
                 f"{ing['abstracts_filled']} of {ing['abstracts_requested']} requested abstracts filled.")

    corpus = report["corpus"]
    lines += ["", "### 2. Corpus: catalog to search by meaning", ""]
    if corpus:
        vectors = ", ".join(f"{m} {n}" for m, n in corpus["current_vectors"].items()) or "none"
        missing = corpus["catalog_records_missing"]
        lines.append(f"{corpus['documents']} documents ({corpus['with_abstract']} with abstracts, mean "
                     f"{corpus['mean_characters']} characters); current vectors: {vectors}; search method: "
                     f"{corpus['method']}" + (f"; {missing} catalog records not yet indexed" if missing else "")
                     + ". Cutoffs: " + ", ".join(f"{k} cosine >= {v}" for k, v in corpus["cutoffs"].items()) + ".")
    else:
        lines.append("No corpus yet (it's built on the first research question).")

    model = report["model"]
    lines += ["", "### 3. Model: training data, evaluation and use", ""]
    if model["training"]:
        parts = [f"{t} {c['kept']} kept / {c['rejected']} rejected ({_pct(c['kept'], c['kept'] + c['rejected'])} "
                 f"accepted)" for t, c in model["training"].items()]
        lines.append("LoRA training items (distilled, then filtered by fact checks): " + "; ".join(parts) + ".")
    if model["model_file"]:
        lines.append(f"Model file: {model['model_file']['name']}, {model['model_file']['bytes'] / 1e9:.2f} GB.")
    if model["evaluation"]:
        results = "; ".join(f"{r['model']} {r['task']} {r['passed']}/{r['cases']} ({r['seconds']:.0f} s)"
                            for r in model["evaluation"]["results"] if r.get("cases"))
        lines.append(f"Latest evaluation ({str(model['evaluation']['created_at'])[:10]}): {results}.")
    lines.append(f"Research summaries written: {model['research_summaries']}. In the period: "
                 f"{_n(model['hosted_questions'], 'question')} to the hosted model ({model['hosted_fallbacks']} fell back "
                 f"to this PC), {_n(model['training_answers_shared'], 'answer')} shared for training.")

    chain = report["chain"]
    lines += ["", "### 4. Chain: published research", ""]
    if chain and chain["entries"]:
        copies = ", ".join(f"node {n}: {c['entries']} {'ok' if c['ok'] else 'FAILED'}" for n, c in chain["copies"].items())
        kinds = ", ".join(f"{k} {n}" for k, n in chain["by_kind"].items())
        sources = ", ".join(f"{s} {n}" for s, n in chain["records_by_source"].items())
        proofs = ", ".join(f"{k} {n}" for k, n in chain["timestamp_proofs"].items())
        lines += [f"{chain['entries']} entries ({chain['new_in_period']} new; newest "
                  f"{(chain['newest'] or '-')[:16].replace('T', ' ')}). Copies: {copies}.",
                  f"By kind: {kinds}.",
                  f"Published records: {chain['records']} from {chain['distinct_queries']} queries ({sources}); "
                  f"{chain['corrected_records']} corrected, {chain['notes']} notes.",
                  f"Datasets: {chain['datasets']} ({chain['dataset_bases']:,} bases). Bitcoin timestamp proofs: "
                  f"{proofs}. Outbox: {chain['outbox_pending']} waiting to publish, {chain['outbox_rejected']} rejected."]
    else:
        lines.append("Nothing published on the shared chain yet.")

    lines += ["", "### 5. Nodes", ""]
    if report["nodes"]:
        lines += ["| Node | Running | Blocks | Own chain | Peers | Research ledger | Audits (problems) "
                  "| Mined / verified this period |", "|---|---|---|---|---|---|---|---|"]
        for name, n in report["nodes"].items():
            p = n["since_supervisor_period"]
            lines.append(f"| {name} | {'yes' if n['running'] else 'no'} | {n['blocks']} | "
                         f"{'intact' if n['chain_ok'] else 'FAILED'} | {n['peers']} | {n['research_ledger']} | "
                         f"{n['audits']} ({n['audit_problems']}) | {p.get('blocks_mined', 0)} / "
                         f"{p.get('blocks_verified', 0)} |")
    else:
        lines.append("No node status on this PC.")

    integrity = report["integrity"]
    lines += ["", "### 6. Integrity", ""]
    if integrity:
        counts = ", ".join(f"{k} {v}" for k, v in integrity["checks"].items())
        lines.append(f"Latest report {integrity['created_at']}: {'all true' if integrity['ok'] else 'PROBLEMS'} "
                     f"({counts})" + (f"; problems: {', '.join(integrity['problems'])}" if integrity["problems"] else "")
                     + f". Fingerprint `{integrity['fingerprint'][:16]}…` ({integrity['file']}).")
    else:
        lines.append("No integrity report yet. Say \"check integrity\" to run one.")
    return lines


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="The research data pipeline report (read-only).")
    p.add_argument("--hours", type=float, default=24, help="the period for the \"new\" figures (default 24)")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    a = p.parse_args(argv)
    now = time.time()
    report = build(now=now, since=now - a.hours * 3600)
    print(json.dumps(report, indent=2) if a.json else "\n".join(render(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
