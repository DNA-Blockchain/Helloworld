import json

import pytest

import dna_shell
import local_ai_retrieval
from research_catalog import ResearchCatalog


def test_assistant_uses_local_ollama_with_cited_catalog_context(tmp_path, monkeypatch):
    catalog = ResearchCatalog(tmp_path / "catalog.sqlite3")
    catalog.add_records([{
        "source": "pubmed",
        "external_id": "123",
        "title": "A BRCA1 study",
        "abstract": "A synthetic finding about BRCA1.",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
        "classification": "public",
    }])
    requests = []

    class Response:
        status = 200

        def read(self):
            return b'{"response":"The record reports a synthetic finding [1]."}'

    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "127.0.0.1"
            assert port == 11434
            assert timeout == 120

        def request(self, method, path, body, headers):
            requests.append((method, path, json.loads(body), headers))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(local_ai_retrieval.http.client, "HTTPConnection", Connection)
    result = local_ai_retrieval.LocalResearchAssistant(catalog).answer(
        "BRCA1", model="local-test-model"
    )

    assert result["answer"] == "The record reports a synthetic finding [1]."
    assert result["citations"][0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/123/"
    assert result["automatic_provider_transfer"] is False
    method, path, payload, headers = requests[0]
    assert (method, path) == ("POST", "/api/generate")
    assert payload["model"] == "local-test-model"
    assert payload["stream"] is False
    assert "untrusted source material" in payload["prompt"]
    assert headers["Content-Type"] == "application/json"


@pytest.mark.parametrize("endpoint", [
    "http://ollama.example:11434",
    "http://192.0.2.1:11434",
    "https://127.0.0.1:11434",
    "http://127.0.0.1:11434/path",
    "http://127.0.0.1:0",
])
def test_assistant_rejects_non_loopback_or_non_base_endpoints(tmp_path, endpoint):
    with pytest.raises(ValueError, match="endpoint"):
        local_ai_retrieval.LocalResearchAssistant(
            ResearchCatalog(tmp_path / "catalog.sqlite3"), endpoint=endpoint
        )


def test_assistant_surfaces_local_ollama_http_errors(tmp_path, monkeypatch):
    class Response:
        status = 503

        def read(self):
            return b'{"error":"model unavailable"}'

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
    catalog = ResearchCatalog(tmp_path / "catalog.sqlite3")
    catalog.add_records([{
        "source": "pubmed",
        "external_id": "123",
        "title": "A matching question record",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
        "classification": "public",
    }])
    assistant = local_ai_retrieval.LocalResearchAssistant(catalog)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        assistant.answer("matching question", model="missing-model")


def test_assistant_abstains_without_contacting_model_when_catalog_has_no_match(
    tmp_path, monkeypatch
):
    def unexpected_connection(*args, **kwargs):
        raise AssertionError("an empty retrieval must not call the model")

    monkeypatch.setattr(
        local_ai_retrieval.http.client, "HTTPConnection", unexpected_connection
    )
    result = local_ai_retrieval.LocalResearchAssistant(
        ResearchCatalog(tmp_path / "catalog.sqlite3")
    ).answer("no matching topic", model="local-test-model")

    assert result["citations"] == []
    assert result["backend"] == "local-catalog"
    assert "no matching records" in result["answer"]


def test_catalog_ask_requires_confirmation_for_sensitive_records(tmp_path, monkeypatch):
    calls = []

    class Assistant:
        def __init__(self, catalog, endpoint):
            calls.append(("init", endpoint))

        def answer(self, query, *, model, classification, limit):
            calls.append((query, model, classification, limit))
            return {"answer": "local answer"}

    monkeypatch.setattr(dna_shell, "LocalResearchAssistant", Assistant)
    with pytest.raises(SystemExit) as error:
        dna_shell.main([
            "catalog-ask", "private cohort", "--model", "local-model",
            "--classification", "private", "--catalog", str(tmp_path / "catalog.sqlite3"),
        ])

    assert error.value.code == 2
    assert calls == []


def test_catalog_ask_invokes_local_assistant_after_sensitive_confirmation(
    tmp_path, monkeypatch, capsys
):
    calls = []

    class Assistant:
        def __init__(self, catalog, endpoint):
            calls.append(("init", endpoint))

        def answer(self, query, *, model, classification, limit):
            calls.append((query, model, classification, limit))
            return {"answer": "local answer"}

    monkeypatch.setattr(dna_shell, "LocalResearchAssistant", Assistant)
    assert dna_shell.main([
        "catalog-ask", "private cohort", "--model", "local-model",
        "--classification", "private", "--confirm-local-sensitive-context",
        "--catalog", str(tmp_path / "catalog.sqlite3"),
    ]) == 0

    assert calls == [
        ("init", "http://127.0.0.1:11434"),
        ("private cohort", "local-model", "private", 5),
    ]
    assert json.loads(capsys.readouterr().out) == {"answer": "local answer"}
