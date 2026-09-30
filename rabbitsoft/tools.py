"""Read-only tools: each reads what the OS already records and returns short, plain sentences.

None of these change anything or send anything off this PC.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STALE_SECONDS = 300          # a node that hasn't written its status for 5 minutes has probably stopped


@dataclass
class Paths:
    """Where the OS keeps its records. Tests point this at a temporary folder."""
    root: Path = ROOT
    autonomous: Path = field(default_factory=lambda: ROOT / "autonomous")
    audit: Path = field(default_factory=lambda: ROOT / "system_audit.jsonl")
    research_store: Path = field(default_factory=lambda: ROOT / "research_store.json")
    catalog: Path = field(default_factory=lambda: ROOT / "dna_shell_data" / "research_catalog.sqlite3")

    def node_dirs(self) -> list[Path]:
        return sorted((p for p in self.autonomous.glob("node-*") if p.is_dir()),
                      key=lambda p: int(p.name.split("-")[1]) if p.name.split("-")[1].isdigit() else 0)


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ago(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} seconds ago"
    if seconds < 5400:
        return f"{seconds / 60:.0f} minutes ago"
    if seconds < 172800:
        return f"{seconds / 3600:.0f} hours ago"
    return f"{seconds / 86400:.0f} days ago"


def _statuses(paths: Paths) -> list[tuple[str, dict]]:
    return [(d.name, s) for d in paths.node_dirs() if isinstance(s := _load(d / "status.json"), dict)]


def nodes(paths: Paths, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    statuses = _statuses(paths)
    if not statuses:
        return ["No node status found on this PC. Start the nodes with: python node_supervisor.py"]
    stale = [name for name, s in statuses if now - s.get("updated_at", 0) > STALE_SECONDS]
    lines = [f"{len(statuses)} nodes. " + ("All are running." if not stale else
             f"{len(stale)} may be stopped ({', '.join(stale)}): no update for over 5 minutes.")]
    for name, s in statuses:
        peers = s.get("connected_peers") or []
        lines.append(
            f"{name}: {s.get('chain_blocks', 0)} blocks, chain {'intact' if s.get('chain_ok') else 'FAILED CHECK'}, "
            f"connected to {len(peers)} peer{'s' if len(peers) != 1 else ''}, "
            f"updated {_ago(now - s.get('updated_at', 0))}.")
    if stale:
        lines.append("To check the supervisor that keeps them running: python node_supervisor.py --status")
    return lines


def chain(paths: Paths) -> list[str]:
    statuses = _statuses(paths)
    if not statuses:
        return ["No node status found, so there are no chain checks to report."]
    lines = []
    broken = [name for name, s in statuses if not s.get("chain_ok")]
    lines.append("Every node's own chain checks out." if not broken else
                 f"Chain check FAILED on {', '.join(broken)}.")
    audits = {(a.get("round"), a.get("by"), a.get("target")): a
              for _, s in statuses for a in (s.get("work") or {}).get("recent_audits", [])}
    if audits:
        problems = [a for a in audits.values() if not a.get("ok") or a.get("problem_count")]
        blocks = max(a.get("blocks_checked", 0) for a in audits.values())
        lines.append(f"Recent cross-checks: {len(audits)} audits, {len(problems)} found problems. "
                     f"In each audit one node re-checks up to {blocks} blocks of another node's chain.")
    ledgers = [s.get("research_ledger") for _, s in statuses if s.get("research_ledger")]
    if ledgers:
        lines.append(f"Research ledger: {max(l.get('entries', 0) for l in ledgers)} entries, "
                     f"{'intact' if all(l.get('ok') for l in ledgers) else 'FAILED CHECK'} on every node.")
    return lines


def swarm(paths: Paths) -> list[str]:
    rounds = {}
    for _, s in _statuses(paths):
        for r in ((s.get("work") or {}).get("swarm") or {}).get("recent", []):
            rounds[r.get("round")] = r
    if not rounds:
        return ["The nodes on this PC haven't recorded swarm rounds (they run without --swarm). "
                "The swarm runs in the Alpine VMs: python3 linux/swarm.py.",
                "I can explain one of the 8 synthetic test subjects instead: say \"explain synthetic 3\"."]
    recent = [rounds[k] for k in sorted(rounds)][-5:]
    accepted = sum(r.get("status") == "ACCEPTED" for r in rounds.values())
    lines = [f"{len(rounds)} recent swarm rounds, {accepted} accepted (two nodes computed the same result)."]
    lines += [f"Round {r.get('round')}: {r.get('status')} {r.get('subject')}" for r in recent]
    lines.append("Say \"explain\" and a subject, for example \"explain synthetic 3\", for a plain explanation.")
    return lines


def ledger(paths: Paths) -> list[str]:
    # Each node's file holds the credits it gave the others (one per block of theirs it verified), so a
    # node's balance is what every other node's file credits it with.
    balances: dict[str, float] = {}
    for d in paths.node_dirs():
        entries = _load(d / f"tokens_{d.name}.json")
        if isinstance(entries, list):
            balances.setdefault(d.name, 0)
            for e in entries:
                balances[e.get("node_id", "?")] = balances.get(e.get("node_id", "?"), 0) + e.get("amount", 0)
    if not balances:
        return ["No token ledger found on this PC."]
    lines = [f"{name}: {amount:g} credits" for name, amount in sorted(balances.items(), key=lambda kv: -kv[1])]
    return lines + ["A node earns a credit each time another node verifies a block it mined. "
                    "Credits are a local score, not a currency."]


def activity(paths: Paths, limit: int = 5) -> list[str]:
    try:
        from audit_trail import AuditTrail

        trail = AuditTrail(str(paths.audit))
        entries = trail.read_all()
        intact, _ = trail.verify_chain()
    except (OSError, ValueError, ImportError):
        return ["No activity log found on this PC."]
    if not entries:
        return ["The activity log is empty."]
    lines = [f"{len(entries)} logged actions; the log's own hash chain is "
             f"{'intact' if intact else 'BROKEN (it has been edited)'}. Most recent:"]
    for e in entries[-limit:][::-1]:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.get("timestamp", 0)))
        lines.append(f"{when}  {e.get('module')}: {str(e.get('action', '')).replace('_', ' ')}")
    return lines


def agents(paths: Paths) -> list[str]:
    store = _load(paths.research_store)
    if not isinstance(store, dict):
        return ["No research agent data found. Start the agent with: python run_agent.py"]
    topics = store.get("topics") or {}
    queue = store.get("queue") or []
    lines = [f"The research agent has looked into {len(topics)} topic{'s' if len(topics) != 1 else ''} "
             f"and has {len(queue)} more queued."]
    for t in list(topics.values())[:5]:
        found = sum(len(ids) for ids in (t.get("all_ids") or {}).values())
        checked = time.strftime("%Y-%m-%d", time.localtime(t.get("last_checked", 0)))
        lines.append(f"{t.get('condition')} + {t.get('biomarker')}: {found} records found, last checked {checked}.")
    if queue:
        lines.append("Next up: " + "; ".join(" + ".join(map(str, q)) for q in queue[:3]) + ".")
    return lines


def report(paths: Paths) -> list[str]:
    reports = sorted((paths.autonomous / "reports").glob("*.md"))
    if not reports:
        return ["No daily report yet. The supervisor writes one each morning."]
    text = reports[-1].read_text(encoding="utf-8")
    overall = next((l.strip("* ") for l in text.splitlines() if l.startswith("**Overall")), "")
    period = next((l for l in text.splitlines() if l.startswith("Period:")), "")
    lines = [f"Latest daily report: {reports[-1].stem}. {overall}".strip(), period] if period else \
        [f"Latest daily report: {reports[-1].stem}. {overall}".strip()]
    return lines + [f"Full report: {reports[-1]}"]


TOOLS = {"nodes": nodes, "chain": chain, "swarm": swarm, "ledger": ledger, "activity": activity,
         "agents": agents, "report": report}
