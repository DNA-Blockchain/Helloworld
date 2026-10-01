import json
import urllib.parse
from urllib.error import URLError

import pytest
import public_variant_sources as sources


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_clinvar_search_uses_ncbi_key_and_returns_cited_metadata(monkeypatch):
    calls = []

    def fake_urlopen(request, **kwargs):
        calls.append(request)
        if "esearch.fcgi" in request.full_url:
            return FakeResponse({"esearchresult": {"idlist": ["77"]}})
        return FakeResponse({"result": {
            "77": {
                "uid": "77",
                "accession": "VCV000000077",
                "title": "Synthetic ClinVar record",
                "clinical_significance": {"description": "uncertain significance"},
            },
        }})

    monkeypatch.setattr(sources.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sources.time, "sleep", lambda _: None)
    monkeypatch.setattr(sources, "_NCBI_LAST_REQUEST", 0.0)
    monkeypatch.setenv("NCBI_API_KEY", "test-key-never-logged")

    records = sources.search_ncbi_variants("BRCA1", database="clinvar", max_results=2)

    assert len(records) == 1
    assert records[0]["source"] == "clinvar"
    assert records[0]["external_id"] == "VCV000000077"
    assert records[0]["classification"] == "public"
    assert json.loads(records[0]["abstract"])["clinical_significance"]["description"] == (
        "uncertain significance"
    )
    for request in calls:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        assert query["api_key"] == ["test-key-never-logged"]
    assert "test-key-never-logged" not in json.dumps(records)


def test_ncbi_request_error_does_not_expose_api_key(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "secret-test-key")
    monkeypatch.setattr(sources, "_NCBI_LAST_REQUEST", 0.0)
    monkeypatch.setattr(sources.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        sources.urllib.request, "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
    )

    with pytest.raises(RuntimeError, match="eutils.ncbi.nlm.nih.gov") as error:
        sources.search_ncbi_variants("BRCA1", database="clinvar")
    assert "secret-test-key" not in str(error.value)


def test_dbsnp_search_maps_rsid(monkeypatch):
    payloads = iter([
        {"esearchresult": {"idlist": ["123"]}},
        {"result": {"123": {"uid": "123", "snp_id": 456, "title": "rs456"}}},
    ])
    monkeypatch.setattr(
        sources.urllib.request, "urlopen",
        lambda *args, **kwargs: FakeResponse(next(payloads)),
    )
    monkeypatch.setattr(sources.time, "sleep", lambda _: None)
    monkeypatch.setattr(sources, "_NCBI_LAST_REQUEST", 0.0)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)

    records = sources.search_ncbi_variants("rs456", database="snp")

    assert records[0]["source"] == "dbsnp"
    assert records[0]["external_id"] == "rs456"
    assert records[0]["source_url"] == "https://www.ncbi.nlm.nih.gov/snp/rs456"


def test_ensembl_lookup_returns_local_catalog_record(monkeypatch):
    monkeypatch.setattr(sources, "_get_json", lambda url: {
        "id": "ENSG00000012048",
        "display_name": "BRCA1",
        "description": "Synthetic gene description",
        "biotype": "protein_coding",
        "start": 100,
        "end": 200,
    })

    records = sources.lookup_ensembl_gene("BRCA1")

    assert records[0]["source"] == "ensembl"
    assert records[0]["external_id"] == "ENSG00000012048"
    assert "Synthetic gene description" in records[0]["abstract"]


def test_ensembl_rejects_unexpected_path_input():
    import pytest

    with pytest.raises(ValueError, match="gene symbol"):
        sources.lookup_ensembl_gene("../../secret")


def test_gnomad_uses_explicit_variant_and_dataset(monkeypatch):
    captured = []

    def fake_post(url, payload):
        captured.append((url, payload))
        return {"data": {"variant": {
            "variant_id": "7-140753336-A-T",
            "genome": {"ac": 2, "an": 100, "af": 0.02},
            "exome": None,
        }}}

    monkeypatch.setattr(sources, "_post_json", fake_post)
    records = sources.lookup_gnomad_variant("7-140753336-A-T")

    assert records[0]["source"] == "gnomad"
    assert records[0]["classification"] == "public"
    assert captured[0][1]["variables"] == {
        "variantId": "7-140753336-A-T",
        "dataset": "gnomad_r4",
    }


def test_gnomad_rejects_free_text_query():
    import pytest

    with pytest.raises(ValueError, match="variant ID"):
        sources.lookup_gnomad_variant("BRCA1 cancer")
