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
Tests for live_store / live_feed — the live SQLite mirror. Pins: off by
default (hooks are no-ops), event ordering by seq, snapshot upsert plus
its change event, the module hooks actually emitting, a broken store
never breaking the caller, and the feed's JSON + SSE endpoints and its
loopback-only bind.
"""
import json
import os
import threading
import urllib.request

import pytest

import live_store
from audit_trail import AuditTrail
from chain_store import ChainStore
from live_feed import LiveFeedServer
from token_ledger import TokenLedger


@pytest.fixture(autouse=True)
def _reset_default_store():
    live_store.disable()
    yield
    live_store.disable()


@pytest.fixture
def store(tmp_path):
    return live_store.enable(os.path.join(str(tmp_path), "live.db"))


def test_disabled_by_default_hooks_are_noops(tmp_path):
    assert live_store.get() is None
    live_store.emit("chain", "x", "block", {"n": 1})   # must not raise
    live_store.snapshot("dna", "x", {"n": 1})
    ChainStore(store_path=os.path.join(str(tmp_path), "c.json")).append({"n": 1})
    assert not os.path.exists(os.path.join(str(tmp_path), "live.db"))


def test_events_are_ordered_and_filterable(store):
    live_store.emit("chain", "node-0", "block", {"n": 1})
    live_store.emit("audit", "node-0", "handshake", {"n": 2})
    live_store.emit("chain", "node-1", "block", {"n": 3})

    all_events = store.events_after(0)
    assert [e["data"]["n"] for e in all_events] == [1, 2, 3]
    assert [e["seq"] for e in all_events] == sorted(e["seq"] for e in all_events)

    chain = store.events_after(0, stream="chain")
    assert [e["source"] for e in chain] == ["node-0", "node-1"]
    assert store.events_after(all_events[1]["seq"]) == [all_events[2]]
    assert store.last_seq() == all_events[-1]["seq"]


def test_snapshot_upserts_and_emits_change_event(store):
    live_store.snapshot("dna", "node-0", {"strand_hex": "aa"})
    live_store.snapshot("dna", "node-0", {"strand_hex": "bb"})

    snap = store.get_snapshot("dna", "node-0")
    assert snap["data"] == {"strand_hex": "bb"}
    assert len(store.list_snapshots("dna")) == 1

    events = store.events_after(0, stream="dna")
    assert [e["kind"] for e in events] == ["snapshot", "snapshot"]
    assert events[-1]["data"]["sha256"] == snap["sha256"]
    assert "strand_hex" not in events[-1]["data"]   # the event is a pointer, not a copy


def test_store_is_shared_across_connections(store, tmp_path):
    live_store.emit("chain", "node-0", "block", {"n": 1})
    other = live_store.LiveStore(store.path)   # e.g. another node process or the feed
    try:
        assert [e["data"]["n"] for e in other.events_after(0)] == [1]
    finally:
        other.close()


def test_module_hooks_emit(store, tmp_path):
    d = str(tmp_path)
    block = ChainStore(store_path=os.path.join(d, "chain_node-0.json")).append({"note": "one"})
    AuditTrail(os.path.join(d, "audit.jsonl")).log(module="test", action="ping", node_id="node-0")
    TokenLedger(store_path=os.path.join(d, "tokens.json")).credit("node-0", 1.5, reason="mine_block")

    chain = store.events_after(0, stream="chain")
    assert chain[0]["source"] == "chain_node-0"
    assert chain[0]["data"]["block_hash"] == block.block_hash

    audit = store.events_after(0, stream="audit")
    assert audit[0]["kind"] == "ping" and audit[0]["data"]["hash"]

    ledger = store.events_after(0, stream="ledger")
    assert ledger[0]["data"]["amount"] == 1.5


def test_failing_store_never_breaks_caller(store, tmp_path, caplog):
    store.close()   # every later write now raises inside live_store
    chain = ChainStore(store_path=os.path.join(str(tmp_path), "c.json"))
    chain.append({"n": 1})
    chain.append({"n": 2})
    assert len(chain.blocks) == 2
    assert chain.verify_chain()[0]
    assert sum("live_store write failed" in r.message for r in caplog.records) == 1


def _get_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def test_feed_json_endpoints(store):
    live_store.emit("chain", "node-0", "block", {"n": 1})
    live_store.snapshot("status", "node-0", {"up": True})
    feed = LiveFeedServer(store.path, port=0).start()
    try:
        base = f"http://127.0.0.1:{feed.port}"
        assert _get_json(base + "/")["last_seq"] == store.last_seq()
        assert [e["data"]["n"] for e in _get_json(base + "/events?stream=chain")] == [1]
        assert _get_json(base + "/snapshots?stream=status")[0]["key"] == "node-0"
        assert _get_json(base + "/snapshot?stream=status&key=node-0")["data"] == {"up": True}
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/snapshot?stream=status&key=nope", timeout=5)
        assert e.value.code == 404
    finally:
        feed.stop()


def test_feed_sse_streams_new_events(store):
    feed = LiveFeedServer(store.path, port=0).start()
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{feed.port}/stream?stream=chain", timeout=10)
        # written after the subscriber connected: must arrive live
        threading.Timer(0.3, lambda: live_store.emit("chain", "node-0", "block", {"n": 42})).start()
        lines = []
        while not any(l.startswith("data:") for l in lines):
            lines.append(resp.readline().decode("utf-8").strip())
        data = json.loads(next(l for l in lines if l.startswith("data:"))[5:])
        assert data["data"] == {"n": 42}
        assert f"id: {data['seq']}" in lines
        resp.close()
    finally:
        feed.stop()


def test_feed_refuses_non_loopback_bind(tmp_path):
    with pytest.raises(ValueError, match="loopback only"):
        LiveFeedServer(os.path.join(str(tmp_path), "live.db"), host="0.0.0.0", port=0)
