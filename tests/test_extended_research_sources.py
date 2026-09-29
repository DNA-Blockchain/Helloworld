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
Offline regression tests for extended_research_sources: NIH RePORTER
(search_nih_grants, a POST) and Europe PMC (search_europepmc, a GET).

Both hit real public APIs in production (see KNOWN_GAPS.md). Here
urllib.request.urlopen is mocked so the real request shaping, field
mapping, max_results slicing, and failure handling are exercised
deterministically and offline.
"""
import json
import urllib.request
from urllib.error import URLError

import pytest

import extended_research_sources as ers


class _FakeResp:
    def __init__(self, payload):
        self._data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_urlopen(monkeypatch, routes):
    def fake(req, *args, **kwargs):
        url = req.full_url
        for needle, payload in routes.items():
            if needle in url:
                if isinstance(payload, Exception):
                    raise payload
                return _FakeResp(payload)
        raise AssertionError(f"unexpected URL requested: {url}")

    monkeypatch.setattr(ers.urllib.request, "urlopen", fake)


# -- NIH RePORTER ----------------------------------------------------------

def test_nih_grants_maps_nested_org_and_fields(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"api.reporter.nih.gov": {"results": [
        {"project_num": "5R01AA000001", "project_title": "Grant One",
         "fiscal_year": 2023, "organization": {"org_name": "Univ A"}},
        {"project_num": "5R01AA000002", "project_title": "Grant Two",
         "fiscal_year": 2022, "organization": {"org_name": "Univ B"}},
    ]}})
    grants = ers.search_nih_grants("PTSD cortisol", max_results=5)
    assert grants == [
        {"project_num": "5R01AA000001", "title": "Grant One", "fiscal_year": 2023, "org": "Univ A"},
        {"project_num": "5R01AA000002", "title": "Grant Two", "fiscal_year": 2022, "org": "Univ B"},
    ]


def test_nih_grants_respects_max_results(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"api.reporter.nih.gov": {"results": [
        {"project_num": str(i), "project_title": f"G{i}", "fiscal_year": 2020,
         "organization": {"org_name": "Org"}} for i in range(5)
    ]}})
    grants = ers.search_nih_grants("x", max_results=2)
    assert len(grants) == 2


def test_nih_grants_missing_organization_does_not_crash(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"api.reporter.nih.gov": {"results": [
        {"project_num": "N", "project_title": "No org", "fiscal_year": 2021},
    ]}})
    grants = ers.search_nih_grants("x")
    assert grants == [{"project_num": "N", "title": "No org", "fiscal_year": 2021, "org": None}]


def test_nih_grants_failure_returns_empty(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"api.reporter.nih.gov": URLError("down")})
    assert ers.search_nih_grants("x") == []


# -- Europe PMC ------------------------------------------------------------

def test_europepmc_uses_pubmed_url_when_pmid_present(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"ebi.ac.uk": {"resultList": {"result": [
        {"id": "MED123", "title": "With PMID", "pubYear": "2024", "pmid": "123"},
    ]}}})
    results = ers.search_europepmc("x")
    assert results == [
        {"id": "MED123", "title": "With PMID", "pub_year": "2024",
         "url": "https://pubmed.ncbi.nlm.nih.gov/123/"},
    ]


def test_europepmc_falls_back_to_doi_without_pmid(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"ebi.ac.uk": {"resultList": {"result": [
        {"id": "PPR9", "title": "Preprint", "pubYear": "2025", "doi": "10.1/xyz"},
    ]}}})
    results = ers.search_europepmc("x")
    assert results[0]["url"] == "10.1/xyz"


def test_europepmc_respects_max_results(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"ebi.ac.uk": {"resultList": {"result": [
        {"id": str(i), "title": f"P{i}", "pubYear": "2020", "pmid": str(i)} for i in range(6)
    ]}}})
    assert len(ers.search_europepmc("x", max_results=3)) == 3


def test_europepmc_failure_returns_empty(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"ebi.ac.uk": URLError("down")})
    assert ers.search_europepmc("x") == []
