#!/usr/bin/env python3
"""
retention.py — how long each kind of data stays in the live store
(live_store.py), and the job that enforces it.

THE POLICY
---------------
Per live_store stream, two numbers in days (null = keep forever):

- events: how long an event row is kept after it was written.
- snapshots: delete a snapshot that hasn't been UPDATED for this long --
  e.g. the status of a node that no longer runs. A snapshot that keeps
  being saved never ages out; it is current state, not history.

The defaults below keep what the project's tamper-evidence depends on
(chain blocks, audit entries, ledger transactions) forever -- deleting
any of them would break verify_chain() on a copy of that history -- and
age out everything that is operational noise. Personal data (the "dna"
stream) is never deleted by age: it stays until you explicitly `forget`
it. Override any of this with a JSON file of the same shape; "*" covers
streams the policy doesn't name.

WHAT DELETION MEANS HERE
-----------------------------
- The live store runs with SQLite secure_delete, and `apply`/`forget`
  compact the file afterwards (VACUUM + WAL truncate), so deleted rows
  are gone from live_store.db and its -wal file, not merely unlinked.
  An SSD or filesystem can still hold old blocks, and backups/copies are
  separate: this deletes from THIS database only.
- The live store is a mirror. `forget` removes a key from it, but the
  module's own JSON file (e.g. dna_state.json) still holds the data and
  will re-mirror it on its next save. To delete personal data for real,
  delete that source file as well -- `forget` prints this reminder.
- Every apply/forget is logged to the audit trail with counts, stream
  names and the policy's hash -- never the deleted content.

Usage
-----
    python retention.py show-policy
    python retention.py plan                        # dry run: what apply would delete
    python retention.py apply --audit system_audit.jsonl
    python retention.py forget --stream dna --key my-research-node --confirm

node_supervisor.py runs `apply` on its database as part of the daily report.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time

import live_store

DAY = 86400.0

DEFAULT_POLICY: dict = {
    "events": {
        "chain": None, "audit": None, "ledger": None,   # tamper-evident history: forever
        "os": 365,                                      # kernel check results
        "supervisor": 90, "network_ledger": 90, "research": 90, "corpus": 90,
        "status": 30,                                   # node heartbeats
        "dna": 30,                                      # change pointers only (key + hash), not the strand
        "*": 90,
    },
    "snapshots": {
        "status": 30,                                   # a node gone quiet for 30 days
        "*": None,                                      # current state stays; dna only via `forget`
    },
}


class PolicyError(ValueError):
    pass


def load_policy(path: str | None = None) -> dict:
    """DEFAULT_POLICY, with any stream values from `path` layered over it."""
    policy = copy.deepcopy(DEFAULT_POLICY)
    if not path:
        return policy
    with open(path, "r", encoding="utf-8") as f:
        override = json.load(f)
    if not isinstance(override, dict) or set(override) - {"events", "snapshots"}:
        raise PolicyError('policy file must be an object with only "events" and/or "snapshots"')
    for section, values in override.items():
        if not isinstance(values, dict):
            raise PolicyError(f'"{section}" must map stream names to days or null')
        for stream, days in values.items():
            if days is not None and (isinstance(days, bool) or not isinstance(days, int) or days < 1):
                raise PolicyError(f'{section}.{stream}: expected a whole number of days >= 1, or null')
            policy[section][stream] = days
    return policy


def policy_hash(policy: dict) -> str:
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()[:16]


def _days_for(policy: dict, section: str, stream: str):
    table = policy[section]
    return table[stream] if stream in table else table.get("*")


def plan(store: live_store.LiveStore, policy: dict, now: float | None = None) -> list[dict]:
    """What apply() would delete, per stream -- deletes nothing."""
    now = time.time() if now is None else now
    rows = []
    for stream in store.streams():
        ev_days = _days_for(policy, "events", stream)
        sn_days = _days_for(policy, "snapshots", stream)
        rows.append({
            "stream": stream,
            "events_keep_days": ev_days,
            "events_to_delete": store.count_events_before(stream, now - ev_days * DAY) if ev_days else 0,
            "snapshots_keep_days": sn_days,
            "snapshots_to_delete": store.count_snapshots_before(stream, now - sn_days * DAY) if sn_days else 0,
        })
    return rows


def _audit(audit_path: str | None, action: str, details: dict) -> None:
    if audit_path:
        from audit_trail import AuditTrail
        AuditTrail(audit_path).log(module="retention", action=action, node_id="retention", details=details)


def apply(db_path: str, policy: dict, now: float | None = None, audit_path: str | None = None,
          compact: bool = True) -> dict:
    """Deletes everything past its retention period, then compacts."""
    now = time.time() if now is None else now
    store = live_store.LiveStore(db_path)
    try:
        deleted = {}
        for row in plan(store, policy, now):
            s = row["stream"]
            ev = store.delete_events_before(s, now - row["events_keep_days"] * DAY) if row["events_keep_days"] else 0
            sn = (store.delete_snapshots_before(s, now - row["snapshots_keep_days"] * DAY)
                  if row["snapshots_keep_days"] else 0)
            if ev or sn:
                deleted[s] = {"events": ev, "snapshots": sn}
        total = sum(d["events"] + d["snapshots"] for d in deleted.values())
        compacted = store.compact() if compact and total else None
    finally:
        store.close()
    report = {"db": db_path, "policy_hash": policy_hash(policy), "deleted": deleted,
              "total_deleted": total, "compact": compacted, "ran_at": now}
    _audit(audit_path, "retention_applied",
           {k: report[k] for k in ("policy_hash", "deleted", "total_deleted", "compact")})
    return report


def forget(db_path: str, stream: str, key: str, audit_path: str | None = None) -> dict:
    """Removes one key's snapshot and events from the live store, then compacts."""
    store = live_store.LiveStore(db_path)
    try:
        ev, sn = store.forget(stream, key)
        compacted = store.compact()
    finally:
        store.close()
    report = {"stream": stream, "key": key, "events_deleted": ev, "snapshots_deleted": sn, "compact": compacted}
    _audit(audit_path, "forget", report)
    return report


