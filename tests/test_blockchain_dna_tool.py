import pytest

import blockchain_dna_tool as tool
from growing_research_agent import GrowingResearchAgent


def test_interpret_records_counts_sources_duplicates_and_missing_urls():
    result = tool.interpret_records([
        {"source": "PubMed", "id": "PMID:123", "url": "https://example.test/123"},
        {"source": "PubMed", "id": "PMID:123"},
        {"source": "ClinicalTrials.gov", "id": "NCT0001", "source_url": "https://example.test/trial"},
    ])

    assert result["record_count"] == 3
    assert result["source_counts"] == {"ClinicalTrials.gov": 1, "PubMed": 2}
    assert result["duplicate_records"] == [{"source": "PubMed", "id": "PMID:123"}]
    assert result["records_missing_source_url"] == [{"source": "PubMed", "id": "PMID:123"}]
    assert "does not assess" in result["interpretation"]


def test_interpret_records_rejects_missing_source_provenance():
    with pytest.raises(tool.ToolInputError, match="source"):
        tool.interpret_records([{"id": "123"}])


def test_research_request_reuses_agent_and_existing_store(monkeypatch):
    class StubAgent:
        def __init__(self, node, dna, store_path):
            assert node is None
            assert dna is None
            assert store_path.endswith("research_store.json")
            self.topics = {}

        async def seed_topic(self, condition, biomarker):
            self.topics["topic-key"] = {
                "last_checked": 123.0,
                "all_ids": {"pubmed": ["PMID:123"], "stjude": []},
                "new_ids_last_run": ["PMID:123"],
                "related_topics_found": [],
            }
            return "topic-key"

    monkeypatch.setattr(tool, "GrowingResearchAgent", StubAgent)
    response = tool.execute_request({
        "action": "research",
        "condition": "example condition",
        "biomarker": "GENE1",
    })

    assert response["ok"] is True
    assert response["result"]["sources"]["pubmed"]["ids"] == ["PMID:123"]
    assert response["result"]["sources"]["pubmed"]["status"]["status"] == "not_reported_by_runtime"
    assert response["result"]["sources"]["stjude"]["record_count"] == 0
    assert response["result"]["sources"]["stjude"]["status"]["status"] == "skipped"
    assert "not_reported_by_runtime" in response["result"]["source_status_note"]
    assert "not written" in response["result"]["chain"]


def test_research_uses_runtime_source_status_when_available(monkeypatch):
    class StubAgent:
        def __init__(self, node, dna, store_path):
            self.topics = {}

        async def seed_topic(self, condition, biomarker):
            self.topics["topic-key"] = {
                "last_checked": 123.0,
                "all_ids": {"pubmed": []},
                "source_status": {"pubmed": {"status": "failed", "error": "offline"}},
            }
            return "topic-key"

    monkeypatch.setattr(tool, "GrowingResearchAgent", StubAgent)
    response = tool.execute_request({"action": "research", "condition": "example"})

    assert response["result"]["sources"]["pubmed"]["status"]["status"] == "failed"
    assert response["result"]["source_status_note"] == "This runtime reports source status."


def test_research_uses_real_agent_fetchers_and_persists_existing_store(monkeypatch):
    async def clinicaltrials(self, condition, biomarker):
        return ["NCT123"], []

    async def pubmed(self, condition, biomarker):
        return ["PMID:123"]

    async def clinvar(self, condition, biomarker):
        return ["ClinVar:123"], []

    async def stjude(self, condition, biomarker):
        return []

    monkeypatch.setattr(GrowingResearchAgent, "_fetch_clinicaltrials", clinicaltrials)
    monkeypatch.setattr(GrowingResearchAgent, "_fetch_pubmed", pubmed)
    monkeypatch.setattr(GrowingResearchAgent, "_fetch_clinvar", clinvar)
    monkeypatch.setattr(GrowingResearchAgent, "_fetch_stjude", stjude)
    store_path = tool.os.path.join(tool.os.getcwd(), "research_store.json")
    assert not tool.os.path.exists(store_path)

    try:
        response = tool.execute_request({
            "action": "research",
            "condition": "offline test condition",
        })
        assert response["result"]["sources"]["clinicaltrials"]["ids"] == ["NCT123"]
        assert tool.os.path.exists(store_path)
        with open(store_path, "r", encoding="utf-8") as store_file:
            persisted = tool.json.load(store_file)
        assert "offline test condition|" in persisted["topics"]
    finally:
        if tool.os.path.exists(store_path):
            tool.os.remove(store_path)


def test_code_execution_requires_both_opt_ins():
    request = {
        "action": "execute_python",
        "code": "print('ok')",
        "user_confirmed": True,
    }
    with pytest.raises(tool.ToolInputError, match="requires"):
        tool.execute_request(request)

    request["user_confirmed"] = False
    with pytest.raises(tool.ToolInputError, match="requires"):
        tool.execute_request(request, allow_code_execution=True)


def test_confirmed_python_execution_has_disclosed_boundary():
    response = tool.execute_request({
        "action": "execute_python",
        "code": "print(1 + 1)",
        "user_confirmed": True,
    }, allow_code_execution=True)

    assert response["result"]["status"] == "completed"
    assert response["result"]["exit_code"] == 0
    assert response["result"]["output"].replace("\r\n", "\n") == "2\n"
    assert "not a security sandbox" in response["result"]["execution_boundary"]
    assert "current user's" in response["result"]["execution_boundary"]


def test_python_execution_timeout_is_reported():
    response = tool.execute_request({
        "action": "execute_python",
        "code": "import time; time.sleep(2)",
        "user_confirmed": True,
        "timeout_seconds": 1,
    }, allow_code_execution=True)

    assert response["result"]["status"] == "timed_out"
    assert response["result"]["exit_code"] is not None


def test_python_execution_caps_captured_output():
    response = tool.execute_request({
        "action": "execute_python",
        "code": "print('x' * 100000)",
        "user_confirmed": True,
    }, allow_code_execution=True)

    assert response["result"]["output_truncated"] is True
    assert len(response["result"]["output"].encode("utf-8")) <= tool.MAX_OUTPUT_BYTES


def test_main_emits_json_error_for_invalid_request(monkeypatch, capsys):
    class Buffer:
        def read(self, size):
            return b'{"action":"unknown"}'

    class Input:
        buffer = Buffer()

    monkeypatch.setattr(tool.sys, "stdin", Input())

    assert tool.main([]) == 2
    assert '"ok": false' in capsys.readouterr().out
