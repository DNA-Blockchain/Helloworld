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

"""Local plain-language summaries: stored locally, hashes only on the chain."""

import json

import pytest

import node_supervisor as sup
import research_analysis
import research_fetch
import research_summaries as rs
import research_viewer
from research_ledger import ResearchLedger
from research_provenance import create_public_research_records_event, validate_public_provenance


class FakeSummarizer:
    model = "llama3.2:3b"

    def __init__(self):
        self.titles = []

    def summarize(self, title):
        self.titles.append(title)
        return f"Plain: {title[:20]}"


def ledger(tmp_path, *events):
    (tmp_path / "node-0").mkdir(exist_ok=True)
    book = ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json"))
    for index, event in enumerate(events, start=len(book) + 1):
        assert book.add_block({"origin": 0, "index": index, "hash_hex": f"{index:02x}",
                               "research_provenance": event})
    return book


def records_event():
    ranking = research_analysis.run(json.loads(json.dumps(research_fetch.FIXTURE_REQUEST)))
    return create_public_research_records_event(ranking, confirm_publication=True)


def test_clean_summary_keeps_one_short_sentence():
    assert rs.clean_summary('  "A study of BRCA1."\n\nExtra notes.') == "A study of BRCA1."
    assert rs.clean_summary("a  \n b") == "a b"
    assert len(rs.clean_summary("x" * 1000)) == rs.MAX_SUMMARY_CHARS
    with pytest.raises(ValueError):
        rs.clean_summary("  ")


@pytest.mark.parametrize("endpoint", ["http://ollama.example:11434", "http://192.0.2.1:11434",
                                      "https://127.0.0.1:11434"])
def test_only_a_local_model_is_ever_contacted(endpoint):
    with pytest.raises(ValueError):
        rs.OllamaSummarizer(endpoint=endpoint)


def test_summaries_are_written_once_saved_locally_and_redone_after_a_title_change(tmp_path):
    ledger(tmp_path, records_event())
    fake = FakeSummarizer()
    assert rs.summarize_pending(tmp_path, fake, limit=2, max_busy=None, log=lambda m: None) == 2
    assert rs.summarize_pending(tmp_path, fake, limit=10, max_busy=None, log=lambda m: None) == 1
    assert rs.summarize_pending(tmp_path, fake, limit=10, max_busy=None, log=lambda m: None) == 0
    store = rs.load_store(tmp_path)
    assert len(store["summaries"]) == 3 and all(e["batch"] is None for e in store["summaries"].values())

    store["summaries"]["pubmed:SYNTH-PM-1"]["title_sha256"] = "0" * 64   # e.g. the title was corrected
    rs.save_store(tmp_path, store)
    assert rs.summarize_pending(tmp_path, fake, limit=10, max_busy=None, log=lambda m: None) == 1


def test_a_busy_pc_stops_the_batch(tmp_path):
    ledger(tmp_path, records_event())
    fake = FakeSummarizer()
    assert rs.summarize_pending(tmp_path, fake, limit=5, max_busy=75, busy=lambda: 95.0, log=lambda m: None) == 0
    assert fake.titles == []


def test_hashes_go_on_chain_and_the_viewer_verifies_them(tmp_path):
    book = ledger(tmp_path, records_event())
    rs.summarize_pending(tmp_path, FakeSummarizer(), limit=5, max_busy=None, log=lambda m: None)
    [event] = rs.publish_pending(tmp_path, tmp_path / "outbox", log=lambda m: None)
    validate_public_provenance(event)
    assert "Plain" not in json.dumps(event)              # no summary text on the chain
    assert event["model"] == "llama3.2:3b" and event["record_count"] == 3
    assert rs.publish_pending(tmp_path, tmp_path / "outbox", log=lambda m: None) == []

    records = {r["external_id"]: r for r in research_viewer.collect(str(tmp_path))["records"]}
    assert records["SYNTH-PM-1"]["summary"]["text"].startswith("Plain")
    assert records["SYNTH-PM-1"]["summary"]["on_chain_event"] is None   # not mined yet

    book.add_block({"origin": 0, "index": 5, "hash_hex": "05", "research_provenance": event})
    records = {r["external_id"]: r for r in research_viewer.collect(str(tmp_path))["records"]}
    assert records["SYNTH-PM-1"]["summary"]["on_chain_event"] == event["event_id"]
    assert "not evidence" in records["SYNTH-PM-1"]["summary"]["note"]

    store = rs.load_store(tmp_path)                        # an edited summary no longer verifies
    store["summaries"]["pubmed:SYNTH-PM-1"]["summary"] = "Edited later"
    rs.save_store(tmp_path, store)
    records = {r["external_id"]: r for r in research_viewer.collect(str(tmp_path))["records"]}
    assert records["SYNTH-PM-1"]["summary"]["on_chain_event"] is None
    assert records["SYNTH-CT-1"]["summary"]["on_chain_event"] == event["event_id"]


def test_supervisor_summarizes_only_while_confirmed(tmp_path, monkeypatch):
    started = []

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            started.append(cmd)

        def poll(self):
            return None

    monkeypatch.setattr(sup.subprocess, "Popen", FakeProc)
    s = sup.Supervisor(sup.Config(base_dir=str(tmp_path), node_count=0, python="python"))
    s.maybe_summarize(10_000.0)
    assert started == []
    open(s.cfg.path(sup.SUMMARIES_CONFIRMATION), "w").close()
    s.maybe_summarize(10_000.0)
    s.maybe_summarize(10_001.0)                           # still running: no overlap
    assert len(started) == 1 and "--confirm-publication" in started[0]
