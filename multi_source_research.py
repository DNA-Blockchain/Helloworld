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
multi_source_research.py
================
Real PubMed (NCBI E-utilities) search returning normalized paper dicts
(title, pub_date, url). growing_research_agent.py's own PubMed fetcher
only returns bare PMIDs (fine for its change-detection use case); this
adds the esummary.fcgi round trip to get real title/date metadata,
for scripts that want to show a human what was actually found, not
just track new IDs.

Usage
-----
    from multi_source_research import search_pubmed

    papers = search_pubmed("PTSD", biomarker="cortisol", max_results=5)
"""

from __future__ import annotations
import json
import os
import ssl
import time
import urllib.parse
import urllib.request

import certifi

NCBI_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_USER_AGENT = "MultiSourceResearch/1.0 (research script; contact: local user)"
_NCBI_MIN_INTERVAL_S = 0.35  # NCBI's <=3 req/s guideline without an API key

# See extended_research_sources.py's comment on this same pattern: an
# explicit certifi CA bundle is more portable than the platform default.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _http_get_json(url: str, params: dict) -> dict:
    request_params = dict(params)
    api_key = os.environ.get("NCBI_API_KEY", "").strip()
    if api_key and "eutils.ncbi.nlm.nih.gov" in url:
        request_params["api_key"] = api_key
    full_url = f"{url}?{urllib.parse.urlencode(request_params)}"
    req = urllib.request.Request(full_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=20, context=_SSL_CONTEXT) as resp:
        return json.loads(resp.read())


def search_pubmed(condition: str, biomarker: str | None = None, max_results: int = 5) -> list[dict]:
    """Real NCBI esearch + esummary round trip. Returns [] on any request
    failure rather than raising."""
    term = f"{condition} AND {biomarker}" if biomarker else condition
    try:
        search_result = _http_get_json(NCBI_ESEARCH, {
            "db": "pubmed", "term": term, "retmode": "json", "retmax": max_results,
        })
        pmids = search_result.get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return []

        time.sleep(_NCBI_MIN_INTERVAL_S)
        summary = _http_get_json(NCBI_ESUMMARY, {
            "db": "pubmed", "id": ",".join(pmids), "retmode": "json",
        })
    except Exception:
        return []

    papers = []
    result = summary.get("result", {})
    for pmid in pmids:
        rec = result.get(pmid, {})
        if not rec:
            continue
        papers.append({
            "pmid": pmid,
            "title": rec.get("title"),
            "pub_date": rec.get("pubdate"),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return papers


if __name__ == "__main__":
    print("=== Real PubMed papers: PTSD + cortisol ===")
    for p in search_pubmed("PTSD", biomarker="cortisol", max_results=5):
        print(f"  {p['title']}  ({p['pub_date']})  {p['url']}")
