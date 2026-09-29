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

from crispr_guide_design import find_guide_candidates, _gc_content, _score_candidate

REAL_BRCA1_FRAGMENT = (
    "ATGGATTTATCTGCTCTTCGCGTTGAAGAAGTACAAAATGTCATTAATGCTATGCAGAAA"
    "ATCTTAGAGTGTCCCATCTGTCTGGAGTTGATCAAGGAACCTGTCTCCACAAAGTGTGAC"
    "CACATATTTTGCAAATTTTGCATGCTGAAACTTCTCAACCAGAAGAAAGGGCCTTCACAG"
)


def test_finds_at_least_one_candidate():
    candidates = find_guide_candidates(REAL_BRCA1_FRAGMENT, top_n=5)
    assert len(candidates) > 0


def test_candidates_have_valid_pam():
    candidates = find_guide_candidates(REAL_BRCA1_FRAGMENT, top_n=5)
    for c in candidates:
        assert c["pam"][1:] == "GG"  # NGG -- last two bases are always GG


def test_candidates_are_correct_length():
    candidates = find_guide_candidates(REAL_BRCA1_FRAGMENT, top_n=5)
    for c in candidates:
        assert len(c["guide_sequence"]) == 20


def test_results_sorted_by_score_descending():
    candidates = find_guide_candidates(REAL_BRCA1_FRAGMENT, top_n=5)
    scores = [c["score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_top_n_is_respected():
    candidates = find_guide_candidates(REAL_BRCA1_FRAGMENT, top_n=2)
    assert len(candidates) <= 2


def test_gc_content_of_all_gc_sequence():
    assert _gc_content("GCGCGC") == 1.0


def test_gc_content_of_no_gc_sequence():
    assert _gc_content("ATATAT") == 0.0


def test_score_peaks_near_50_percent_gc():
    balanced = "A" * 10 + "G" * 10  # 50% GC
    extreme = "G" * 20               # 100% GC
    assert _score_candidate(balanced) > _score_candidate(extreme)
