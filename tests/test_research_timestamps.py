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

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.timestamp import Timestamp

import external_chain_bridge
import research_analysis
import research_fetch
import research_timestamps
import research_viewer
from research_ledger import ResearchLedger
from research_provenance import create_public_research_records_event, validate_public_provenance

ANCHOR = {"chain": "bitcoin", "height": 912345, "block_hash": "ab" * 32, "source": "mempool.space"}


def event(anchor=None):
    ranking = research_analysis.run(json.loads(json.dumps(research_fetch.FIXTURE_REQUEST)))
    return create_public_research_records_event(ranking, confirm_publication=True, time_anchor=anchor)


class FakeCalendar:
    """Stands in for opentimestamps.calendar.RemoteCalendar."""
    committed = {}      # url -> bitcoin height, once "in a block"
    down = set()

    def __init__(self, url):
        self.url = url

    def submit(self, digest, timeout=None):
        if self.url in self.down:
            raise OSError("calendar unreachable")
        stamp = Timestamp(digest)
        stamp.attestations.add(PendingAttestation(self.url))
        return stamp

    def get_timestamp(self, commitment, timeout=None):
        if self.url not in self.committed:
            raise KeyError("not committed yet")
        stamp = Timestamp(commitment)
        stamp.attestations.add(BitcoinBlockHeaderAttestation(self.committed[self.url]))
        return stamp


@pytest.fixture
def calendars(monkeypatch):
    FakeCalendar.committed, FakeCalendar.down = {}, set()
    monkeypatch.setattr(research_timestamps, "RemoteCalendar", FakeCalendar)
    return FakeCalendar


def test_time_anchor_is_optional_and_validated():
    validate_public_provenance(event())                  # events from before anchors
    anchored = event(ANCHOR)
    assert anchored["time_anchor"] == ANCHOR
    for bad in ({**ANCHOR, "height": "912345"}, {**ANCHOR, "block_hash": "xyz"},
                {**ANCHOR, "source": "someone.example"}, {**ANCHOR, "extra": 1}):
        tampered = {**anchored, "time_anchor": bad}
        with pytest.raises(ValueError, match="time anchor"):
            validate_public_provenance(tampered)


def test_fetch_bitcoin_anchor_reads_hash_then_height(monkeypatch):
    calls = []

    class Response:
        def __init__(self, text="", payload=None):
            self.text, self.payload = text, payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_get(url, timeout):
        calls.append(url)
        if "blockstream" in url:
            raise OSError("down")
        if url.endswith("/blocks/tip/hash"):
            return Response(text="cd" * 32 + "\n")
        return Response(payload={"height": 912346})

    monkeypatch.setattr(external_chain_bridge.requests, "get", fake_get)
    anchor = external_chain_bridge.fetch_bitcoin_anchor()
    assert anchor == {"chain": "bitcoin", "height": 912346, "block_hash": "cd" * 32, "source": "mempool.space"}
    assert calls[-1] == "https://mempool.space/api/block/" + "cd" * 32


def test_stamp_upgrade_and_status(tmp_path, calendars):
    published = event(ANCHOR)
    (tmp_path / "node-0").mkdir()
    ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json")).add_block(
        {"origin": 0, "index": 1, "hash_hex": "ab", "research_provenance": published})
    proofs = tmp_path / "timestamps"
    calendars.down = {research_timestamps.DEFAULT_CALENDARS[2]}

    notes = research_timestamps.stamp_all(str(tmp_path), proofs, research_timestamps.DEFAULT_CALENDARS)
    assert notes == [f"{published['event_id']}: stamped (1 calendar(s) unreachable)"]
    proof = research_timestamps.load_proof((proofs / f"{published['event_id']}.ots").read_bytes())
    assert proof.file_digest == research_timestamps.event_digest(published)
    assert research_timestamps.proof_state(proof)["pending"] == sorted(research_timestamps.DEFAULT_CALENDARS[:2])
    assert research_timestamps.stamp_all(str(tmp_path), proofs) == []            # already stamped
    [row] = research_timestamps.status(str(tmp_path), proofs)
    assert row["proof"] == "pending at 2 calendar(s)"

    assert research_timestamps.upgrade_all(proofs) == []                          # not in Bitcoin yet
    calendars.committed = {research_timestamps.DEFAULT_CALENDARS[0]: 912400}
    assert research_timestamps.upgrade_all(proofs) == [f"{published['event_id']}: in Bitcoin block 912400"]
    [row] = research_timestamps.status(str(tmp_path), proofs)
    assert row["proof"] == "bitcoin block 912400"


def test_every_calendar_down_is_reported(tmp_path, calendars):
    calendars.down = set(research_timestamps.DEFAULT_CALENDARS)
    with pytest.raises(RuntimeError, match="no OpenTimestamps calendar"):
        research_timestamps.stamp_digest(b"\x00" * 32)


def test_status_flags_a_proof_for_different_content(tmp_path, calendars):
    published = event()
    (tmp_path / "node-0").mkdir()
    ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json")).add_block(
        {"origin": 0, "index": 1, "research_provenance": published})
    proofs = tmp_path / "timestamps"
    proofs.mkdir()
    other, _ = research_timestamps.stamp_digest(b"\x11" * 32)
    (proofs / f"{published['event_id']}.ots").write_bytes(other)
    [row] = research_timestamps.status(str(tmp_path), proofs)
    assert row["proof"] == "MISMATCH"


def test_viewer_shows_anchor_and_proof_and_serves_the_file(tmp_path, calendars):
    published = event(ANCHOR)
    (tmp_path / "node-0").mkdir()
    ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json")).add_block(
        {"origin": 0, "index": 1, "hash_hex": "ab", "research_provenance": published})
    research_timestamps.stamp_all(str(tmp_path), tmp_path / "timestamps", research_timestamps.DEFAULT_CALENDARS)

    server = ThreadingHTTPServer(("127.0.0.1", 0), research_viewer.make_handler(str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        [ev] = json.loads(urllib.request.urlopen(url + "/api/events", timeout=5).read())
        assert ev["time_anchor"]["height"] == 912345 and ev["timestamp_proof"] == "pending"
        record = json.loads(urllib.request.urlopen(url + "/api/records?limit=1", timeout=5).read())[0]
        assert record["not_before_bitcoin_block"] == 912345
        proof = urllib.request.urlopen(url + f"/api/timestamps/{published['event_id']}.ots", timeout=5).read()
        assert research_timestamps.load_proof(proof).file_digest == research_timestamps.event_digest(published)
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(url + "/api/timestamps/../../x.ots", timeout=5)
    finally:
        server.shutdown()
        server.server_close()
