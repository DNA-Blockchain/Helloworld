"""
Offline regression tests for multi_source_research.search_pubmed.

The real function makes an NCBI esearch + esummary round trip over the
network (see KNOWN_GAPS.md on why the live path isn't in the suite).
These tests mock urllib.request.urlopen so the real term-building,
two-step sequencing, and JSON parsing are exercised deterministically
without touching the network.
"""
import json
import urllib.parse
import urllib.request
from urllib.error import URLError

import pytest

import multi_source_research as msr


class _FakeResp:
    def __init__(self, payload):
        self._data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_urlopen(monkeypatch, routes, captured=None):
    """routes: {url_substring: payload_dict | Exception}. Raises AssertionError
    if the code requests a URL no route matches (so an unexpected call fails
    loudly instead of silently)."""
    def fake(req, *args, **kwargs):
        url = req.full_url
        if captured is not None:
            captured.append(url)
        for needle, payload in routes.items():
            if needle in url:
                if isinstance(payload, Exception):
                    raise payload
                return _FakeResp(payload)
        raise AssertionError(f"unexpected URL requested: {url}")

    monkeypatch.setattr(msr.urllib.request, "urlopen", fake)
    # keep the mandated NCBI spacing from actually sleeping in tests
    monkeypatch.setattr(msr.time, "sleep", lambda *a, **k: None)


def test_happy_path_parses_title_date_and_url(monkeypatch):
    _install_fake_urlopen(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": ["111", "222"]}},
        "esummary.fcgi": {"result": {
            "111": {"title": "First paper", "pubdate": "2024 Jan"},
            "222": {"title": "Second paper", "pubdate": "2023 Dec"},
        }},
    })
    papers = msr.search_pubmed("breast cancer", biomarker="BRCA1", max_results=5)
    assert [(p["pmid"], p["title"], p["pub_date"], p["url"]) for p in papers] == [
        ("111", "First paper", "2024 Jan", "https://pubmed.ncbi.nlm.nih.gov/111/"),
        ("222", "Second paper", "2023 Dec", "https://pubmed.ncbi.nlm.nih.gov/222/"),
    ]
    assert all(p["authors"] == [] and p["doi"] == "" for p in papers)   # absent in this summary


def test_pubmed_carries_citation_fields_from_the_same_summary(monkeypatch):
    """esummary already returns authors, journal, volume, pages and the DOI, so exports (BibTeX, RIS)
    need no extra request."""
    _install_fake_urlopen(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": ["111"]}},
        "esummary.fcgi": {"result": {"111": {
            "title": "A paper", "pubdate": "2026 Sep 25", "fulljournalname": "The journal",
            "source": "J Abbrev", "volume": "27", "issue": "3", "pages": "e952933",
            "authors": [{"name": "Chen Y", "authtype": "Author"},
                        {"name": "Smith J", "authtype": "CollectiveName"}],
            "articleids": [{"idtype": "pubmed", "value": "111"}, {"idtype": "doi", "value": "10.1/x"}],
        }}},
    })
    [paper] = msr.search_pubmed("x")
    assert paper["authors"] == ["Chen Y"]                 # a collective name is not an author
    assert paper["container"] == "The journal" and paper["volume"] == "27" and paper["issue"] == "3"
    assert paper["pages"] == "e952933" and paper["doi"] == "10.1/x" and paper["record_type"] == "article"


def test_biomarker_is_anded_into_the_search_term(monkeypatch):
    captured = []
    _install_fake_urlopen(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": ["1"]}},
        "esummary.fcgi": {"result": {"1": {"title": "t", "pubdate": "2024"}}},
    }, captured=captured)
    msr.search_pubmed("PTSD", biomarker="cortisol")
    esearch_url = next(u for u in captured if "esearch.fcgi" in u)
    term = urllib.parse.parse_qs(urllib.parse.urlparse(esearch_url).query)["term"][0]
    assert term == "PTSD AND cortisol"


def test_no_biomarker_uses_bare_condition_as_term(monkeypatch):
    captured = []
    _install_fake_urlopen(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": ["1"]}},
        "esummary.fcgi": {"result": {"1": {"title": "t", "pubdate": "2024"}}},
    }, captured=captured)
    msr.search_pubmed("glioblastoma")
    esearch_url = next(u for u in captured if "esearch.fcgi" in u)
    term = urllib.parse.parse_qs(urllib.parse.urlparse(esearch_url).query)["term"][0]
    assert term == "glioblastoma"


def test_empty_idlist_returns_empty_and_skips_esummary(monkeypatch):
    captured = []
    # No esummary route on purpose: if the code tried to call it, the fake
    # would AssertionError -- but an empty idlist must short-circuit first.
    _install_fake_urlopen(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": []}},
    }, captured=captured)
    assert msr.search_pubmed("nonexistent condition xyz") == []
    assert all("esummary.fcgi" not in u for u in captured)


def test_request_failure_returns_empty_list(monkeypatch):
    _install_fake_urlopen(monkeypatch, {
        "esearch.fcgi": URLError("network down"),
    })
    assert msr.search_pubmed("breast cancer", biomarker="BRCA1") == []


def test_ncbi_api_key_is_read_from_environment_without_logging(monkeypatch):
    captured = []
    monkeypatch.setenv("NCBI_API_KEY", "test-api-key")
    _install_fake_urlopen(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": []}},
    }, captured=captured)

    assert msr.search_pubmed("BRCA1") == []
    params = urllib.parse.parse_qs(urllib.parse.urlparse(captured[0]).query)
    assert params["api_key"] == ["test-api-key"]


def test_summary_records_missing_for_some_pmids_are_skipped(monkeypatch):
    _install_fake_urlopen(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": ["1", "2"]}},
        # esummary only has a record for "1" -- "2" must be dropped, not crash
        "esummary.fcgi": {"result": {"1": {"title": "only one", "pubdate": "2024"}}},
    })
    papers = msr.search_pubmed("x")
    assert [p["pmid"] for p in papers] == ["1"]


def test_the_ncbi_api_key_goes_only_to_ncbis_real_host(monkeypatch):
    """The key is a secret. A substring or prefix test would leak it to a look-alike host, so the host
    is parsed and compared exactly."""
    assert msr.is_ncbi("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
    assert msr.is_ncbi("https://EUTILS.NCBI.NLM.NIH.GOV/entrez/eutils/esearch.fcgi")
    for impostor in ("https://evil.example/?x=eutils.ncbi.nlm.nih.gov",
                     "https://eutils.ncbi.nlm.nih.gov.evil.example/x",
                     "https://evil.example/eutils.ncbi.nlm.nih.gov",
                     "https://eutils.ncbi.nlm.nih.gov@evil.example/x",
                     "https://www.ncbi.nlm.nih.gov/home/about/policies/", "", "not a url"):
        assert not msr.is_ncbi(impostor), impostor

    monkeypatch.setenv("NCBI_API_KEY", "secret-key")
    sent = {}

    class Response:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, **kwargs):
        sent["url"] = request.full_url
        return Response()

    monkeypatch.setattr(msr.urllib.request, "urlopen", fake_urlopen)
    msr._http_get_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", {"db": "pubmed"})
    assert "api_key=secret-key" in sent["url"]
    msr._http_get_json("https://evil.example/?x=eutils.ncbi.nlm.nih.gov", {"db": "pubmed"})
    assert "secret-key" not in sent["url"]
