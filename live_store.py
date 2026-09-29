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
live_store.py — one local SQLite database that every module mirrors its
state into as it happens, so a dashboard or script can watch the whole
system live (see live_feed.py) instead of re-reading a dozen JSON files.

TWO KINDS OF RECORD
------------------------
- events: append-only rows, one per thing that happened -- a chain block
  appended, an audit entry logged, a token-ledger transaction. Each gets
  a monotonically increasing `seq`, so a reader asks "everything after
  seq N" and never misses or repeats a row.
- snapshots: the latest full copy of whole-file state that is rewritten
  rather than appended to -- a node's DNA strand, the research store,
  the corpus, node status. One row per (stream, key), replaced on every
  save. Each replacement ALSO appends a small "snapshot" event (key +
  sha256 of the data, not the data itself), so live readers see that it
  changed without every DNA autosave copying the whole strand into the
  event log.

WHAT THIS IS NOT
---------------------
Not the source of truth. The JSON / JSONL files each module already
writes stay authoritative, and their hash chains (chain_store.py,
audit_trail.py) are what verify_chain() checks -- a row in this
database proves nothing on its own. This is a queryable, live mirror.

Disabled by default: until an entry point calls enable() (run_all.py,
run_node_cli.py via --live-db / NETWORK_OS_LIVE_DB), every emit() here
is a no-op, so library code and the test suite behave exactly as
before. And it never breaks the caller: if a write fails (disk full,
locked past the busy timeout, bad path), the error is logged once and
the node keeps running on its JSON files.