def _print_plan(rows: list[dict]) -> None:
    fmt = "{:<16} {:>10} {:>9}   {:>10} {:>9}"
    print(fmt.format("stream", "events", "delete", "snapshots", "delete"))
    for r in rows:
        keep = lambda d: "forever" if d is None else f"{d}d"
        print(fmt.format(r["stream"], keep(r["events_keep_days"]), r["events_to_delete"],
                         keep(r["snapshots_keep_days"]), r["snapshots_to_delete"]))


def main(argv: list[str] | None = None) -> int:
    default_db = os.environ.get(live_store.ENV_VAR) or "live_store.db"
    p = argparse.ArgumentParser(description="Enforce retention on the live store (live_store.py).")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("show-policy", "plan", "apply", "forget"):
        c = sub.add_parser(name)
        c.add_argument("--db", default=default_db, help=f"live store file (default: ${live_store.ENV_VAR} or live_store.db)")
        c.add_argument("--policy", help="JSON policy file layered over the defaults")
        if name in ("apply", "forget"):
            c.add_argument("--audit", help="log what was deleted (counts only) to this audit_trail.py file")
        if name == "apply":
            c.add_argument("--no-compact", action="store_true", help="skip VACUUM (deleted rows stay in free pages)")
        if name == "forget":
            c.add_argument("--stream", required=True)
            c.add_argument("--key", required=True)
            c.add_argument("--confirm", action="store_true", help="required: forgetting cannot be undone")
    args = p.parse_args(argv)

    try:
        policy = load_policy(args.policy)
    except (OSError, ValueError) as e:
        p.error(f"policy: {e}")

    if args.command == "show-policy":
        print(json.dumps(policy, indent=2))
        print(f"policy hash: {policy_hash(policy)}")
        return 0
    if args.command != "forget" and not os.path.exists(args.db):
        p.error(f"no live store at {args.db}")

    if args.command == "plan":
        store = live_store.LiveStore(args.db)
        try:
            _print_plan(plan(store, policy))
        finally:
            store.close()
        return 0
    if args.command == "apply":
        report = apply(args.db, policy, audit_path=args.audit, compact=not args.no_compact)
        print(json.dumps(report, indent=2))
        return 0

    if not args.confirm:
        p.error("forget deletes permanently; add --confirm")
    if not os.path.exists(args.db):
        p.error(f"no live store at {args.db}")
    report = forget(args.db, args.stream, args.key, audit_path=args.audit)
    print(json.dumps(report, indent=2))
    print(f"\nRemoved from the live store only. The module's own state file (for the dna stream, "
          f"the DigitalDNA file saved with seed_label {args.key!r}) still holds this data and will "
          f"re-mirror it on its next save; delete that file too to remove it completely.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
