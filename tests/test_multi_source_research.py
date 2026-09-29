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
    assert papers == [
        {"pmid": "111", "title": "First paper", "pub_date": "2024 Jan",
         "url": "https://pubmed.ncbi.nlm.nih.gov/111/"},
        {"pmid": "222", "title": "Second paper", "pub_date": "2023 Dec",
         "url": "https://pubmed.ncbi.nlm.nih.gov/222/"},
    ]


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
