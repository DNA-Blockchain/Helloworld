"""The research data pipeline report: figures for every stage, read-only, valid against its schema."""
import hashlib
import json
import time

import pytest

import node_supervisor
from rabbitsoft import contracts, pipeline_report
from rabbitsoft.assistant import Session
from tests.test_rabbitsoft import FakeAI, make_os

RECORDS = [
    {"source": "pubmed", "external_id": "1", "title": "Base editing in sickle cell disease",
     "abstract": "A phase 1 trial.", "source_url": "https://example.org/1", "published_at": "2019 Mar",
     "classification": "public"},
    {"source": "pubmed", "external_id": "2", "title": "Prime editing", "abstract": "", "source_url": "https://example.org/2",
     "published_at": "2024", "classification": "public"},
    {"source": "nih_reporter", "external_id": "R01", "title": "Gene therapy grant", "abstract": "Aims.",
     "source_url": "https://example.org/r01", "published_at": "2026", "classification": "public"},
]


@pytest.fixture
def populated(tmp_path):
    from audit_trail import AuditTrail
    from corpus_vector_store import CorpusVectorStore, _text_sha
    from research_catalog import ResearchCatalog

    now = time.time()
    paths = make_os(tmp_path, now)
    catalog = ResearchCatalog(paths.catalog)
    catalog.add_records(RECORDS)
    CorpusVectorStore(store_path=str(paths.corpus)).sync_from_catalog(catalog)
    state = json.loads(paths.corpus.read_text())
    doc = state["documents"][0]
    state["vectors"] = {doc["id"]: {"model": "nomic-embed-text", "text_sha256": _text_sha(doc["text"]), "vector": [1.0]}}
    paths.corpus.write_text(json.dumps(state))
    trail = AuditTrail(str(paths.audit))
    trail.log("rabbitsoft", "public_search", "pc", {"records": 7})
    trail.log("rabbitsoft", "abstracts_fetched", "pc", {"asked": 4, "filled": 3})
    trail.log("rabbitsoft", "model_server_used", "pc", {"fell_back": True})
    trail.log("rabbitsoft", "training_answer_shared", "pc", {})
    lora = tmp_path / "ollama" / "nos-lora"
    lora.mkdir(parents=True)
    (lora / "kept.jsonl").write_text('{"task": "explain"}\n{"task": "summary"}\n{"task": "explain"}\n')
    (lora / "rejected.jsonl").write_text('{"task": "explain"}\n')
    integrity = paths.autonomous / "integrity"
    integrity.mkdir()
    (integrity / "integrity-20261001T000000.json").write_text(json.dumps({
        "schema": "rabbitsoft-integrity.v1", "created_at": "2026-10-01T00:00:00+00:00", "ok": False,
        "checks": [{"role": "records and data", "name": "Node chains", "status": "ok", "lines": []},
                   {"role": "code enforcement", "name": "Code fingerprint", "status": "problem", "lines": []}]}))
    return paths, now


def test_every_stage_is_measured_and_fits_the_schema(populated):
    paths, now = populated
    report = pipeline_report.build(paths, now=now, since=now - 3600)
    assert not contracts.errors(report, "pipeline-report-v1", "report")
    cat = report["ingestion"]["catalog"]
    assert (cat["records"], cat["with_abstract"], cat["new_in_period"]) == (3, 2, 3)
    assert cat["sources"]["pubmed"] == {"records": 2, "with_abstract": 1, "new_in_period": 2, "published": "2019-2024"}
    assert report["ingestion"]["agent"]["ids_by_source"] == {"pubmed": 2, "clinicaltrials": 1}
    assert (report["ingestion"]["public_searches"], report["ingestion"]["records_returned"],
            report["ingestion"]["abstracts_filled"], report["ingestion"]["abstracts_requested"]) == (1, 7, 3, 4)
    corpus = report["corpus"]
    assert corpus["documents"] == 3 and corpus["current_vectors"] == {"nomic-embed-text": 1}
    assert corpus["method"] == "tfidf" and corpus["catalog_records_missing"] == 0     # 1 of 3 isn't a full index
    model = report["model"]
    assert model["training"] == {"explain": {"kept": 2, "rejected": 1}, "summary": {"kept": 1, "rejected": 0}}
    assert (model["hosted_questions"], model["hosted_fallbacks"], model["training_answers_shared"]) == (1, 1, 1)
    assert report["nodes"]["node-0"]["research_ledger"] == 40 and report["nodes"]["node-1"]["audits"] == 1
    raw = (paths.autonomous / "integrity" / "integrity-20261001T000000.json").read_bytes()
    assert report["integrity"]["fingerprint"] == hashlib.sha256(raw).hexdigest()
    assert report["integrity"]["problems"] == ["Code fingerprint"]


def test_the_period_decides_what_counts_as_new(populated):
    paths, now = populated
    later = pipeline_report.build(paths, now=now + 7200, since=now + 3600)
    assert later["ingestion"]["catalog"]["new_in_period"] == 0 and later["ingestion"]["public_searches"] == 0
    assert later["ingestion"]["catalog"]["records"] == 3               # totals don't depend on the period


def test_the_text_report_carries_the_figures(populated):
    paths, now = populated
    text = "\n".join(pipeline_report.render(pipeline_report.build(paths, now=now, since=now - 3600)))
    assert "Catalog: 3 records (3 new), abstracts for 2 (67%)" in text
    assert "| pubmed | 2 | 2 | 1 (50%) | 2019-2024 |" in text
    assert "1 public search returning 7 records; 3 of 4 requested abstracts filled" in text
    assert "explain 2 kept / 1 rejected (67% accepted)" in text
    assert "1 question to the hosted model (1 fell back to this PC), 1 answer shared for training" in text
    assert "| node-0 | yes | 100 | intact | 2 | 40 | 1 (0) | 0 / 0 |" in text
    assert "PROBLEMS (ok 1, problem 1); problems: Code fingerprint" in text


def test_it_only_reads(tmp_path):
    now = time.time()
    paths = make_os(tmp_path, now)
    report = pipeline_report.build(paths, now=now)
    assert not contracts.errors(report, "pipeline-report-v1", "report")
    assert report["ingestion"]["catalog"] is None and report["corpus"] is None and report["integrity"] is None
    assert not paths.catalog.exists() and not paths.corpus.exists() and not paths.audit.exists()
    text = "\n".join(pipeline_report.render(report))
    assert "No research catalog on this PC yet." in text and "No integrity report yet." in text


def test_chat_and_daily_report_include_it(populated, monkeypatch):
    paths, now = populated
    s = Session(paths, ai=FakeAI())
    assert s.handle("show me the data mining report").text.startswith("Research data pipeline, ")
    assert "Research data pipeline report" in s.handle("help").choices
    section = node_supervisor.pipeline_section(now - 3600, now, paths)
    assert section.startswith("\n## Research data pipeline\n\n") and "Catalog: 3 records" in section
    monkeypatch.setattr(pipeline_report, "build", lambda *a, **k: 1 / 0)
    assert "Not available (ZeroDivisionError" in node_supervisor.pipeline_section(now - 3600, now, paths)
