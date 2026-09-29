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

import io
import json

import pytest

import multi_source_research
import public_variant_sources
import research_backfill
import research_matcher
from research_ledger import ResearchLedger, published_record_keys
from research_provenance import validate_public_provenance

STORE = {
    "topics": {
        "breast cancer|brca1": {
            "condition": "breast cancer",
            "biomarker": "BRCA1",
            "all_ids": {
                "pubmed": [f"PMID:{100 + i}" for i in range(25)],
                "clinicaltrials": ["NCT00000001", "NCT00000002"],
                "clinvar": ["ClinVar:555"],
                "stjude": ["SJ-1"],
                "europepmc": [],
            },
        }
    },
    "queue": [],
}


@pytest.fixture
def fake_sources(monkeypatch):
    calls = []

    def pubmed(ids):
        calls.append(("pubmed", list(ids)))
        return [{"source": "pubmed", "external_id": i, "title": f"BRCA1 breast cancer paper {i}",
                 "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{i}/", "published_at": "2025"}
                for i in ids if i != "124"]   # one PMID not returned

    def trials(ids):
        calls.append(("clinicaltrials.gov", list(ids)))
        return [{"source": "clinicaltrials.gov", "external_id": i, "title": f"BRCA1 trial {i}",
                 "source_url": f"https://clinicaltrials.gov/study/{i}", "published_at": "2024-01"} for i in ids]

    def clinvar(ids):
        calls.append(("clinvar", list(ids)))
        return [{"source": "clinvar", "external_id": "VCV000000555", "title": "NM_007294.4(BRCA1):c.68_69del",
                 "abstract": "{}", "source_url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/555/",
                 "published_at": "", "classification": "public"}]

    monkeypatch.setattr(research_backfill, "FETCHERS", {
        "pubmed": ("pubmed", pubmed),
        "clinicaltrials": ("clinicaltrials.gov", trials),
        "clinvar": ("clinvar", clinvar),
    })
    return calls


def store_groups():
    return research_backfill.groups_from_store(STORE, "research_store.json")


def test_plan_fetches_by_bare_id_and_batches_twenty_per_event(fake_sources):
    batches, notes = research_backfill.plan(store_groups(), set())

    assert ("pubmed", [str(100 + i) for i in range(25)]) in fake_sources
    assert ("clinvar", ["555"]) in fake_sources
    sizes = [(b["ranked"][0]["source"], len(b["ranked"])) for b in batches]
    assert sizes == [("pubmed", 20), ("pubmed", 4), ("clinicaltrials.gov", 2), ("clinvar", 1)]
    assert any("stjude IDs skipped" in note for note in notes)
    assert any("pubmed 25 IDs, 0 already published or planned, 24 fetched, 24 to publish" in note for note in notes)
    for batch in batches:
        validate_public_provenance(
            research_backfill.create_public_research_records_event(batch, confirm_publication=True))


def test_plan_skips_published_ids_before_fetching(fake_sources):
    published = {("pubmed", str(100 + i)) for i in range(20)} | {("clinvar", "VCV000000555")}
    batches, notes = research_backfill.plan(store_groups(), published)
    sizes = [(b["ranked"][0]["source"], len(b["ranked"])) for b in batches]
    assert sizes == [("pubmed", 4), ("clinicaltrials.gov", 2)]
    assert ("pubmed", [str(120 + i) for i in range(5)]) in fake_sources   # only the unpublished ones
    assert any("20 already published" in note for note in notes)


def test_records_planned_from_one_source_are_not_repeated_from_another(fake_sources):
    corpus = [{"condition": "breast cancer", "biomarker": "BRCA1",
               "new_ids": ["NCT00000001", "NCT00000003", "PMID:100", "ClinVar:555", "odd-id"]}]
    groups = store_groups() + research_backfill.groups_from_corpus(corpus, "live_store corpus")
    batches, notes = research_backfill.plan(groups, set())
    corpus_batches = batches[4:]
    assert [(b["ranked"][0]["source"], [r["external_id"] for r in b["ranked"]]) for b in corpus_batches] == [
        ("clinicaltrials.gov", ["NCT00000003"])]
    assert any("1 unrecognized IDs skipped" in note for note in notes)


def test_classify_id():
    assert research_backfill.classify_id("NCT01234567") == "clinicaltrials"
    assert research_backfill.classify_id("PMID:42801735") == "pubmed"
    assert research_backfill.classify_id("ClinVar:4935332") == "clinvar"
    assert research_backfill.classify_id("SJ-1") is None


