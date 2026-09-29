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
maxwell_research.py
================
Real arXiv search for Maxwell's-equations / electromagnetism physics
literature. This is the CORRECT source for this — the existing
research sources (ClinicalTrials.gov, PubMed, ClinVar, St. Jude, NIH
grants, Europe PMC) are all medical/biomedical and would return noise
for physics queries. arXiv is where real physics preprints/papers
actually live, free public API, no auth needed.

Usage
-----
    from maxwell_research import search_arxiv

    papers = search_arxiv("Maxwell equations electromagnetic field", max_results=5)
"""

from __future__ import annotations
import ssl
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

import certifi

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# See extended_research_sources.py's comment on this same pattern: an
# explicit certifi CA bundle is more portable than the platform default.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def search_arxiv(query: str, max_results: int = 5) -> list[dict]:
    params = {"search_query": f"all:{query}", "start": 0, "max_results": max_results}
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url, timeout=15, context=_SSL_CONTEXT) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)

        results = []
        for entry in root.findall("atom:entry", ATOM_NS):
            title = entry.find("atom:title", ATOM_NS)
            id_url = entry.find("atom:id", ATOM_NS)
            updated = entry.find("atom:updated", ATOM_NS)
            results.append({
                "title": title.text.strip().replace("\n", " ") if title is not None else None,
                "url": id_url.text if id_url is not None else None,
                "updated": updated.text if updated is not None else None,
            })
        return results
    except Exception as e:
        return [{"error": f"arXiv request failed: {e}"}]


if __name__ == "__main__":
    print("=== Real arXiv search: Maxwell's equations ===")
    for p in search_arxiv("Maxwell equations electromagnetic field", max_results=5):
        if "error" in p:
            print(f"  ERROR: {p['error']}")
            continue
        print(f"  {p.get('title')}")
        print(f"    {p.get('url')}  ({p.get('updated')})")