The database holds everything the modules save, including the personal
DNA strand state, so it lives beside the other state files and is
git-ignored. Node signing keys (keys/*.pem) are never written here.

Several processes may share one database file (node_supervisor.py runs
three nodes): WAL mode plus a busy timeout lets them write concurrently.

Usage
-----
    import live_store

    live_store.enable("live_store.db")
    live_store.emit("chain", "node-0", "block", block_dict)
    live_store.snapshot("dna", "node-0", state_dict)

    store = live_store.get()
    store.events_after(0, stream="chain")      # [{"seq": 1, ...}, ...]
    store.get_snapshot("dna", "node-0")        # {"updated_at": ..., "data": {...}}
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time

logger = logging.getLogger("live_store")

ENV_VAR = "NETWORK_OS_LIVE_DB"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    stream  TEXT NOT NULL,
    source  TEXT NOT NULL,
    kind    TEXT NOT NULL,
    data    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_stream_seq ON events (stream, seq);
CREATE TABLE IF NOT EXISTS snapshots (
    stream      TEXT NOT NULL,
    key         TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    sha256      TEXT NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (stream, key)
);
"""


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


class LiveStore:
    def __init__(self, path: str, busy_timeout_s: float = 5.0):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, timeout=busy_timeout_s, check_same_thread=False,
                                     isolation_level=None)   # autocommit; each write is its own transaction
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # deleted rows are overwritten with zeros, not just unlinked (see retention.py)
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- writes ----
    def emit(self, stream: str, source: str, kind: str, data) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events (ts, stream, source, kind, data) VALUES (?, ?, ?, ?, ?)",
                (time.time(), stream, str(source), kind, _dumps(data)),
            )
            return cur.lastrowid

    def snapshot(self, stream: str, key: str, data) -> int:
        body = _dumps(data)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "INSERT INTO snapshots (stream, key, updated_at, sha256, data) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT (stream, key) DO UPDATE SET "
                    "updated_at = excluded.updated_at, sha256 = excluded.sha256, data = excluded.data",
                    (stream, str(key), now, digest, body),
                )
                cur = self._conn.execute(
                    "INSERT INTO events (ts, stream, source, kind, data) VALUES (?, ?, ?, 'snapshot', ?)",
                    (now, stream, str(key), _dumps({"key": str(key), "sha256": digest, "bytes": len(body)})),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            return cur.lastrowid

    # ---- reads ----
    def events_after(self, after_seq: int = 0, stream: str | None = None, limit: int = 500) -> list[dict]:
        sql = "SELECT seq, ts, stream, source, kind, data FROM events WHERE seq > ?"
        params: list = [after_seq]
        if stream:
            sql += " AND stream = ?"
            params.append(stream)
        sql += " ORDER BY seq LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            {"seq": r[0], "ts": r[1], "stream": r[2], "source": r[3], "kind": r[4], "data": json.loads(r[5])}
            for r in rows
        ]

    def last_seq(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()
        return row[0]

    def list_snapshots(self, stream: str | None = None) -> list[dict]:
        sql = "SELECT stream, key, updated_at, sha256, LENGTH(data) FROM snapshots"
        params: list = []
        if stream:
            sql += " WHERE stream = ?"
            params.append(stream)
        sql += " ORDER BY stream, key"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [{"stream": r[0], "key": r[1], "updated_at": r[2], "sha256": r[3], "bytes": r[4]} for r in rows]

    def get_snapshot(self, stream: str, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT updated_at, sha256, data FROM snapshots WHERE stream = ? AND key = ?", (stream, str(key)),
            ).fetchone()
        if row is None:
            return None
        return {"stream": stream, "key": str(key), "updated_at": row[0], "sha256": row[1], "data": json.loads(row[2])}

    def streams(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT stream FROM events UNION SELECT stream FROM snapshots ORDER BY 1").fetchall()
        return [r[0] for r in rows]

    # ---- deletes (used by retention.py) ----
    def count_events_before(self, stream: str, cutoff_ts: float) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM events WHERE stream = ? AND ts < ?",
                                      (stream, cutoff_ts)).fetchone()[0]

    def count_snapshots_before(self, stream: str, cutoff_ts: float) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM snapshots WHERE stream = ? AND updated_at < ?",
                                      (stream, cutoff_ts)).fetchone()[0]

    def delete_events_before(self, stream: str, cutoff_ts: float) -> int:
        with self._lock:
            return self._conn.execute("DELETE FROM events WHERE stream = ? AND ts < ?",
                                      (stream, cutoff_ts)).rowcount

    def delete_snapshots_before(self, stream: str, cutoff_ts: float) -> int:
        with self._lock:
            return self._conn.execute("DELETE FROM snapshots WHERE stream = ? AND updated_at < ?",
                                      (stream, cutoff_ts)).rowcount

    def forget(self, stream: str, key: str) -> tuple[int, int]:
        """Deletes one snapshot and every event about it (source == key).
        Returns (events_deleted, snapshots_deleted)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                ev = self._conn.execute("DELETE FROM events WHERE stream = ? AND source = ?",
                                        (stream, str(key))).rowcount
                sn = self._conn.execute("DELETE FROM snapshots WHERE stream = ? AND key = ?",
                                        (stream, str(key))).rowcount
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        return ev, sn

    def compact(self) -> dict:
        """VACUUM, then fold the WAL back in and truncate it, so deleted rows
        leave neither the main file nor the -wal file. Another process
        holding a read open can keep the WAL from truncating; `wal_busy`
        reports that, and the next compact finishes the job."""
        with self._lock:
            self._conn.execute("VACUUM")
            busy, _, _ = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return {"vacuumed": True, "wal_busy": bool(busy)}


# ---- process-wide default store: what the module hooks write to ----
_default: LiveStore | None = None
_warned = False


def enable(path: str) -> LiveStore:
    global _default, _warned
    if _default is not None and os.path.abspath(_default.path) == os.path.abspath(path):
        return _default
    disable()
    _default = LiveStore(path)
    _warned = False
    return _default


def enable_from_env() -> LiveStore | None:
    path = os.environ.get(ENV_VAR)
    return enable(path) if path else None


def disable() -> None:
    global _default
    if _default is not None:
        try:
            _default.close()
        except Exception:
            pass
    _default = None


def get() -> LiveStore | None:
    return _default


def _report(err: Exception) -> None:
    global _warned
    if not _warned:
        _warned = True
        logger.warning("live_store write failed (%s) -- continuing on JSON files only; "
                       "further failures will not be logged", err)


def emit(stream: str, source, kind: str, data) -> None:
    """No-op unless enable() was called. Never raises."""
    store = _default
    if store is None:
        return
    try:
        store.emit(stream, source, kind, data)
    except Exception as e:
        _report(e)


def snapshot(stream: str, key, data) -> None:
    """No-op unless enable() was called. Never raises."""
    store = _default
    if store is None:
        return
    try:
        store.snapshot(stream, key, data)
    except Exception as e:
        _report(e)


def source_from_path(path: str | None) -> str:
    """'autonomous/node-0/chain_node-0.json' -> 'chain_node-0'."""
    if not path:
        return "memory"
    return os.path.splitext(os.path.basename(path))[0]
