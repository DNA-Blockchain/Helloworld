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
Offline regression tests for research_matcher.find_trials
(ClinicalTrials.gov v2, one-shot synchronous search).

Mocks urllib.request.urlopen so the real JSON field-mapping,
no-nctId skipping, max_results slicing, optional filter/biomarker
params, and failure-returns-[] behavior run deterministically offline.
"""
import json
import urllib.parse
from urllib.error import URLError

import pytest

import research_matcher as rm


class _FakeResp:
    def __init__(self, payload):
        self._data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_urlopen(monkeypatch, payload, captured=None):
    def fake(req, *args, **kwargs):
        if captured is not None:
            captured.append(req.full_url)
        if isinstance(payload, Exception):
            raise payload
        return _FakeResp(payload)

    monkeypatch.setattr(rm.urllib.request, "urlopen", fake)


def _study(nct_id, title="A trial", status="RECRUITING"):
    return {"protocolSection": {"identificationModule": {
        "nctId": nct_id, "briefTitle": title, "overallStatus": status,
    }}}


def test_maps_nct_id_title_and_builds_study_url(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"studies": [
        _study("NCT001", "Trial One"),
        _study("NCT002", "Trial Two"),
    ]})
    trials = rm.find_trials("PTSD")
    assert trials == [
        {"nct_id": "NCT001", "title": "Trial One", "url": "https://clinicaltrials.gov/study/NCT001"},
        {"nct_id": "NCT002", "title": "Trial Two", "url": "https://clinicaltrials.gov/study/NCT002"},
    ]


def test_studies_without_nct_id_are_skipped(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"studies": [
        _study("NCT001"),
        {"protocolSection": {"identificationModule": {"briefTitle": "no id"}}},
        _study("NCT003"),
    ]})
    assert [t["nct_id"] for t in rm.find_trials("x")] == ["NCT001", "NCT003"]


def test_respects_max_results(monkeypatch):
    _install_fake_urlopen(monkeypatch, {"studies": [_study(f"NCT{i:03d}") for i in range(5)]})
    assert len(rm.find_trials("x", max_results=2)) == 2


def test_biomarker_and_recruiting_only_add_query_params(monkeypatch):
    captured = []
    _install_fake_urlopen(monkeypatch, {"studies": []}, captured=captured)
    rm.find_trials("PTSD", biomarker="cortisol", recruiting_only=True)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(captured[0]).query)
    assert q["query.cond"] == ["PTSD"]
    assert q["query.term"] == ["cortisol"]
    assert q["filter.overallStatus"] == ["RECRUITING"]


def test_no_optional_params_when_not_requested(monkeypatch):
    captured = []
    _install_fake_urlopen(monkeypatch, {"studies": []}, captured=captured)
    rm.find_trials("PTSD")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(captured[0]).query)
    assert "query.term" not in q
    assert "filter.overallStatus" not in q


def test_request_failure_returns_empty_list(monkeypatch):
    _install_fake_urlopen(monkeypatch, URLError("down"))
    assert rm.find_trials("x") == []
