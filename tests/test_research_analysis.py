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

import pytest

import research_analysis
import research_fetch


def fixture():
    return json.loads(json.dumps(research_fetch.FIXTURE_REQUEST))


def test_fixture_ranking_dedupes_and_orders_by_score():
    result = research_analysis.run(fixture())

    assert result["schema"] == research_analysis.OUTPUT_SCHEMA
    assert result["input_records"] == 5
    assert result["unique_records"] == 3
    assert result["duplicates_removed"] == 2
    assert [entry["external_id"] for entry in result["ranked"]] == ["SYNTH-PM-1", "SYNTH-CT-1", "SYNTH-PM-2"]
    top = result["ranked"][0]
    assert top["also_in"] == ["europe_pmc"]
    assert top["matched_terms"] == ["crispr", "cancer", "g>a"]
    assert top["score"] == 3 * 3 + 3 * 1 + 1  # title + abstract + recent
    assert result["ranked"][2]["score"] == 0


def test_hashes_are_deterministic_and_content_bound():
    first = research_analysis.run(fixture())
    second = research_analysis.run(fixture())
    assert first["all_records_sha256"] == second["all_records_sha256"]

    changed = fixture()
    changed["records"][3]["title"] = "Different title"
    assert research_analysis.run(changed)["all_records_sha256"] != first["all_records_sha256"]


def test_year_parsing_and_title_key():
    assert research_analysis.publication_year("2024 Mar 5") == 2024
    assert research_analysis.publication_year("FY 12, 2021") == 2021
    assert research_analysis.publication_year("") == 0
    assert research_analysis.title_key("CRISPR: G>A, Base-Editing.") == "crispr g a base editing"


@pytest.mark.parametrize("patch, message", [
    ({"schema": "other"}, "research-input.v1"),
    ({"records": [{"source": "hospital_db", "external_id": "1", "title": "x"}]}, "public source"),
    ({"records": [{"source": "pubmed", "external_id": "1", "title": "x", "classification": "private"}]}, "only public"),
    ({"records": [{"source": "pubmed", "external_id": "", "title": "x"}]}, "external_id"),
    ({"terms": []}, "query term"),
])
def test_rejects_invalid_input(patch, message):
    request = fixture()
    request.update(patch)
    with pytest.raises(ValueError, match=message):
        research_analysis.run(request)


def test_output_is_capped_for_kernel_output_file():
    request = fixture()
    request["records"] = [
        {"source": "pubmed", "external_id": f"SYNTH-{i}", "title": f"CRISPR cancer study number {i} " + "x" * 150,
         "abstract": "", "source_url": "https://example.invalid/" + "y" * 250, "published_at": "2024",
         "classification": "public"}
        for i in range(60)
    ]
    result = research_analysis.run(request)
    assert len(research_analysis.canonical_json(result)) <= research_analysis.MAX_OUTPUT_BYTES
    assert 0 < len(result["ranked"]) <= research_analysis.MAX_RANKED


def test_entrypoint_writes_declared_output(tmp_path, monkeypatch, capsys):
    (tmp_path / "RESEARCH.JSON").write_text(json.dumps(fixture()))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(research_analysis.sys, "platform", "network-os")
    assert research_analysis.main(["RESEARCH.PY"]) == 0
    written = json.loads((tmp_path / "RANKED.OUT").read_text())
    assert written == json.loads(capsys.readouterr().out)
    assert written["ranked"][0]["external_id"] == "SYNTH-PM-1"


def test_fetch_keeps_public_records_trims_and_fits_kernel_limit(monkeypatch):
    records = [
        {"source": "pubmed", "external_id": str(i), "title": f"CRISPR paper {i}", "abstract": "a" * 5000,
         "source_url": "https://example.invalid", "published_at": "2024", "classification": "public",
         "rights_status": "dropped"}
        for i in range(150)
    ]
    records.append({"source": "pubmed", "external_id": "p", "title": "private", "classification": "private"})
    records.append({"source": "unknown", "external_id": "u", "title": "unknown source"})
    import research_catalog

    monkeypatch.setattr(research_catalog, "search_public_sources", lambda query, sources, max_results: records)
    request = research_fetch.fetch("CRISPR cancer", [], ["pubmed"], 100)

    assert request["terms"] == ["crispr", "cancer"]
    assert all(r["classification"] == "public" and len(r["abstract"]) <= 400 for r in request["records"])
    assert all(set(r) == set(research_fetch.KEPT_FIELDS) for r in request["records"])
    assert len(json.dumps(request).encode()) <= research_analysis.MAX_INPUT_BYTES
    research_analysis.run(request)


def test_fetch_cli_fixture_writes_input(tmp_path, capsys):
    output = tmp_path / "RESEARCH.JSON"
    assert research_fetch.main(["--fixture", "--output", str(output), "--analyze"]) == 0
    assert json.loads(output.read_text())["schema"] == research_analysis.INPUT_SCHEMA
    assert "SYNTH-PM-1" in capsys.readouterr().out
