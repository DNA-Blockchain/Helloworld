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


def test_plan_ranks_every_topic_in_one_kernel_boot(monkeypatch):
    boots = []

    def fake_batch(requests):
        boots.append([request["query"] for request in requests])
        return [research_analysis.run(request) for request in requests]

    monkeypatch.setattr(research_queue, "rank_batch_in_kernel", fake_batch)
    events, notes = run_plan(kernel=True)
    assert boots == [["Metastatic Breast Cancer BRCA1", "Ovarian Neoplasms BRCA1", "Neoplasms BRCA1"]]
    assert len(events) == 3 and all("in the kernel" in n for n in notes)


def test_batches_are_split_at_the_kernel_limit(monkeypatch):
    boots = []
    monkeypatch.setattr(research_queue, "KERNEL_BATCH", 2)
    monkeypatch.setattr(research_queue, "rank_batch_in_kernel",
                        lambda requests: boots.append(len(requests)) or [research_analysis.run(r) for r in requests])
    events, _ = run_plan(kernel=True)
    assert boots == [2, 1] and len(events) == 3


def test_kernel_rejections_and_failed_boots_are_reported(monkeypatch):
    def partly_rejected(requests):
        return [None if r["query"].startswith("Ovarian") else research_analysis.run(r) for r in requests]

    monkeypatch.setattr(research_queue, "rank_batch_in_kernel", partly_rejected)
    events, notes = run_plan(kernel=True)
    assert [e["query"] for e in events] == ["Metastatic Breast Cancer BRCA1", "Neoplasms BRCA1"]
    assert any("Ovarian Neoplasms BRCA1: ranking failed" in n for n in notes)

    def boot_fails(requests):
        raise RuntimeError("kernel ranking failed: boom")

    monkeypatch.setattr(research_queue, "rank_batch_in_kernel", boot_fails)
    events, notes = run_plan(kernel=True)
    assert events == [] and any("kernel batch of 3 failed" in n for n in notes)


class Round:
    def __init__(self, round_no):
        self.round_no = round_no


def test_shared_topic_research_rotates_and_skips_published_topics(tmp_path):
    store = tmp_path / "store.json"
    store.write_text(json.dumps(STORE))
    shared = research_queue.SharedTopicResearch(tmp_path, [store], None, sources=["pubmed"])
    # three pending topics; round 4 starts at 4 % 3 = 1
    result = shared(Round(4))
    assert result["research_event"]["query"] == "Ovarian Neoplasms BRCA1"
    validate_public_provenance(result["research_event"])

    from research_ledger import ResearchLedger
    (tmp_path / "node-0").mkdir()
    ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json")).add_block(
        {"origin": 0, "index": 1, "hash_hex": "ab", "research_provenance": result["research_event"]})
    # the published topic drops out of the rotation: [Metastatic, Neoplasms], 4 % 2 = 0
    assert shared(Round(4))["research_event"]["query"] == "Metastatic Breast Cancer BRCA1"
    assert research_queue.SharedTopicResearch(tmp_path, [tmp_path / "none.json"], None)(Round(1)) == {
        "source": "research_queue", "status": "queue empty"}


def test_cli_dry_run_then_confirm(tmp_path, capsys):
    store = tmp_path / "store.json"
    store.write_text(json.dumps(STORE))
    outbox = tmp_path / "outbox"
    args = ["--store", str(store), "--no-live-store", "--ledgers", str(tmp_path), "--outbox", str(outbox)]
    assert research_queue.main(args) == 0
    assert "3 event(s)" in capsys.readouterr().out and not outbox.exists()
    assert research_queue.main(args + ["--confirm-publication", "--limit", "2"]) == 0
    assert len(list(outbox.glob("*.json"))) == 2