def test_live_store_groups_read_research_stores_and_corpus(tmp_path):
    import sqlite3

    db = tmp_path / "live_store.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE snapshots (stream TEXT, key TEXT, updated_at REAL, sha256 TEXT, data TEXT)")
    connection.executemany("INSERT INTO snapshots VALUES (?, ?, 0, '', ?)", [
        ("research", "crispr_store", json.dumps(STORE)),
        ("corpus", "corpus", json.dumps([{"condition": "c", "biomarker": "b", "new_ids": ["NCT00000009"]}])),
        ("os", "check", json.dumps({"ignored": True})),
    ])
    connection.commit()
    connection.close()

    groups = research_backfill.live_store_groups(db)
    assert [g.label for g in groups] == ["live_store corpus c b", "live_store crispr_store breast cancer|brca1"]
    assert groups[0].ids == {"clinicaltrials": ["NCT00000009"]}
    assert research_backfill.live_store_groups(tmp_path / "missing.db") == []


def test_unreachable_source_is_reported_and_others_continue(fake_sources, monkeypatch):
    def down(ids):
        raise OSError("network unreachable")

    research_backfill.FETCHERS["clinicaltrials"] = ("clinicaltrials.gov", down)
    batches, notes = research_backfill.plan(store_groups(), set())
    assert [b["ranked"][0]["source"] for b in batches] == ["pubmed", "pubmed", "clinvar"]
    assert any("fetch failed" in note for note in notes)


def test_cli_dry_run_then_confirm(tmp_path, fake_sources, capsys):
    store = tmp_path / "store.json"
    store.write_text(json.dumps(STORE))
    outbox = tmp_path / "outbox"
    args = ["--store", str(store), "--no-live-store", "--ledgers", str(tmp_path), "--outbox", str(outbox)]

    assert research_backfill.main(args) == 0
    assert "27 records in 4 event(s)" in capsys.readouterr().out
    assert not outbox.exists()

    assert research_backfill.main(args + ["--confirm-publication"]) == 0
    assert len(list(outbox.glob("*.json"))) == 4


def test_published_record_keys_reads_every_ledger(tmp_path):
    from research_analysis import run
    from research_fetch import FIXTURE_REQUEST
    from research_provenance import create_public_research_records_event

    event = create_public_research_records_event(
        run(json.loads(json.dumps(FIXTURE_REQUEST))), confirm_publication=True)
    (tmp_path / "node-0").mkdir()
    ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json")).add_block(
        {"origin": 0, "index": 1, "research_provenance": event})
    assert ("pubmed", "SYNTH-PM-1") in published_record_keys(str(tmp_path))


# --------------------------------------------------- fetch-by-ID helpers

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_pubmed_summaries_requests_bare_ids(monkeypatch):
    seen = {}

    def fake(url, params):
        seen.update(params)
        return {"result": {"101": {"title": "Paper", "pubdate": "2024 Jan"}}}

    monkeypatch.setattr(multi_source_research, "_http_get_json", fake)
    papers = multi_source_research.pubmed_summaries(["101", "102", "not-a-pmid"])
    assert seen["id"] == "101,102"
    assert papers == [{"pmid": "101", "title": "Paper", "pub_date": "2024 Jan",
                       "url": "https://pubmed.ncbi.nlm.nih.gov/101/"}]


def test_trials_by_id_parses_title_and_start_date(monkeypatch):
    seen = {}

    def fake(request, timeout, context):
        seen["url"] = request.full_url
        return FakeResponse(json.dumps({"studies": [{"protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "briefTitle": "A trial"},
            "statusModule": {"startDateStruct": {"date": "2021-05"}},
        }}]}).encode())

    monkeypatch.setattr(research_matcher.urllib.request, "urlopen", fake)
    trials = research_matcher.trials_by_id(["nct00000001", "bogus"])
    assert "filter.ids=NCT00000001" in seen["url"]
    assert trials == [{"nct_id": "NCT00000001", "title": "A trial", "start_date": "2021-05",
                       "url": "https://clinicaltrials.gov/study/NCT00000001"}]


def test_clinvar_records_by_id_uses_accession(monkeypatch):
    monkeypatch.setattr(public_variant_sources, "_ncbi_get_json", lambda url, params: {"result": {
        "555": {"uid": "555", "accession": "VCV000000555", "title": "NM_007294.4(BRCA1):c.68_69del"}}})
    [record] = public_variant_sources.clinvar_records_by_id(["555", "x"])
    assert record["source"] == "clinvar" and record["external_id"] == "VCV000000555"
    assert record["source_url"] == "https://www.ncbi.nlm.nih.gov/clinvar/variation/555/"
