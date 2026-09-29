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
Offline tests for ptsd_research, which is pure orchestration over four
fetchers already tested elsewhere (find_trials, search_pubmed,
search_nih_grants, search_europepmc). Here those four are replaced with
recording stubs, so these tests pin the aggregation shape, the exact
arguments ptsd_research passes to each source, and format_results'
rendering -- with no network and no dependence on the real fetchers.
"""
import pytest

import ptsd_research as pr


def _install_stubs(monkeypatch, calls):
    def rec(name, ret):
        def stub(*args, **kwargs):
            calls.append((name, args, kwargs))
            return ret
        return stub

    monkeypatch.setattr(pr, "find_trials", rec("find_trials",
        [{"nct_id": "NCT1", "title": "Trial", "url": "u1"}]))
    monkeypatch.setattr(pr, "search_pubmed", rec("search_pubmed",
        [{"pmid": "1", "title": "Paper", "pub_date": "2024", "url": "u2"}]))
    monkeypatch.setattr(pr, "search_nih_grants", rec("search_nih_grants",
        [{"project_num": "G1", "title": "Grant", "fiscal_year": 2023, "org": "Org"}]))
    monkeypatch.setattr(pr, "search_europepmc", rec("search_europepmc",
        [{"id": "E1", "title": "Preprint", "pub_year": "2025", "url": "u3"}]))


def test_aggregates_all_four_sources_under_expected_keys(monkeypatch):
    _install_stubs(monkeypatch, [])
    out = pr.search_ptsd_research(biomarker="cortisol", max_results=3)
    assert set(out) == {"trials", "papers", "grants", "preprints_and_papers"}
    assert out["trials"][0]["nct_id"] == "NCT1"
    assert out["papers"][0]["pmid"] == "1"
    assert out["grants"][0]["project_num"] == "G1"
    assert out["preprints_and_papers"][0]["id"] == "E1"


def test_passes_expected_arguments_to_each_source(monkeypatch):
    calls = []
    _install_stubs(monkeypatch, calls)
    pr.search_ptsd_research(biomarker="cortisol", max_results=3)
    by_name = {name: (args, kwargs) for name, args, kwargs in calls}

    # trials: condition "PTSD", biomarker passed, recruiting-only, max_results
    assert by_name["find_trials"][0] == ("PTSD",)
    assert by_name["find_trials"][1] == {"biomarker": "cortisol", "recruiting_only": True, "max_results": 3}
    # pubmed: condition "PTSD", biomarker + max_results
    assert by_name["search_pubmed"][0] == ("PTSD",)
    assert by_name["search_pubmed"][1] == {"biomarker": "cortisol", "max_results": 3}
    # grants/europepmc take a single combined query string "PTSD cortisol"
    assert by_name["search_nih_grants"][0] == ("PTSD cortisol",)
    assert by_name["search_europepmc"][0] == ("PTSD cortisol",)


def test_no_biomarker_yields_bare_ptsd_query_without_trailing_space(monkeypatch):
    calls = []
    _install_stubs(monkeypatch, calls)
    pr.search_ptsd_research(biomarker=None, max_results=5)
    by_name = {name: (args, kwargs) for name, args, kwargs in calls}
    # f"PTSD {biomarker or ''}".strip() must not leave a trailing space
    assert by_name["search_nih_grants"][0] == ("PTSD",)
    assert by_name["search_europepmc"][0] == ("PTSD",)


def test_format_results_renders_counts_and_rows(monkeypatch):
    _install_stubs(monkeypatch, [])
    text = pr.format_results(pr.search_ptsd_research(biomarker="cortisol"))
    assert "=== 1 recruiting PTSD trials ===" in text
    assert "=== 1 PubMed papers ===" in text
    assert "=== 1 funded research grants ===" in text
    assert "=== 1 Europe PMC results ===" in text
    assert "Trial" in text and "Paper" in text and "Grant" in text and "Preprint" in text
