"""Integrity check: are the chains, records, data and code of this OS still true?

Each check belongs to a role and only reads:

  records and data   every node's own chain, the shared research ledgers (and whether every entry still
                     meets today's rules), the activity log's hash chain, the Maxwell chain, and local
                     dataset files against their fingerprints on the chain
  code enforcement   code files against the saved code fingerprint (project_identifier.py), uncommitted
                     changes, the tools the OS needs (rabbitsoft/toolchain.py), the test suite and every
                     component's self-test

The report is saved on this PC (autonomous/integrity/) as JSON and as a page to read; its SHA-256 is its
fingerprint. Only that fingerprint can go on the shared chain: when asked, or daily if it's turned on for
this PC (off by default). node_supervisor.py runs this every day with its report. RabbitSoftware.inc runs
it in the background ("check integrity"), or run it directly:

    python -m rabbitsoft.integrity              # everything, about 3-4 minutes
    python -m rabbitsoft.integrity --no-tests   # chains, records, data and code fingerprints only
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .tools import Paths

OK, PROBLEM, SKIPPED = "ok", "problem", "skipped"


@dataclass
class Check:
    role: str
    name: str
    status: str
    lines: list[str] = field(default_factory=list)


def node_chains(paths: Paths) -> Check:
    from chain_store import ChainStore

    lines, broken = [], []
    for d in paths.node_dirs():
        path = d / f"chain_{d.name}.json"
        if not path.exists():
            continue
        ok, message = ChainStore(store_path=str(path)).verify_chain()
        lines.append(f"{d.name}: {message}")
        if not ok:
            broken.append(d.name)
    if not lines:
        return Check("records and data", "Node chains", SKIPPED, ["No node chains on this PC."])
    return Check("records and data", "Node chains", PROBLEM if broken else OK, lines)


def research_ledgers(paths: Paths) -> Check:
    from research_ledger import load_all_ledgers
    from research_provenance import validate_public_provenance

    ledgers = load_all_ledgers(str(paths.autonomous))
    if not ledgers:
        return Check("records and data", "Shared research chain", SKIPPED, ["No research ledgers on this PC."])
    lines, problem = [], False
    held: dict[str, set[int]] = {}
    for node_id, ledger in sorted(ledgers.items()):
        ok, message = ledger.verify()
        problem |= not ok
        invalid = 0
        for entry in ledger.entries():
            held.setdefault(entry["event_id"], set()).add(node_id)
            event = entry["block"].get("research_provenance")
            if isinstance(event, dict):
                try:
                    validate_public_provenance(event)
                except ValueError:
                    invalid += 1
        problem |= invalid > 0
        lines.append(f"node-{node_id}: {message}" + (f"; {invalid} entries no longer meet the rules" if invalid else ""))
    partial = [e for e, nodes in held.items() if len(nodes) < len(ledgers)]
    lines.append(f"{len(held)} entries; " + (f"{len(partial)} not yet copied to every node (normal for a few "
                                               "minutes after publishing)." if partial else "every node holds every entry."))
    return Check("records and data", "Shared research chain", PROBLEM if problem else OK, lines)


def activity_log(paths: Paths) -> Check:
    from audit_trail import AuditTrail

    if not paths.audit.exists():
        return Check("records and data", "Activity log", SKIPPED, ["No activity log on this PC."])
    trail = AuditTrail(str(paths.audit))
    intact, problems = trail.verify_chain()
    lines = [f"{len(trail.read_all())} entries; hash chain {'intact' if intact else 'BROKEN'}."]
    lines += [f"- {p}" for p in problems[:5]] if not intact else []
    return Check("records and data", "Activity log", OK if intact else PROBLEM, lines)


MAXWELL_FILES = ("maxwell_chain*.json", "maxwell_blockchain*.json")


def relay_export(blocks: list[dict]) -> tuple[bool, str]:
    """Checks a chain exported from the Maxwell web app (blocks with "mined_by" and "created_date"). Its hash
    formula isn't in this project, so hashes can't be recomputed; what can be checked is that every block
    links to a parent one height below it, back to a single genesis block. The export keeps every branch
    miners started, so forks and the same record mined more than once are reported, not treated as damage."""
    by_hash = {b["hash"]: b for b in blocks}
    genesis = [b for b in blocks if b["block_number"] == 0]
    orphans = [b for b in blocks if b["block_number"] > 0 and (
        b["previous_hash"] not in by_hash or by_hash[b["previous_hash"]]["block_number"] != b["block_number"] - 1)]
    ok = len(genesis) == 1 and not orphans and len(by_hash) == len(blocks)
    if not ok:
        return False, (f"{len(blocks)} blocks; {len(orphans)} don't link to a parent one height below, "
                       f"{len(genesis)} genesis blocks, {len(blocks) - len(by_hash)} repeated hashes.")
    parents = {b["previous_hash"] for b in blocks}
    tips = [b for b in blocks if b["hash"] not in parents]
    records = {b["data"] if isinstance(b["data"], str) else json.dumps(b["data"], sort_keys=True)
               for b in blocks if b["block_number"] > 0}
    return True, (f"{len(blocks)} blocks, every one links back to the genesis block. {len(tips)} branches; the "
                  f"longest is {max(b['block_number'] for b in tips) + 1} blocks. {len(records)} different records "
                  f"(the rest are the same record mined again on another branch). Hashes weren't recomputed: this "
                  "chain was made by the Maxwell web app and its hash formula isn't in this project.")


def maxwell_chains(paths: Paths) -> Check:
    from maxwell_chain_agent import MaxwellChainAgent

    found = sorted({Path(p) for name in MAXWELL_FILES for pattern in (name, f"autonomous/**/{name}")
                    for p in glob.glob(str(paths.root / pattern), recursive=True)})
    if not found:
        return Check("records and data", "Maxwell chain", SKIPPED, ["No Maxwell chain file on this PC."])
    lines, broken = [], False
    for path in found:
        name = path.relative_to(paths.root)
        try:
            blocks = json.loads(path.read_text(encoding="utf-8"))
            if blocks and "mined_by" in blocks[0] and "timestamp" not in blocks[0]:
                ok, message = relay_export(blocks)
            else:
                agent = MaxwellChainAgent([], store_path=str(path))
                ok = agent.validate_chain()
                message = (f"{len(agent.chain)} blocks, "
                           f"{'every hash and link checks out' if ok else 'a block or link does NOT check out'}.")
        except (ValueError, KeyError, TypeError) as e:
            ok, message = False, f"can't be read as a Maxwell chain ({type(e).__name__}: {e})."
        broken |= not ok
        lines.append(f"{name}: {message}")
    return Check("records and data", "Maxwell chain", PROBLEM if broken else OK, lines)


def datasets(paths: Paths) -> Check:
    import research_viewer

    published = [d for d in research_viewer.collect(str(paths.autonomous))["datasets"] if d.get("accession")]
    if not published:
        return Check("records and data", "Dataset files", SKIPPED, ["No datasets published on the chain."])
    lines, mismatched, missing = [], [], 0
    for d in published:
        local = paths.autonomous / "datasets" / f"{d['accession']}.fasta"
        if not local.exists():
            missing += 1
            continue
        if hashlib.sha256(local.read_bytes()).hexdigest() == d["dataset_sha256"]:
            lines.append(f"{d['accession']}: matches its fingerprint on the chain.")
        else:
            mismatched.append(d["accession"])
            lines.append(f"{d['accession']}: does NOT match its fingerprint on the chain.")
    if missing:
        lines.append(f"{missing} published dataset{'s are' if missing != 1 else ' is'} not stored on this PC "
                     "(the chain holds fingerprints, not files).")
    return Check("records and data", "Dataset files", PROBLEM if mismatched else OK, lines)


def code_fingerprints(paths: Paths) -> Check:
    from project_identifier import compute_project_identifier, verify_against_manifest

    manifest = paths.root / "project_manifest.json"
    lines, status = [], OK
    current = compute_project_identifier(str(paths.root))
    lines.append(f"Code fingerprint now: {current['project_id'][:16]}... over {current['file_count']} core files.")
    if current.get("missing_files"):
        status = PROBLEM
        lines.append(f"Missing core files: {', '.join(current['missing_files'])}.")
    if manifest.exists():
        result = verify_against_manifest(str(manifest), str(paths.root))
        changed = result.get("changed_files") or result.get("changed") or []
        lines.append("No core file changed since the saved fingerprint." if not changed else
                     f"{len(changed)} core files changed since the saved fingerprint: {', '.join(changed[:8])}"
                     + ("..." if len(changed) > 8 else "") + ". Expected after updates; save a new one with "
                                                          "python project_identifier.py once they're reviewed.")
    else:
        lines.append("No saved code fingerprint yet (python project_identifier.py saves one).")
    try:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=paths.root, capture_output=True, text=True,
                               timeout=60).stdout.splitlines()
        lines.append("No uncommitted code changes." if not dirty else
                     f"{len(dirty)} uncommitted change{'s' if len(dirty) != 1 else ''} in the working copy.")
    except (OSError, subprocess.SubprocessError):
        lines.append("git isn't available, so uncommitted changes weren't checked.")
    return Check("code enforcement", "Code fingerprints", status, lines)


def test_suite(paths: Paths, timeout: float = 1200) -> Check:
    try:
        run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=paths.root,
                             capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return Check("code enforcement", "Test suite", PROBLEM, [f"Didn't finish within {timeout / 60:.0f} minutes."])
    summary = next((l.strip("= ") for l in reversed(run.stdout.splitlines()) if re.search(r"\d+ (passed|failed)", l)),
                   f"exit code {run.returncode}")
    failed = [l.split(" - ")[0].removeprefix("FAILED ") for l in run.stdout.splitlines() if l.startswith("FAILED ")]
    return Check("code enforcement", "Test suite", OK if run.returncode == 0 else PROBLEM,
                 [summary + "."] + [f"- {f}" for f in failed[:10]])


def self_tests(paths: Paths) -> Check:
    out = paths.rabbit / "integrity-self-tests.json"
    paths.rabbit.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "run_self_tests.py", "--skip-live-data", "--json-out", str(out)], cwd=paths.root,
                   capture_output=True, text=True, timeout=900)
    try:
        results = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Check("code enforcement", "Component self-tests", PROBLEM, ["They didn't produce results."])
    c = results.get("counts", {})
    failed = [r["file"] for r in results.get("results", []) if r.get("status") == "FAIL"]
    return Check("code enforcement", "Component self-tests", PROBLEM if failed else OK,
                 [f"{c.get('PASS', 0)} passed, {c.get('FAIL', 0)} failed, {c.get('SKIP', 0)} skipped (sites outside "
                  "this PC)."] + [f"- {f}" for f in failed])


def tools(paths: Paths, survey=None) -> Check:
    """The tools this OS needs. Informational: a missing tool isn't damage, so this never fails."""
    from . import toolchain

    rows = (survey or toolchain.survey)()
    have = sum(r["here"] for r in rows)
    lines = [f"{have} of {len(rows)} tools on this computer"
             + (f", {sum(bool(r['wsl']) for r in rows)} of {len(rows)} in WSL." if rows and rows[0]["wsl"] is not None
                else ".")]
    lines += [l for l in toolchain.describe(rows) if l.startswith(("To add", "winget"))]
    return Check("code enforcement", "Tools", OK, lines)


