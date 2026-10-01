#!/usr/bin/env python3
"""
backup_health.py — is the backup system actually working? Checks it, and
once a week proves it by restoring.

A backup nobody has restored is a hope, not a backup. So besides checking
that backups keep happening, this restores the newest one every week into
a throwaway folder -- decrypting it, checking every file against the
manifest's SHA-256, running SQLite's integrity check on every database and
parsing every JSON file -- and, if the S3 copy is configured, downloads the
newest off-site backup to a throwaway folder and decrypts that too. The
throwaway folders are deleted afterwards; the result is appended to
<dest>/test_restores.jsonl.

ALERTS (same "[ALERT] ..." style as chain_monitor_agent.py)
-------------------------------------------------------------
- no backups at all, or the newest is older than --max-age-hours (36)
- the newest backup wasn't verified when it was made
- the passphrase can't be loaded (tonight's backup would fail)
- off-site configured, but a backup older than the max age still isn't
  confirmed in S3, or the last off-site sync reported an error
- no successful test restore within the last 8 days, or the latest failed
- less than 1 GB free where the backups live
- (Windows) the nightly task is missing, or its last run failed

`backup.py run` calls run_scheduled() after every backup (test restore
when due, then checks, then a desktop notification if anything is wrong),
and node_supervisor.py adds these alerts to its daily report.

Usage
-----
    python backup_health.py check                 # exit 1 if any alert
    python backup_health.py test-restore          # now, regardless of schedule
    python backup_health.py check --json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import backup

TASK_NAME = "NetworkOSNightlyBackup"
MAX_AGE_HOURS = 36.0
TEST_RESTORE_EVERY_DAYS = 7
TEST_RESTORE_STALE_DAYS = 8
MIN_FREE_BYTES = 1 << 30
LOG_NAME = "test_restores.jsonl"
LAST_SYNC_NAME = "offsite_last_sync.json"


def _now() -> float:
    return time.time()


def _ts(iso: str) -> float:
    return dt.datetime.fromisoformat(iso).timestamp()


# ---- test restore ----
def _check_restored_tree(root: Path) -> dict:
    dbs = jsons = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if backup._is_sqlite(path):
            con = sqlite3.connect(path)
            try:
                result = con.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                con.close()
            if result != "ok":
                raise ValueError(f"SQLite integrity check failed for {path.relative_to(root)}: {result}")
            dbs += 1
        elif path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
            jsons += 1
        elif path.suffix == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
            jsons += 1
    return {"sqlite_ok": dbs, "json_ok": jsons}


def test_restore(bs: backup.BackupSet, passphrase: str, include_offsite: bool = True) -> dict:
    """Restores the newest local backup (and the newest S3 copy, if configured)
    into throwaway folders, checks everything, deletes them, logs the result."""
    result = {"at": _now(), "ok": False}
    try:
        with tempfile.TemporaryDirectory(prefix="restore-test-", dir=bs.dest) as scratch:
            restored = bs.restore("latest", Path(scratch) / "local", passphrase)
            result.update(vault_id=restored["vault_id"], files=restored["file_count"],
                          **_check_restored_tree(Path(scratch) / "local"))
            if include_offsite:
                result["offsite"] = _test_offsite(bs, passphrase, Path(scratch) / "offsite")
        result["ok"] = result.get("offsite", {}).get("ok", True)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"[:400]
    with (bs.dest / LOG_NAME).open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, sort_keys=True) + "\n")
    return result


def _test_offsite(bs: backup.BackupSet, passphrase: str, scratch: Path) -> dict:
    import offsite_s3
    config = offsite_s3.S3Offsite.load_config(bs.dest)
    if not config:
        return {"ok": True, "skipped": "off-site not configured"}
    confirmed = offsite_s3.S3Offsite(bs.dest, runner=offsite_s3.cli_runner).confirmed()
    if not confirmed:
        return {"ok": False, "error": "nothing confirmed off-site yet"}
    newest = max(confirmed.values(), key=lambda r: r["confirmed_at"])["vault_id"]
    remote = offsite_s3.S3Offsite(scratch, config=config, runner=offsite_s3.cli_runner)
    try:
        remote.pull([newest])
        backup.BackupSet(scratch).vault.inspect(newest, passphrase=passphrase)   # full decrypt + hash check
    except Exception as e:
        return {"ok": False, "vault_id": newest, "error": f"{type(e).__name__}: {e}"[:300]}
    return {"ok": True, "vault_id": newest}


def test_restore_history(dest: Path) -> list[dict]:
    path = Path(dest) / LOG_NAME
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_restore_due(dest: Path, now: float | None = None) -> bool:
    now = _now() if now is None else now
    ok = [r for r in test_restore_history(dest) if r.get("ok")]
    return not ok or now - ok[-1]["at"] > TEST_RESTORE_EVERY_DAYS * 86400


# ---- checks ----
def _scheduled_task_problem() -> str | None:
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return f"the nightly backup task '{TASK_NAME}' isn't installed (run install_backup_task.ps1)"
    rows = [r for r in out.stdout.splitlines() if r.strip()]
    if len(rows) >= 2:
        import csv
        header, values = next(csv.reader([rows[0]])), next(csv.reader([rows[1]]))
        info = dict(zip(header, values))
        last = info.get("Last Result", "").strip()
        if last not in ("", "0", "267011", "267009"):   # 267011 = never run yet, 267009 = running now
            return f"the nightly backup task's last run failed (result {last}); see backup_task.log"
    return None


def check(dest: Path = backup.DEFAULT_DEST, now: float | None = None, max_age_hours: float = MAX_AGE_HOURS,
          check_task: bool = True, check_passphrase: bool = True) -> list[str]:
    now = _now() if now is None else now
    dest = Path(dest)
    bs = backup.BackupSet(dest)
    alerts: list[str] = []
    max_age = max_age_hours * 3600

    entries = bs.entries()
    if not entries:
        alerts.append(f"no backups found in {dest}")
    else:
        newest = entries[-1]
        age_h = (now - _ts(newest["created_at"])) / 3600
        if age_h * 3600 > max_age:
            alerts.append(f"newest backup is {age_h:.0f}h old (limit {max_age_hours:.0f}h)")
        if not newest.get("verified"):
            alerts.append(f"newest backup {newest['vault_id']} was not verified")

    if check_passphrase:
        try:
            backup.load_passphrase()
        except (LookupError, OSError) as e:
            alerts.append(f"backup passphrase unavailable: {e}")

    import offsite_s3
    if offsite_s3.S3Offsite.load_config(dest):
        off = offsite_s3.S3Offsite(dest, runner=offsite_s3.cli_runner)
        created = {e["vault_id"]: _ts(e["created_at"]) for e in entries}
        overdue = [v for v in off.pending() if v in created and now - created[v] > max_age]
        if overdue:
            alerts.append(f"{len(overdue)} backup(s) older than {max_age_hours:.0f}h not yet confirmed in S3")
        last_sync = dest / LAST_SYNC_NAME
        if last_sync.exists():
            report = json.loads(last_sync.read_text(encoding="utf-8"))
            if report.get("error") or report.get("failed"):
                alerts.append("last off-site sync had errors: "
                              + (report.get("error") or ", ".join(report["failed"]))[:200])

    history = test_restore_history(dest)
    if entries:
        ok = [r for r in history if r.get("ok")]
        if history and not history[-1].get("ok"):
            last = history[-1]
            alerts.append("last test restore FAILED: "
                          + (last.get("error") or last.get("offsite", {}).get("error", "see test_restores.jsonl")))
        elif not ok or now - ok[-1]["at"] > TEST_RESTORE_STALE_DAYS * 86400:
            alerts.append(f"no successful test restore in the last {TEST_RESTORE_STALE_DAYS} days")

    if dest.exists():
        free = shutil.disk_usage(dest).free
        if free < MIN_FREE_BYTES:
            alerts.append(f"only {free / (1 << 20):.0f} MB free where backups are stored")

    if check_task:
        problem = _scheduled_task_problem()
        if problem:
            alerts.append(problem)
    return alerts


def run_scheduled(dest: Path, passphrase: str, audit_path: str | None = None, notify: bool = True) -> dict:
    """What backup.py runs after each nightly backup."""
    bs = backup.BackupSet(dest)
    restored = test_restore(bs, passphrase) if test_restore_due(dest) else None
    alerts = check(dest, check_task=False)   # the task is the one running us right now
    if audit_path:
        from audit_trail import AuditTrail
        AuditTrail(audit_path).log(module="backup_health", action="health_check", node_id="backup",
                                   details={"alerts": alerts,
                                            "test_restore": None if restored is None else
                                            {k: restored.get(k) for k in ("ok", "vault_id", "files", "error")}})
    if alerts and notify:
        from node_supervisor import notify as toast
        toast("network-os backups: needs attention", "; ".join(alerts))
    return {"alerts": alerts, "test_restore": restored}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backup health checks and test restores.")
    p.add_argument("--dest", type=Path, default=backup.DEFAULT_DEST)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("--json", action="store_true")
    c.add_argument("--max-age-hours", type=float, default=MAX_AGE_HOURS)
    sub.add_parser("test-restore")
    args = p.parse_args(argv)

    if args.command == "check":
        alerts = check(args.dest, max_age_hours=args.max_age_hours)
        if args.json:
            print(json.dumps({"alerts": alerts, "ok": not alerts}, indent=2))
        else:
            print("\n".join(f"[ALERT] {a}" for a in alerts) or "No alerts. Backups healthy.")
        return 1 if alerts else 0
    try:
        passphrase = backup.load_passphrase()
    except (LookupError, OSError) as e:
        p.error(str(e))
    result = test_restore(backup.BackupSet(args.dest), passphrase)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
