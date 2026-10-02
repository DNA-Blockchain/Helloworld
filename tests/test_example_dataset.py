"""The committed example dataset: its checksums, its records, and the offline check that verifies it."""
import importlib.util
import json
from pathlib import Path

import pytest

from rabbitsoft import contracts
import research_export as ex

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "examples" / "research"
_spec = importlib.util.spec_from_file_location("fetch_example", HERE / "fetch_example.py")
fetch_example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_example)


def manifest():
    return json.loads((HERE / "checksums.json").read_text(encoding="utf-8"))


def test_the_committed_files_match_their_checksums(capsys):
    assert fetch_example.check() == 0
    assert "Every file matches its checksum." in capsys.readouterr().out


def test_a_changed_file_is_caught(tmp_path, monkeypatch, capsys):
    """The check must fail when a file no longer matches, or it is decoration."""
    for name in ("records.jsonl", "checksums.json"):
        (tmp_path / name).write_bytes((HERE / name).read_bytes())
    for name in ("records.bib", "records.ris", "records.csv"):
        (tmp_path / name).write_bytes((HERE / name).read_bytes())
    monkeypatch.setattr(fetch_example, "HERE", tmp_path)
    monkeypatch.setattr(fetch_example, "CHECKSUMS", tmp_path / "checksums.json")
    assert fetch_example.check() == 0
    (tmp_path / "records.bib").write_text("@article{tampered,}\n", encoding="utf-8")
    assert fetch_example.check() == 1
    assert "SHA-256 is" in capsys.readouterr().err
    (tmp_path / "records.bib").unlink()
    assert fetch_example.check() == 1
    assert "missing" in capsys.readouterr().err


def test_the_manifest_records_how_the_dataset_was_made():
    m = manifest()
    assert m["schema"] == "rabbitsoftware-example-dataset.v1"
    assert sorted(m["queries"]) == ["clinicaltrials.gov", "clinvar", "europe_pmc", "nih_reporter", "pubmed"]
    assert m["records"] == sum(m["records_found"].values()) and m["records"] > 0
    assert m["fetched_at"] > 0 and m["fetched_at_human"].endswith("UTC")
    assert sorted(m["files"]) == ["records.bib", "records.csv", "records.jsonl", "records.ris"]
    for entry in m["files"].values():
        assert len(entry["sha256"]) == 64 and entry["bytes"] > 0


def test_every_record_is_traceable_and_fits_the_provenance_schema():
    records = [json.loads(line) for line in (HERE / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(records) == manifest()["records"]
    assert {r["source"] for r in records} == set(manifest()["queries"])
    for record in records:
        assert record["external_id"] and record["title"] and record["citation_key"]
        p = record["provenance"]
        assert p["source_id"] == f"{record['source']}:{record['external_id']}"
        assert p["source_url"].startswith("https://") and p["terms_url"].startswith("https://")
        assert not contracts.errors(p, "provenance-v1", "recordProvenance")
    # Every record type the formats have to handle appears.
    assert {r["record_type"] for r in records} >= {"article", "clinical_trial", "variant", "grant"}


def test_the_other_three_files_describe_the_same_records():
    records = [json.loads(line) for line in (HERE / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    bib = (HERE / "records.bib").read_text(encoding="utf-8")
    ris = (HERE / "records.ris").read_text(encoding="utf-8")
    csv_text = (HERE / "records.csv").read_text(encoding="utf-8")
    assert ris.count("ER  - \n") == len(records) and bib.count("\n@") == len(records) - 1
    assert csv_text.splitlines()[0] == ",".join(ex.CSV_COLUMNS)
    for record in records:
        for text in (bib, ris, csv_text):
            assert record["external_id"] in text, (record["external_id"], text[:40])
    # No source markup survived into any of them.
    for text in (bib, ris, csv_text):
        assert "&lt;" not in text and "<i>" not in text


def test_fetching_asks_first(monkeypatch, capsys):
    monkeypatch.setattr(fetch_example, "HERE", Path("/nonexistent"))
    assert fetch_example.fetch(ask=lambda _: "no") == 1
    assert "Nothing was fetched." in capsys.readouterr().out


def test_the_readme_documents_the_committed_files():
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    for name in manifest()["files"]:
        assert name in readme
    assert "--check" in readme and "no patient data" in readme
