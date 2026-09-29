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
ptsd_research.py
================
Real PTSD research literature access — trials, papers, and funded
grants — combining sources already built and tested elsewhere in this
project. Same category as crispr_cancer_research.py: real published
facts, surfaced for a human to read, nothing predictive or diagnostic.

WHAT THIS DELIBERATELY DOES NOT DO
--------------------------------------
Does not diagnose, does not claim to detect or measure trauma, does
not process any individual's data. Pure literature search — the
equivalent of a very good PubMed/ClinicalTrials.gov search focused on
PTSD research specifically.

Usage
-----
    from ptsd_research import search_ptsd_research

    results = search_ptsd_research(biomarker="cortisol", max_results=5)
"""

from __future__ import annotations
from research_matcher import find_trials
from multi_source_research import search_pubmed
from extended_research_sources import search_nih_grants, search_europepmc


def search_ptsd_research(biomarker: str | None = None, max_results: int = 5) -> dict:
    trials = find_trials("PTSD", biomarker=biomarker, recruiting_only=True, max_results=max_results)
    papers = search_pubmed("PTSD", biomarker=biomarker, max_results=max_results)
    grants = search_nih_grants(f"PTSD {biomarker or ''}".strip(), max_results=max_results)
    preprints = search_europepmc(f"PTSD {biomarker or ''}".strip(), max_results=max_results)

    return {"trials": trials, "papers": papers, "grants": grants, "preprints_and_papers": preprints}


def format_results(results: dict) -> str:
    lines = [f"=== {len(results['trials'])} recruiting PTSD trials ==="]
    for t in results["trials"]:
        lines.append(f"  {t.get('title')}  [{t.get('nct_id')}]  {t.get('url')}")

    lines.append(f"\n=== {len(results['papers'])} PubMed papers ===")
    for p in results["papers"]:
        lines.append(f"  {p.get('title')}  ({p.get('pub_date')})  {p.get('url')}")

    lines.append(f"\n=== {len(results['grants'])} funded research grants ===")
    for g in results["grants"]:
        lines.append(f"  {g.get('title')}  ({g.get('fiscal_year')}, {g.get('org')})")

    lines.append(f"\n=== {len(results['preprints_and_papers'])} Europe PMC results ===")
    for e in results["preprints_and_papers"]:
        lines.append(f"  {e.get('title')}  ({e.get('pub_year')})  {e.get('url')}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Real PTSD + cortisol research ===\n")
    results = search_ptsd_research(biomarker="cortisol", max_results=3)
    print(format_results(results))
