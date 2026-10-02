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


def test_a_clinvar_summary_keeps_its_classification_under_either_field_name():
    """ClinVar renamed clinical_significance to germline_classification (and added oncogenicity and
    clinical-impact classifications). The allow-list behind a record's abstract must know the new names:
    with only the old one, every ClinVar abstract silently lost its classification, which is the single
    most important fact about a variant."""
    live = {"accession": "VCV004935332", "title": "NM_007294.4(BRCA1):c.441+1G>T",
            "germline_classification": {"description": "Likely pathogenic",
                                        "review_status": "criteria provided, single submitter"},
            "oncogenicity_classification": {"description": "Oncogenic"},
            "genes": [{"symbol": "BRCA1"}], "secret": "must not appear"}
    summary = sources._safe_summary(live, database="clinvar")
    assert "Likely pathogenic" in summary and "criteria provided" in summary
    assert "Oncogenic" in summary and "VCV004935332" in summary
    assert "secret" not in summary                      # the allow-list still excludes everything else

    archived = {"accession": "VCV1", "clinical_significance": {"description": "Pathogenic"}}
    assert "Pathogenic" in sources._safe_summary(archived, database="clinvar")
    # dbSNP still uses the old name, so it must keep working.
    assert "Benign" in sources._safe_summary(
        {"snp_id": "rs1", "clinical_significance": {"description": "Benign"}}, database="snp")


def test_the_ncbi_api_key_is_attached_only_for_ncbis_own_host(monkeypatch):
    """The key is a secret, so it is attached by exact host match, never unconditionally."""
    monkeypatch.setenv("NCBI_API_KEY", "secret-key")
    monkeypatch.setattr(sources.time, "sleep", lambda _: None)
    for url in (sources.NCBI_ESEARCH, sources.NCBI_ESUMMARY, sources.NCBI_EFETCH):
        assert sources.is_ncbi(url), url
        assert sources._ncbi_prepare({"db": "clinvar"}, url).get("api_key") == "secret-key", url
    for impostor in ("https://eutils.ncbi.nlm.nih.gov.evil.example/x",
                     "https://evil.example/?x=eutils.ncbi.nlm.nih.gov",
                     "https://eutils.ncbi.nlm.nih.gov@evil.example/x", "", "not a url"):
        assert not sources.is_ncbi(impostor), impostor
        assert "api_key" not in sources._ncbi_prepare({"db": "clinvar"}, impostor), impostor
    # A caller that forgets the URL gets no key rather than leaking one.
    assert "api_key" not in sources._ncbi_prepare({"db": "clinvar"})


def test_the_fasta_fetch_still_sends_the_key(monkeypatch):
    """A host check must not silently stop the key reaching NCBI's own efetch endpoint."""
    monkeypatch.setenv("NCBI_API_KEY", "secret-key")
    monkeypatch.setattr(sources.time, "sleep", lambda _: None)
    seen = {}

    class Response:
        def read(self, size=None):          # fetch_nuccore_fasta reads with a byte limit
            return b">NM_007294.4 test\nACGT\n"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, **kw):
        seen["url"] = request.full_url
        return Response()

    monkeypatch.setattr(sources.urllib.request, "urlopen", fake_urlopen)
    assert sources.fetch_nuccore_fasta("NM_007294.4").startswith(b">")
    from urllib.parse import parse_qs, urlsplit

    parts = urlsplit(seen["url"])
    assert parts.hostname == "eutils.ncbi.nlm.nih.gov"          # the host, not a substring of the URL
    assert parse_qs(parts.query)["api_key"] == ["secret-key"]
