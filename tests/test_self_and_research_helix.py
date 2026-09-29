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
Offline tests for self_and_research_helix_live's pure logic:
  - analyze_real_sequence (base counts + GC on real nucleotide letters)
  - build_self_helix (SHA-256 -> strand + Watson-Crick complement, with the
    complement == bitwise-NOT helix property)
  - fetch_real_reference_sequence's FASTA parsing (requests.get mocked, so
    no network is touched)
"""
import pytest

import self_and_research_helix_live as mod
from self_and_research_helix_live import (
    analyze_real_sequence, build_self_helix, fetch_real_reference_sequence,
)
from dna_binary_codec import decode_from_dna


def test_analyze_real_sequence_counts_and_gc():
    stats = analyze_real_sequence("ACGTACGT")
    assert stats["length"] == 8
    assert stats["base_counts"] == {"A": 2, "C": 2, "G": 2, "T": 2}
    assert stats["gc_content"] == 0.5


def test_analyze_real_sequence_empty():
    stats = analyze_real_sequence("")
    assert stats["length"] == 0
    assert stats["gc_content"] == 0.0


def test_build_self_helix_is_verified_and_reversible():
    h = build_self_helix(b"some identity bytes")
    # SHA-256 = 32 bytes -> 128 DNA bases
    assert len(h["strand"]) == 128
    # the strand decodes back to the exact fingerprint bytes
    assert decode_from_dna(h["strand"]) == bytes.fromhex(h["fingerprint_hex"])
    # the helix property holds: complement == bitwise NOT of the fingerprint
    assert h["helix_verified"] is True
    assert h["source_bytes_len"] == len(b"some identity bytes")


def test_fetch_parses_fasta_without_network(monkeypatch):
    class _FakeResp:
        text = ">NM_000207.1 Homo sapiens insulin (INS), mRNA\nACGTacgt\nGGCC\n"
        def raise_for_status(self):
            return None

    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _FakeResp())
    ref = fetch_real_reference_sequence()
    assert ref["accession"] == "NM_000207"
    assert ref["header"].startswith(">NM_000207")
    # sequence lines are joined and upper-cased; header dropped
    assert ref["sequence"] == "ACGTACGTGGCC"
