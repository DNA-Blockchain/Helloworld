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

import pytest

import blockchain_dna_tool as tool


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


def test_interpret_records_rejects_missing_source_provenance():
    with pytest.raises(tool.ToolInputError, match="source"):
        tool.interpret_records([{"id": "123"}])


def test_research_request_returns_source_ids_and_status(monkeypatch):
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
                "source_status": {
                    "pubmed": {"status": "ok"},
                    "stjude": {"status": "skipped"},
                },
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
    assert response["result"]["sources"]["stjude"]["status"]["status"] == "skipped"
    assert "not written" in response["result"]["chain"]


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