def run_all(paths: Paths, run_tests: bool = True) -> dict:
    checks = [node_chains, research_ledgers, activity_log, maxwell_chains, datasets, code_fingerprints, tools]
    if run_tests:
        checks += [self_tests, test_suite]
    results = []
    for check in checks:
        try:
            results.append(check(paths))
        except Exception as error:        # one broken check must not hide the others' results
            results.append(Check("records and data" if check in checks[:5] else "code enforcement",
                                 check.__name__.replace("_", " ").capitalize(), PROBLEM,
                                 [f"The check itself failed: {type(error).__name__}: {error}"]))
    return {"schema": "rabbitsoft-integrity.v1", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ok": all(c.status != PROBLEM for c in results), "checks": [asdict(c) for c in results]}


def summary_line(report: dict) -> str:
    checks = report["checks"]
    problems = [c["name"] for c in checks if c["status"] == PROBLEM]
    counts = {s: sum(c["status"] == s for c in checks) for s in (OK, PROBLEM, SKIPPED)}
    text = f"{counts[OK]} checks passed, {counts[PROBLEM]} found problems, {counts[SKIPPED]} had nothing to check."
    return text + (f" Problems: {', '.join(problems)}." if problems else "")


def write_report(report: dict, folder: Path) -> tuple[Path, Path, str]:
    """The report as JSON and as a readable page; returns both paths and the JSON's SHA-256."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = report["created_at"].replace(":", "").replace("-", "")[:15]
    raw = json.dumps(report, indent=1, ensure_ascii=False).encode("utf-8")
    json_path, md_path = folder / f"integrity-{stamp}.json", folder / f"integrity-{stamp}.md"
    json_path.write_bytes(raw)
    fingerprint = hashlib.sha256(raw).hexdigest()
    lines = [f"# Integrity report {report['created_at']}", "", f"**{'All true' if report['ok'] else 'Problems found'}.** "
             f"{summary_line(report)}", "", f"Fingerprint (SHA-256 of {json_path.name}): `{fingerprint}`", ""]
    for role in ("records and data", "code enforcement"):
        lines += [f"## {role.capitalize()}", ""]
        for c in (c for c in report["checks"] if c["role"] == role):
            lines.append(f"- **{c['name']}: {c['status']}.**")
            lines += [f"  - {line.lstrip('- ')}" for line in c["lines"]]
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path, fingerprint


# -- the report's fingerprint on the chain (only ever the SHA-256; the report stays on this PC) ----------
def _settings_file(paths: Paths) -> Path:
    return paths.rabbit / "settings.json"


def publishing_daily(paths: Paths) -> bool:
    try:
        return bool(json.loads(_settings_file(paths).read_text(encoding="utf-8")).get("integrity_publish_daily"))
    except (OSError, ValueError, AttributeError):
        return False


def set_publishing_daily(paths: Paths, on: bool) -> None:
    path = _settings_file(paths)
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    settings["integrity_publish_daily"] = on
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=1), encoding="utf-8")


def latest_report(paths: Paths) -> Path | None:
    reports = sorted((paths.autonomous / "integrity").glob("integrity-*.json"))
    return reports[-1] if reports else None


def publish_fingerprint(paths: Paths, report_json: Path) -> str:
    """Queues the report's SHA-256 for the shared chain (node-0 mines it). Returns the event ID."""
    from audit_trail import AuditTrail
    from research_provenance import ResearchProvenanceQueue, create_public_data_hash_event

    fingerprint = hashlib.sha256(report_json.read_bytes()).hexdigest()
    event = create_public_data_hash_event(data_sha256=fingerprint, data_kind="integrity_report",
                                          classification="public", confirm_hash_publication=True)
    ResearchProvenanceQueue(paths.autonomous / "research-outbox").enqueue(event)
    try:
        AuditTrail(str(paths.audit)).log("rabbitsoft", "integrity_fingerprint_queued", "local",
                                         {"event_id": event["event_id"], "report": report_json.name,
                                          "sha256": fingerprint})
    except (OSError, ValueError):
        pass                 # queued either way; a missing log line shouldn't undo that
    return event["event_id"]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    p.add_argument("--no-tests", action="store_true", help="skip the test suite and self-tests")
    p.add_argument("--json-out", type=Path, help="also copy the report to this file")
    p.add_argument("--daily", action="store_true",
                   help="the daily run: also publish the fingerprint if that's turned on for this PC")
    args = p.parse_args(argv)
    paths = Paths()
    started = time.time()
    report = run_all(paths, run_tests=not args.no_tests)
    json_path, md_path, fingerprint = write_report(report, paths.autonomous / "integrity")
    if args.json_out:
        args.json_out.write_bytes(json_path.read_bytes())
    print(summary_line(report))
    print(f"Report: {md_path} (fingerprint {fingerprint[:16]}..., {time.time() - started:.0f} s)")
    if args.daily and publishing_daily(paths):
        print(f"Fingerprint queued for the chain (entry {publish_fingerprint(paths, json_path)[:8]}).")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
