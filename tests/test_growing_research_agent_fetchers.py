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
Offline regression tests for GrowingResearchAgent's source fetchers
(ClinicalTrials.gov, PubMed, ClinVar two-step, HGNC, St. Jude no-op).

In production these hit real public APIs (see KNOWN_GAPS.md on why the
live paths aren't in the suite). Here the module's async _http_get_json
is replaced with a router over canned JSON, so the real parsing,
two-step ClinVar sequencing, gene extraction, and failure handling run
deterministically and offline. Each test drives exactly one fetcher, so
routing by URL substring is unambiguous.
"""
import pytest

import growing_research_agent as gra
from growing_research_agent import GrowingResearchAgent


def _install_fake_http(monkeypatch, routes):
    async def fake_get_json(url, params=None, headers=None, timeout=20):
        for needle, payload in routes.items():
            if needle in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"unexpected URL requested: {url}")

    monkeypatch.setattr(gra, "_http_get_json", fake_get_json)


def _agent(tmp_path):
    return GrowingResearchAgent(
        node=None, dna=None,
        store_path=str(tmp_path / "store.json"),
        interval_s=999, max_topics=50,
    )


# -- PubMed ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_pubmed_prefixes_pmids(monkeypatch, tmp_path):
    _install_fake_http(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": ["10", "20"]}},
    })
    ids = await _agent(tmp_path)._fetch_pubmed("breast cancer", "BRCA1")
    assert ids == ["PMID:10", "PMID:20"]


@pytest.mark.asyncio
async def test_fetch_pubmed_failure_returns_empty(monkeypatch, tmp_path):
    _install_fake_http(monkeypatch, {"esearch.fcgi": RuntimeError("boom")})
    assert await _agent(tmp_path)._fetch_pubmed("x", None) == []


# -- ClinicalTrials.gov ----------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_clinicaltrials_ids_and_related_conditions(monkeypatch, tmp_path):
    _install_fake_http(monkeypatch, {"clinicaltrials.gov": {"studies": [
        {"protocolSection": {
            "identificationModule": {"nctId": "NCT001"},
            "conditionsModule": {"conditions": ["Breast Cancer", "Lymphoma"]},
        }},
        {"protocolSection": {
            "identificationModule": {"nctId": "NCT002"},
            "conditionsModule": {"conditions": ["Melanoma"]},
        }},
    ]}})
    ids, related = await _agent(tmp_path)._fetch_clinicaltrials("breast cancer", None)
    assert ids == ["NCT001", "NCT002"]
    # the queried condition is excluded (case-insensitively); the rest remain
    assert set(related) == {"Lymphoma", "Melanoma"}


@pytest.mark.asyncio
async def test_fetch_clinicaltrials_failure_returns_empty_pair(monkeypatch, tmp_path):
    _install_fake_http(monkeypatch, {"clinicaltrials.gov": RuntimeError("boom")})
    assert await _agent(tmp_path)._fetch_clinicaltrials("x", None) == ([], [])


# -- ClinVar (two-step esearch -> esummary) --------------------------------

@pytest.mark.asyncio
async def test_fetch_clinvar_ids_and_candidate_genes(monkeypatch, tmp_path):
    _install_fake_http(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": ["u1", "u2"]}},
        "esummary.fcgi": {"result": {
            "u1": {"genes": [{"symbol": "BRCA1"}, {"symbol": "TP53"}]},
            "u2": {"genes": [{"symbol": "brca1"}]},
        }},
    })
    ids, genes = await _agent(tmp_path)._fetch_clinvar("breast cancer", "BRCA1")
    assert ids == ["ClinVar:u1", "ClinVar:u2"]
    # the biomarker itself is excluded (case-insensitively); others uppercased
    assert genes == ["TP53"]


@pytest.mark.asyncio
async def test_fetch_clinvar_no_uids_short_circuits(monkeypatch, tmp_path):
    # No esummary route: if the code called it despite an empty idlist, the
    # router would AssertionError. An empty idlist must return before that.
    _install_fake_http(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": []}},
    })
    assert await _agent(tmp_path)._fetch_clinvar("x", "GENE") == ([], [])


@pytest.mark.asyncio
async def test_fetch_clinvar_esummary_failure_keeps_ids(monkeypatch, tmp_path):
    _install_fake_http(monkeypatch, {
        "esearch.fcgi": {"esearchresult": {"idlist": ["u1", "u2"]}},
        "esummary.fcgi": RuntimeError("summary down"),
    })
    ids, genes = await _agent(tmp_path)._fetch_clinvar("x", "GENE")
    assert ids == ["ClinVar:u1", "ClinVar:u2"]
    assert genes == []


# -- HGNC ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_hgnc_returns_normalized_symbol(monkeypatch, tmp_path):
    _install_fake_http(monkeypatch, {"rest.genenames.org": {
        "response": {"docs": [{"symbol": "TP53"}]},
    }})
    assert await _agent(tmp_path)._fetch_hgnc("tp53") == "TP53"


@pytest.mark.asyncio
async def test_fetch_hgnc_no_docs_returns_none(monkeypatch, tmp_path):
    _install_fake_http(monkeypatch, {"rest.genenames.org": {"response": {"docs": []}}})
    assert await _agent(tmp_path)._fetch_hgnc("notagene") is None


@pytest.mark.asyncio
async def test_fetch_hgnc_failure_returns_none(monkeypatch, tmp_path):
    _install_fake_http(monkeypatch, {"rest.genenames.org": RuntimeError("boom")})
    assert await _agent(tmp_path)._fetch_hgnc("BRCA1") is None


# -- St. Jude (deliberate no-op) -------------------------------------------

@pytest.mark.asyncio
async def test_fetch_stjude_is_noop(tmp_path):
    # Documented no-op: no endpoint, returns [] without any HTTP call.
    assert await _agent(tmp_path)._fetch_stjude("x", "GENE") == []
