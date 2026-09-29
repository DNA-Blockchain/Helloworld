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
research_matcher.py
================
Real ClinicalTrials.gov API v2 search, returning a normalized list of
trial dicts (title, nct_id, url) rather than growing_research_agent.py's
raw NCT-ID list. This is a synchronous, single-shot search utility for
scripts like ptsd_research.py, not a persistent background agent --
see growing_research_agent.py for that pattern; this module
deliberately doesn't reuse its async machinery since a one-shot
search doesn't need it.

Usage
-----
    from research_matcher import find_trials

    trials = find_trials("PTSD", biomarker="cortisol", recruiting_only=True, max_results=5)
"""

from __future__ import annotations
import json
import ssl
import urllib.parse
import urllib.request

import certifi

CLINICALTRIALS_API = "https://clinicaltrials.gov/api/v2/studies"
_USER_AGENT = "ResearchMatcher/1.0 (research script; contact: local user)"

# See extended_research_sources.py's comment on this same pattern: an
# explicit certifi CA bundle is more portable than the platform default.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def find_trials(
    condition: str, biomarker: str | None = None,
    recruiting_only: bool = False, max_results: int = 5,
) -> list[dict]:
    """Real ClinicalTrials.gov v2 search. Returns [] on any request
    failure rather than raising -- a bad network day shouldn't crash a
    caller that's just trying to show what it could find."""
    params = {"query.cond": condition, "pageSize": max_results, "fields": "NCTId,BriefTitle,OverallStatus"}
    if biomarker:
        params["query.term"] = biomarker
    if recruiting_only:
        params["filter.overallStatus"] = "RECRUITING"

    url = f"{CLINICALTRIALS_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    trials = []
    for study in data.get("studies", []):
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        nct_id = ident.get("nctId")
        if not nct_id:
            continue
        trials.append({
            "nct_id": nct_id,
            "title": ident.get("briefTitle"),
            "url": f"https://clinicaltrials.gov/study/{nct_id}",
        })
    return trials[:max_results]


def trials_by_id(nct_ids: list[str]) -> list[dict]:
    """ClinicalTrials.gov studies for known NCT IDs (e.g. from
    research_store.json), with their start dates. Unlike find_trials this
    raises on request failure, so a backfill can tell "not found" from
    "not reachable"; IDs the registry does not return are omitted."""
    clean = [i.strip().upper() for i in nct_ids if i.strip().upper().startswith("NCT")]
    if not clean:
        return []
    if len(clean) > 100:
        raise ValueError("at most 100 NCT IDs per request")
    params = {
        "filter.ids": ",".join(clean),
        "fields": "NCTId,BriefTitle,StartDate",
        "pageSize": len(clean),
    }
    url = f"{CLINICALTRIALS_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=20, context=_SSL_CONTEXT) as resp:
        data = json.loads(resp.read())
    trials = []
    for study in data.get("studies", []):
        proto = study.get("protocolSection", {})
        nct_id = proto.get("identificationModule", {}).get("nctId")
        if not nct_id:
            continue
        trials.append({
            "nct_id": nct_id,
            "title": proto.get("identificationModule", {}).get("briefTitle"),
            "start_date": proto.get("statusModule", {}).get("startDateStruct", {}).get("date", ""),
            "url": f"https://clinicaltrials.gov/study/{nct_id}",
        })
    return trials


if __name__ == "__main__":
    print("=== Real recruiting trials: PTSD + cortisol ===")
    for t in find_trials("PTSD", biomarker="cortisol", recruiting_only=True, max_results=5):
        print(f"  {t['title']}  [{t['nct_id']}]  {t['url']}")
