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
import sqlite3

import pytest

import research_analysis
import research_fetch
import research_queue
from research_provenance import validate_public_provenance

STORE = {"topics": {}, "queue": [["Metastatic Breast Cancer", "BRCA1"], ["Ovarian Neoplasms", "BRCA1"],
                                  ["metastatic breast cancer", "brca1"], ["Neoplasms", "BRCA1"], "bad-entry"]}


def fake_fetch(query, terms, sources, max_results):
    base = query.split()[0].lower()
    return {
        "schema": research_analysis.INPUT_SCHEMA, "query": query, "terms": terms, "fetched_at": "t",
        "records": [
            {"source": "pubmed", "external_id": f"{base}-{i}", "title": f"{query} study {i}", "abstract": "",
             "source_url": "https://example.invalid", "published_at": "2025", "classification": "public"}
            for i in range(3)
        ] + [{"source": "pubmed", "external_id": "shared-1", "title": f"Shared {query}", "abstract": "",
              "source_url": "https://example.invalid", "published_at": "2024", "classification": "public"}],
    }


@pytest.fixture(autouse=True)
def offline_fetch(monkeypatch):
    monkeypatch.setattr(research_fetch, "fetch", fake_fetch)


def test_queued_topics_dedupe_across_store_and_live_store(tmp_path):
    store = tmp_path / "store.json"
    store.write_text(json.dumps(STORE))
    db = tmp_path / "live_store.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE snapshots (stream TEXT, key TEXT, updated_at REAL, sha256 TEXT, data TEXT)")
    connection.execute("INSERT INTO snapshots VALUES ('research', 'crispr_store', 0, '', ?)",
                       (json.dumps({"topics": {}, "queue": [["Ovarian Neoplasms", "BRCA1"], ["Solid Tumor", "BRCA1"]]}),))
    connection.commit()
    connection.close()

    topics = research_queue.queued_topics([store], db)
    assert topics == [("Metastatic Breast Cancer", "BRCA1"), ("Ovarian Neoplasms", "BRCA1"),
                      ("Neoplasms", "BRCA1"), ("Solid Tumor", "BRCA1")]


def run_plan(**overrides):
    options = dict(sources=["pubmed"], max_results=5, kernel=False, already_published=set(), already_queried=set())
    options.update(overrides)
    return research_queue.plan([("Metastatic Breast Cancer", "BRCA1"), ("Ovarian Neoplasms", "BRCA1"),
                                ("Neoplasms", "BRCA1")], **options)


def test_plan_ranks_each_topic_and_never_repeats_a_record():
    events, notes = run_plan()
    assert [e["query"] for e in events] == ["Metastatic Breast Cancer BRCA1", "Ovarian Neoplasms BRCA1",
                                            "Neoplasms BRCA1"]
    ids = [r["external_id"] for e in events for r in e["records"]]
    assert ids.count("shared-1") == 1          # published with the first topic only
    for event in events:
        validate_public_provenance(event)


def test_plan_skips_published_topics_and_records_and_honours_limit():
    events, notes = run_plan(already_queried={"ovarian neoplasms brca1"},
                             already_published={("pubmed", "metastatic-0")}, limit=1)
    assert [e["query"] for e in events] == ["Metastatic Breast Cancer BRCA1"]
    assert "metastatic-0" not in [r["external_id"] for r in events[0]["records"]]
    assert any("Ovarian Neoplasms BRCA1: already published" in n for n in notes)


def test_plan_can_rank_in_the_kernel(monkeypatch):
    calls = []

    def fake_kernel(request):
        calls.append(request["query"])
        return research_analysis.run(request)

    monkeypatch.setattr(research_queue, "rank_in_kernel", fake_kernel)
    events, notes = run_plan(kernel=True, limit=2)
    assert calls == ["Metastatic Breast Cancer BRCA1", "Ovarian Neoplasms BRCA1"]
    assert all("in the kernel" in n for n in notes)


def test_kernel_failure_is_reported_and_other_topics_continue(monkeypatch):
    def flaky(request):
        if request["query"].startswith("Ovarian"):
            raise RuntimeError("kernel ranking failed: boom")
        return research_analysis.run(request)

    monkeypatch.setattr(research_queue, "rank_in_kernel", flaky)
    events, notes = run_plan(kernel=True)
    assert [e["query"] for e in events] == ["Metastatic Breast Cancer BRCA1", "Neoplasms BRCA1"]
    assert any("ranking failed" in n for n in notes)


def test_cli_dry_run_then_confirm(tmp_path, capsys):
    store = tmp_path / "store.json"
    store.write_text(json.dumps(STORE))
    outbox = tmp_path / "outbox"
    args = ["--store", str(store), "--no-live-store", "--ledgers", str(tmp_path), "--outbox", str(outbox)]
    assert research_queue.main(args) == 0
    assert "3 event(s)" in capsys.readouterr().out and not outbox.exists()
    assert research_queue.main(args + ["--confirm-publication", "--limit", "2"]) == 0
    assert len(list(outbox.glob("*.json"))) == 2
