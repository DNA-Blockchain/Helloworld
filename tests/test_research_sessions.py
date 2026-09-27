import json
import uuid

import pytest

import dna_shell
import local_ai_retrieval
from research_catalog import ResearchCatalog
from research_sessions import ResearchSessionStore


def test_session_store_saves_lists_recalls_and_forgets_locally(tmp_path):
    store = ResearchSessionStore(tmp_path / "sessions.sqlite3")
    saved = store.save(
        query="BRCA1",
        answer="A cited answer [1].",
        model="llama3.2",
        sources=["clinvar", "ensembl", "clinvar"],
        citations=[{"id": "[1]", "url": "https://example.org/record"}],
        records_fetched=2,
    )

    listed = store.list()
    recalled = store.get(saved["session_id"])

    assert listed[0]["session_id"] == saved["session_id"]
    assert listed[0]["sources"] == ["clinvar", "ensembl"]
    assert recalled["answer"] == "A cited answer [1]."
    assert recalled["citations"][0]["url"] == "https://example.org/record"
    assert recalled["storage"] == "local-only"
    store.forget(saved["session_id"])
    assert store.list() == []
    with pytest.raises(KeyError, match="not found"):
        store.get(saved["session_id"])


def test_session_store_validates_ids_and_list_limits(tmp_path):
    store = ResearchSessionStore(tmp_path / "sessions.sqlite3")

    with pytest.raises(ValueError, match="UUID"):
        store.get("not-an-id")
    with pytest.raises(KeyError, match="not found"):
        store.get(uuid.uuid4().hex)
    with pytest.raises(ValueError, match="limit"):
        store.list(limit=0)


def test_research_ask_does_not_persist_session_without_opt_in(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dna_shell, "search_public_sources", lambda *args, **kwargs: [])

    class Assistant:
        def __init__(self, catalog, endpoint):
            pass

        def answer(self, query, *, model, classification, limit):
            return {
                "query": query,
                "answer": "No matching evidence.",
                "model": model,
                "citations": [],
            }

    monkeypatch.setattr(dna_shell, "LocalResearchAssistant", Assistant)
    session_path = tmp_path / "sessions.sqlite3"
    catalog_path = tmp_path / "catalog.sqlite3"
    assert dna_shell.main([
        "research-ask", "public question", "--sources", "clinvar",
        "--model", "local-model", "--confirm-public-query",
        "--catalog", str(catalog_path), "--session-store", str(session_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert "saved_session_id" not in output
    assert not session_path.exists()


def test_research_ask_saves_explicit_local_recall_record(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dna_shell, "search_public_sources", lambda query, sources, max_results: [{
        "source": "clinvar",
        "external_id": "VCV000001",
        "title": "BRCA1 test record",
        "abstract": "evidence",
        "source_url": "https://example.org/record",
        "classification": "public",
    }])

    class Response:
        status = 200

        def read(self):
            return b'{"response":"A locally generated cited answer [1]."}'

    class Connection:
        def __init__(self, host, port, timeout):
            pass

        def request(self, method, path, body, headers):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(local_ai_retrieval.http.client, "HTTPConnection", Connection)
    session_path = tmp_path / "sessions.sqlite3"
    assert dna_shell.main([
        "research-ask", "BRCA1", "--sources", "clinvar", "--model", "llama3.2",
        "--confirm-public-query", "--save-session",
        "--session-store", str(session_path),
        "--catalog", str(tmp_path / "catalog.sqlite3"),
    ]) == 0

    response = json.loads(capsys.readouterr().out)
    recalled = ResearchSessionStore(session_path).get(response["saved_session_id"])
    assert recalled["query"] == "BRCA1"
    assert recalled["answer"] == "A locally generated cited answer [1]."
    assert recalled["sources"] == ["clinvar"]
    assert recalled["citations"][0]["url"] == "https://example.org/record"
    assert recalled["storage"] == "local-only"

    assert dna_shell.main([
        "research-history", "--session-store", str(session_path)
    ]) == 0
    history = json.loads(capsys.readouterr().out)
    assert history["sessions"][0]["session_id"] == response["saved_session_id"]
    assert "answer" not in history["sessions"][0]

    assert dna_shell.main([
        "research-forget", response["saved_session_id"],
        "--session-store", str(session_path),
    ]) == 0
    capsys.readouterr()
    assert ResearchSessionStore(session_path).list() == []
