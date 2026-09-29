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
