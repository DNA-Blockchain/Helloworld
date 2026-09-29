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
Tests for retention.py — the live store's retention policy. Pins: the
default policy never ages out tamper-evident history or personal data,
plan() matches what apply() deletes, policy overrides and validation,
forget() removing one key only, deleted content really leaving the
database file (secure_delete + compaction), counts-only audit records,
and the supervisor's daily hook.
"""
import datetime as dt
import json
import os
import sqlite3

import pytest

import live_store
import retention
from audit_trail import AuditTrail

DAY = retention.DAY
NOW = 1_800_000_000.0


def _age(db, table, days):
    """Backdate every row in `table` by `days` (the store stamps time.time())."""
    col = "ts" if table == "events" else "updated_at"
    con = sqlite3.connect(db)
    con.execute(f"UPDATE {table} SET {col} = ?", (NOW - days * DAY,))
    con.commit()
    con.close()


@pytest.fixture
def db(tmp_path):
    path = os.path.join(str(tmp_path), "live.db")
    store = live_store.LiveStore(path)
    # note: each snapshot() also writes a change event, so status and dna end up with 2 events
    for stream in ("chain", "audit", "ledger", "status", "dna", "custom"):
        store.emit(stream, "node-0", "x", {"stream": stream})
    store.snapshot("status", "node-0", {"up": True})
    store.snapshot("dna", "my-node", {"strand_hex": "ab" * 16})
    store.close()
    return path


def _counts(path):
    con = sqlite3.connect(path)
    ev = dict(con.execute("SELECT stream, COUNT(*) FROM events GROUP BY stream").fetchall())
    sn = dict(con.execute("SELECT stream, COUNT(*) FROM snapshots GROUP BY stream").fetchall())
    con.close()
    return ev, sn


def test_default_policy_keeps_history_and_personal_data_forever(db):
    _age(db, "events", 400)
    _age(db, "snapshots", 400)
    retention.apply(db, retention.load_policy(), now=NOW)
    ev, sn = _counts(db)
    assert ev == {"chain": 1, "audit": 1, "ledger": 1}   # status, dna pointers, custom ("*") aged out
    assert sn == {"dna": 1}                              # stale status snapshot gone; dna stays


def test_nothing_is_deleted_inside_the_window(db):
    _age(db, "events", 10)
    _age(db, "snapshots", 10)
    report = retention.apply(db, retention.load_policy(), now=NOW)
    assert report["total_deleted"] == 0 and report["compact"] is None


def test_plan_matches_apply_and_deletes_nothing(db):
    _age(db, "events", 45)
    _age(db, "snapshots", 45)
    store = live_store.LiveStore(db)
    rows = {r["stream"]: r for r in retention.plan(store, retention.load_policy(), now=NOW)}
    store.close()
    assert rows["status"]["events_to_delete"] == 2 and rows["status"]["snapshots_to_delete"] == 1
    assert rows["dna"]["events_to_delete"] == 2 and rows["dna"]["snapshots_to_delete"] == 0
    assert rows["custom"]["events_to_delete"] == 0            # "*" is 90 days
    assert _counts(db)[0]["status"] == 2                       # plan deleted nothing

    report = retention.apply(db, retention.load_policy(), now=NOW)
    assert report["deleted"] == {"status": {"events": 2, "snapshots": 1}, "dna": {"events": 2, "snapshots": 0}}


def test_policy_file_overrides_and_validates(tmp_path, db):
    path = os.path.join(str(tmp_path), "policy.json")
    with open(path, "w") as f:
        json.dump({"events": {"chain": 7}, "snapshots": {"dna": 5}}, f)
    policy = retention.load_policy(path)
    assert policy["events"]["chain"] == 7 and policy["events"]["audit"] is None   # others keep defaults

    _age(db, "events", 8)
    _age(db, "snapshots", 8)
    report = retention.apply(db, policy, now=NOW)
    assert report["deleted"]["chain"]["events"] == 1
    assert report["deleted"]["dna"]["snapshots"] == 1

    for bad in ({"events": {"chain": 0}}, {"events": {"chain": "7"}}, {"events": {"chain": True}},
                {"events": []}, {"rows": {}}):
        with open(path, "w") as f:
            json.dump(bad, f)
        with pytest.raises(retention.PolicyError):
            retention.load_policy(path)


def test_forget_removes_only_that_key(db):
    store = live_store.LiveStore(db)
    store.snapshot("dna", "other-node", {"strand_hex": "cd" * 16})
    store.close()
    report = retention.forget(db, "dna", "my-node")
    assert report["snapshots_deleted"] == 1 and report["events_deleted"] == 1   # its snapshot pointer event
    store = live_store.LiveStore(db)
    assert store.get_snapshot("dna", "my-node") is None
    assert store.get_snapshot("dna", "other-node") is not None
    store.close()


def test_forgotten_content_is_gone_from_the_file(tmp_path):
    path = os.path.join(str(tmp_path), "live.db")
    secret = "SECRET-STRAND-" + "ACGT" * 64
    store = live_store.LiveStore(path)
    store.snapshot("dna", "me", {"strand": secret})
    for i in range(50):   # other data, so this isn't just an empty file
        store.emit("chain", "node-0", "block", {"i": i})
    assert secret.encode() in open(path, "rb").read() + open(path + "-wal", "rb").read()
    store.close()

    retention.forget(path, "dna", "me")
    raw = open(path, "rb").read()
    wal = path + "-wal"
    raw += open(wal, "rb").read() if os.path.exists(wal) else b""
    assert secret.encode() not in raw
    assert b"SECRET-STRAND" not in raw


def test_audit_records_counts_not_content(tmp_path, db):
    audit = os.path.join(str(tmp_path), "audit.jsonl")
    _age(db, "events", 45)
    retention.apply(db, retention.load_policy(), now=NOW, audit_path=audit)
    retention.forget(db, "dna", "my-node", audit_path=audit)
    entries = AuditTrail(audit).read_all()
    assert [e["action"] for e in entries] == ["retention_applied", "forget"]
    assert entries[0]["details"]["deleted"]["status"]["events"] == 2
    assert "ab" * 16 not in open(audit).read()
    assert AuditTrail(audit).verify_chain()[0]


def test_cli_forget_requires_confirm(db, capsys):
    with pytest.raises(SystemExit):
        retention.main(["forget", "--db", db, "--stream", "dna", "--key", "my-node"])
    assert live_store.LiveStore(db).get_snapshot("dna", "my-node") is not None
    assert retention.main(["forget", "--db", db, "--stream", "dna", "--key", "my-node", "--confirm"]) == 0
    assert "still holds this data" in capsys.readouterr().out


def test_cli_plan_and_apply(db, capsys):
    assert retention.main(["plan", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "chain" in out and "forever" in out
    assert retention.main(["apply", "--db", db]) == 0


def test_supervisor_daily_hook(tmp_path, db, monkeypatch):
    import node_supervisor
    monkeypatch.delenv(live_store.ENV_VAR, raising=False)
    cfg = node_supervisor.Config(base_dir=str(tmp_path))
    os.replace(db, cfg.live_db)
    _age(cfg.live_db, "events", 45)
    sup = node_supervisor.Supervisor.__new__(node_supervisor.Supervisor)   # no nodes/keys needed
    sup.cfg = cfg
    sup.log = node_supervisor.logging.getLogger("test")
    report = sup.apply_retention(dt.datetime.fromtimestamp(NOW))
    assert report["deleted"]["status"]["events"] == 2
    assert AuditTrail(cfg.path("retention_audit.jsonl")).read_all()[0]["action"] == "retention_applied"
