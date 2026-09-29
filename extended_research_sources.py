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
extended_research_sources.py
================
Two more real, free, unauthenticated research sources beyond what
growing_research_agent.py already covers (ClinicalTrials.gov, PubMed,
ClinVar, HGNC):

  - NIH RePORTER — search_nih_grants(): real funded NIH grant records
    (title, fiscal year, awarding org), via NIH's public RePORTER API
  - Europe PMC — search_europepmc(): real papers/preprints indexed by
    Europe PMC (title, publication year, url) — a broader index than
    PubMed alone, includes preprints PubMed doesn't

Usage
-----
    from extended_research_sources import search_nih_grants, search_europepmc

    grants = search_nih_grants("PTSD cortisol", max_results=5)
    papers = search_europepmc("PTSD cortisol", max_results=5)
"""

from __future__ import annotations
import json
import ssl
import urllib.parse
import urllib.request

import certifi

NIH_REPORTER_API = "https://api.reporter.nih.gov/v2/projects/search"
EUROPEPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_USER_AGENT = "ExtendedResearchSources/1.0 (research script; contact: local user)"

# Explicit certifi CA bundle rather than relying on the platform default:
# some government API cert chains (verified for api.reporter.nih.gov, see
# KNOWN_GAPS.md) aren't trusted by Python's default OpenSSL trust store on
# every platform even though the OS's own store (and curl, via schannel
# on Windows) trusts them fine. certifi's bundle is portable and doesn't
# depend on what happens to be installed locally.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def search_nih_grants(query: str, max_results: int = 5) -> list[dict]:
    """Real NIH RePORTER search. Returns [] on any request failure rather
    than raising."""
    body = json.dumps({
        "criteria": {
            "advanced_text_search": {
                "operator": "and", "search_field": "projecttitle,terms", "search_text": query,
            },
        },
        "include_fields": ["ProjectTitle", "FiscalYear", "Organization", "ProjectNum"],
        "offset": 0, "limit": max_results,
    }).encode()
    req = urllib.request.Request(
        NIH_REPORTER_API, data=body,
        headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    grants = []
    for rec in data.get("results", [])[:max_results]:
        org = rec.get("organization") or {}
        grants.append({
            "project_num": rec.get("project_num"),
            "title": rec.get("project_title"),
            "fiscal_year": rec.get("fiscal_year"),
            "org": org.get("org_name"),
        })
    return grants


def search_europepmc(query: str, max_results: int = 5) -> list[dict]:
    """Real Europe PMC search. Returns [] on any request failure rather
    than raising."""
    params = {"query": query, "format": "json", "pageSize": max_results}
    url = f"{EUROPEPMC_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    results = []
    for rec in data.get("resultList", {}).get("result", [])[:max_results]:
        pmid = rec.get("pmid")
        results.append({
            "id": rec.get("id"),
            "title": rec.get("title"),
            "pub_year": rec.get("pubYear"),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else rec.get("doi", ""),
        })
    return results


if __name__ == "__main__":
    print("=== Real NIH grants: PTSD cortisol ===")
    for g in search_nih_grants("PTSD cortisol", max_results=5):
        print(f"  {g['title']}  ({g['fiscal_year']}, {g['org']})")

    print("\n=== Real Europe PMC results: PTSD cortisol ===")
    for e in search_europepmc("PTSD cortisol", max_results=5):
        print(f"  {e['title']}  ({e['pub_year']})  {e['url']}")
