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

import dna_shell
import research_catalog
from research_catalog import ResearchCatalog, render_cited_context


def test_catalog_stores_and_retrieves_records_with_citations(tmp_path):
    catalog = ResearchCatalog(tmp_path / "catalog.sqlite3")
    catalog.add_records([
        {
            "source": "pubmed",
            "external_id": "123",
            "title": "A study of BRCA1 in breast cancer",
            "abstract": "This synthetic study reviews a biomarker.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
            "classification": "public",
            "rights_status": "unknown",
        },
        {
            "source": "local",
            "external_id": "local-1",
            "title": "Restricted BRCA1 cohort",
            "abstract": "Controlled access data.",
            "source_url": "https://institution.example/record/1",
            "classification": "restricted",
        },
    ])

    results = catalog.retrieve("BRCA1 breast cancer")
    assert len(results) == 1
    assert results[0]["citation"]["record_id"] == "123"
    assert results[0]["citation"]["url"] == "https://pubmed.ncbi.nlm.nih.gov/123/"
    context = render_cited_context("BRCA1 breast cancer", results)
    assert context["citations"][0]["id"] == "[1]"
    assert context["records"][0]["citation_id"] == "[1]"
    assert context["automatic_provider_transfer"] is False
    assert catalog.count() == 2
    assert catalog.count(classification="restricted") == 1


def test_catalog_update_deduplicates_records(tmp_path):
    catalog = ResearchCatalog(tmp_path / "catalog.sqlite3")
    record = {
        "source": "pubmed",
        "external_id": "1",
        "title": "First title",
        "source_url": "https://example.org/1",
        "classification": "public",
    }
    assert catalog.add_records([record]) == 1
    assert catalog.add_records([{**record, "title": "Updated title"}]) == 1
    assert catalog.count() == 1
    assert catalog.retrieve("updated")[0]["citation"]["title"] == "Updated title"


def test_retrieve_requires_valid_classification_limit_and_query(tmp_path):
    catalog = ResearchCatalog(tmp_path / "catalog.sqlite3")
    with pytest.raises(ValueError, match="searchable word"):
        catalog.retrieve("  ")
    with pytest.raises(ValueError, match="limit"):
        catalog.retrieve("anything", limit=0)
    with pytest.raises(ValueError, match="classification"):
        catalog.retrieve("anything", classification="unknown")


def test_public_source_connector_normalizes_existing_sources(monkeypatch):
    monkeypatch.setattr(research_catalog, "search_pubmed", lambda query, max_results: [
        {"pmid": "123", "title": "A paper", "pub_date": "2024", "url": "https://pubmed/123"}
    ])
    monkeypatch.setattr(research_catalog, "find_trials", lambda query, max_results: [
        {"nct_id": "NCT123", "title": "A trial", "url": "https://trials/NCT123"}
    ])
    records = research_catalog.search_public_sources(
        "test query", sources=("pubmed", "clinicaltrials.gov"), max_results=2
    )
    assert [record["source"] for record in records] == ["pubmed", "clinicaltrials.gov"]
    assert records[0]["classification"] == "public"
    assert records[0]["rights_status"].startswith("unknown")
    assert records[1]["external_id"] == "NCT123"


def test_public_source_connector_registers_variant_gene_and_population_sources(monkeypatch):
    monkeypatch.setattr(research_catalog, "search_ncbi_variants", lambda query, database, max_results: [{
        "source": "clinvar" if database == "clinvar" else "dbsnp",
        "external_id": database,
        "title": f"{database} result",
        "source_url": "https://example.org/record",
        "classification": "public",
    }])
    monkeypatch.setattr(research_catalog, "lookup_ensembl_gene", lambda query: [{
        "source": "ensembl",
        "external_id": "ENSG1",
        "title": f"Gene {query}",
        "source_url": "https://example.org/gene",
        "classification": "public",
    }])
    monkeypatch.setattr(research_catalog, "lookup_gnomad_variant", lambda query: [{
        "source": "gnomad",
        "external_id": query,
        "title": "Population variant",
        "source_url": "https://example.org/variant",
        "classification": "public",
    }])

    records = research_catalog.search_public_sources(
        "BRCA1", sources=("clinvar", "dbsnp", "ensembl", "gnomad")
    )

    assert [record["source"] for record in records] == [
        "clinvar", "dbsnp", "ensembl", "gnomad"
    ]
    assert all(record["classification"] == "public" for record in records)


def test_public_api_search_requires_explicit_disclosure_confirmation(tmp_path):
    with pytest.raises(SystemExit) as exc:
        dna_shell.main([
            "research-search", "private institutional query", "--catalog",
            str(tmp_path / "catalog.sqlite3"),
        ])
    assert exc.value.code == 2
    assert not (tmp_path / "catalog.sqlite3").exists()


def test_public_api_search_requires_confirm_flag_then_stores_records(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dna_shell, "search_public_sources", lambda query, sources, max_results: [{
        "source": "pubmed",
        "external_id": "42",
        "title": "Public paper",
        "abstract": "",
        "source_url": "https://pubmed/42",
        "published_at": "2025",
        "classification": "public",
        "rights_status": "unknown",
        "terms_url": "https://example.org/terms",
    }])
    catalog_path = tmp_path / "catalog.sqlite3"
    assert dna_shell.main([
        "research-search", "public query", "--confirm-public-query",
        "--sources", "pubmed", "--catalog", str(catalog_path),
    ]) == 0
    assert ResearchCatalog(catalog_path).count(classification="public") == 1
    assert "Rights remain unknown" in capsys.readouterr().out


def test_local_jsonl_import_defaults_private_and_context_requires_confirmation(tmp_path, capsys):
    path = tmp_path / "records.jsonl"
    path.write_text(json.dumps({
        "source": "institution",
        "external_id": "study-1",
        "title": "Private trial",
        "abstract": "private phrase from an authorized local file",
        "source_url": "https://institution.example/study-1",
    }) + "\n", encoding="utf-8")
    catalog_path = tmp_path / "catalog.sqlite3"

    assert dna_shell.main([
        "catalog-import-jsonl", str(path), "--catalog", str(catalog_path)
    ]) == 0
    capsys.readouterr()
    catalog = ResearchCatalog(catalog_path)
    assert catalog.count(classification="private") == 1
    with pytest.raises(SystemExit) as exc:
        dna_shell.main([
            "catalog-context", "private phrase", "--classification", "private",
            "--catalog", str(catalog_path),
        ])
    assert exc.value.code == 2
    capsys.readouterr()

    assert dna_shell.main([
        "catalog-context", "private phrase", "--classification", "private",
        "--confirm-local-sensitive-context", "--catalog", str(catalog_path),
    ]) == 0
    context = json.loads(capsys.readouterr().out)
    assert context["records"][0]["abstract"] == "private phrase from an authorized local file"
    assert context["citations"][0]["url"] == "https://institution.example/study-1"
    assert context["automatic_provider_transfer"] is False


def test_private_classification_cannot_be_overridden_in_jsonl(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text(json.dumps({
        "source": "institution",
        "external_id": "1",
        "title": "Record",
        "source_url": "https://institution.example/1",
        "classification": "public",
    }) + "\n", encoding="utf-8")
    records = research_catalog.load_jsonl_records(path, classification="restricted")
    assert records[0]["classification"] == "restricted"
