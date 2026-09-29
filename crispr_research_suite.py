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
crispr_research_suite.py
================
Ties together the two real CRISPR-adjacent pieces in this project:

  1. LITERATURE TRACKING — reuses growing_research_agent.py's real
     fetch pipeline (ClinicalTrials.gov, PubMed, ClinVar, HGNC) to
     track new results for a condition/biomarker over time, via an
     internal GrowingResearchAgent instance.
  2. GUIDE DESIGN — crispr_guide_design.py's real PAM-site scan, for
     scoring candidate guide RNAs against a DNA sequence you provide.

DELIBERATE BOUNDARY: never mines into the chain
------------------------------------------------------
The internal GrowingResearchAgent is constructed with node=None and
dna=None. Looking at growing_research_agent.py's own code: node is
only ever used for two optional hooks (`node.on_topic(...)` at
construction, `node.broadcast_topic(...)` after each explore step),
both guarded by `hasattr(...)` checks that fail safely on None; dna
is stored but never read anywhere in that class. So this suite gets
the exact same real ClinicalTrials.gov/PubMed/ClinVar/HGNC fetching
integrated_research_agent.py uses, WITHOUT that class's mining step —
guide-design and literature-tracking results never become a signed
block or a live DNA signal. That's intentional: CRISPR guide
candidates are computational suggestions for further real wet-lab
validation (see crispr_guide_design.py's own docstring), not
consented personal signals, so they don't belong in the identity
strand or the gossiped chain.

Usage
-----
    from crispr_research_suite import CrisprResearchSuite

    suite = CrisprResearchSuite(crispr_store_path="crispr_store.json", audit=audit)
    result = await suite.check_research("breast cancer", biomarker="BRCA1")
    # result: {"total_ids": int, "new_ids": [...]}

    candidates = suite.design_guides(dna_sequence, top_n=5)
"""

from __future__ import annotations

from crispr_guide_design import find_guide_candidates
from growing_research_agent import GrowingResearchAgent


class CrisprResearchSuite:
    def __init__(self, crispr_store_path: str = "crispr_store.json", audit=None, max_topics: int = 50):
        self.audit = audit
        # node=None, dna=None: see module docstring -- this keeps literature
        # tracking working fully while guaranteeing it never mines a block
        # or touches an identity strand.
        self._research = GrowingResearchAgent(
            node=None, dna=None, store_path=crispr_store_path, max_topics=max_topics,
        )

    async def check_research(self, condition: str, biomarker: str | None = None) -> dict:
        """Runs one real explore step (ClinicalTrials.gov + PubMed + ClinVar
        + HGNC) for condition/biomarker and returns a summary. Async --
        this does real network I/O, same as growing_research_agent.py's
        own seed_topic()."""
        key = await self._research.seed_topic(condition, biomarker=biomarker)
        topic = self._research.topics[key]
        total_ids = sum(len(ids) for ids in topic["all_ids"].values())

        if self.audit is not None:
            self.audit.log(
                module="crispr_research_suite", action="check_research", node_id="local",
                details={
                    "condition": condition, "biomarker": biomarker,
                    "total_ids": total_ids, "new_id_count": len(topic["new_ids_last_run"]),
                },
            )

        return {"total_ids": total_ids, "new_ids": topic["new_ids_last_run"]}

    def design_guides(self, dna_sequence: str, top_n: int = 5) -> list[dict]:
        """Synchronous, real PAM-site scan -- no network I/O, see
        crispr_guide_design.py for the scoring heuristic and its limits."""
        candidates = find_guide_candidates(dna_sequence, top_n=top_n)

        if self.audit is not None:
            self.audit.log(
                module="crispr_research_suite", action="design_guides", node_id="local",
                details={"sequence_length": len(dna_sequence), "candidates_found": len(candidates)},
            )

        return candidates


if __name__ == "__main__":
    import asyncio
    import tempfile
    import os

    async def _demo():
        with tempfile.TemporaryDirectory() as tmp:
            suite = CrisprResearchSuite(crispr_store_path=os.path.join(tmp, "crispr_store.json"))

            print("=== Real literature check: breast cancer / BRCA1 ===")
            result = await suite.check_research("breast cancer", biomarker="BRCA1")
            print(f"Total IDs tracked: {result['total_ids']}")
            print(f"New this run: {len(result['new_ids'])}")

            print("\n=== Real guide design: BRCA1 fragment ===")
            brca1_fragment = (
                "ATGGATTTATCTGCTCTTCGCGTTGAAGAAGTACAAAATGTCATTAATGCTATGCAGAAA"
                "ATCTTAGAGTGTCCCATCTGTCTGGAGTTGATCAAGGAACCTGTCTCCACAAAGTGTGAC"
            )
            candidates = suite.design_guides(brca1_fragment, top_n=3)
            for c in candidates:
                print(f"  {c['guide_sequence']}-{c['pam']}  score={c['score']}")

            print(f"\nUnderlying research agent has node/dna: "
                  f"{suite._research.node is None and suite._research.dna is None} (expected True)")

    asyncio.run(_demo())
