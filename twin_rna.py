#!/usr/bin/env python3
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
twin_rna.py
===========
The RNA layer of the DNA digital twin: what the twin's sequence looks like
once it is read as messenger RNA, with three lookups the twin page shows.

1. tRNA anticodons. Each codon in the mRNA is read by a transfer RNA whose
   anticodon pairs with it, so the anticodon is the codon's reverse
   complement in RNA letters, written 5'->3' (codon AUG is read by the
   anticodon CAU). This ignores wobble pairing at the codon's third base,
   which lets one tRNA read several codons; the anticodon given is the one
   that pairs exactly.

2. Amino-acid properties of a change. Each amino acid's side-chain class
   (nonpolar, aromatic, polar, positive, negative) and its Kyte-Doolittle
   hydropathy (J. Mol. Biol. 157:105, 1982) are fixed published values, so a
   missense difference can be described as, say, "polar -> negative, charge
   -1, hydropathy -2.8". That describes the chemistry of the swap. It does not
   say whether the change matters clinically.

3. siRNA candidate scan. Small interfering RNAs silence an mRNA by pairing
   with 19 bases of it. The scan scores every 19-base window of the twin's
   sample with the eight rational-design criteria of Reynolds et al.
   (Nat. Biotechnol. 22:326, 2004). A window that covers a difference from the
   reference is flagged, since it matches the sample allele but mismatches the
   reference. Allele-specific siRNA is an active research topic, and a single
   mismatch is often not enough to spare the other allele. The scores are a
   design heuristic, not a validated or tested siRNA.

Nothing here is published to the chain or changes the modeled edit.
"""

from __future__ import annotations

RNA_COMPLEMENT = {"A": "U", "U": "A", "G": "C", "C": "G"}

# Side-chain classes as in standard biochemistry texts (Lehninger).
AMINO_ACID_CLASS = {
    "Gly": "nonpolar", "Ala": "nonpolar", "Pro": "nonpolar", "Val": "nonpolar",
    "Leu": "nonpolar", "Ile": "nonpolar", "Met": "nonpolar",
    "Phe": "aromatic", "Tyr": "aromatic", "Trp": "aromatic",
    "Ser": "polar", "Thr": "polar", "Cys": "polar", "Asn": "polar", "Gln": "polar",
    "Lys": "positive", "Arg": "positive", "His": "positive",
    "Asp": "negative", "Glu": "negative",
}
CHARGE = {"positive": 1, "negative": -1}
# Kyte & Doolittle 1982: positive is hydrophobic, negative is hydrophilic.
HYDROPATHY = {
    "Ile": 4.5, "Val": 4.2, "Leu": 3.8, "Phe": 2.8, "Cys": 2.5, "Met": 1.9, "Ala": 1.8,
    "Gly": -0.4, "Thr": -0.7, "Ser": -0.8, "Trp": -0.9, "Tyr": -1.3, "Pro": -1.6,
    "His": -3.2, "Glu": -3.5, "Gln": -3.5, "Asp": -3.5, "Asn": -3.5, "Lys": -3.9, "Arg": -4.5,
}

SIRNA_LENGTH = 19
SIRNA_NOTE = (
    "siRNA candidates are 19-base windows of the sample's mRNA scored with the Reynolds et al. 2004 "
    "rational-design criteria (0-10). The guide strand is the window's reverse complement with a UU "
    "overhang. This is a design heuristic: no candidate has been tested, off-target matches elsewhere in "
    "the genome are not checked, and a window covering a difference is not shown to spare the reference "
    "allele."
)
PROPERTY_NOTE = (
    "Amino-acid class and Kyte-Doolittle hydropathy are fixed published values. They describe the "
    "chemistry of a swap, not whether it causes disease."
)


def to_rna(dna: str) -> str:
    """The mRNA reading of a coding-strand DNA sequence: T becomes U."""
    return dna.upper().replace("T", "U")


def reverse_complement_rna(rna: str) -> str:
    return "".join(RNA_COMPLEMENT[base] for base in reversed(rna.upper()))


def anticodon(codon: str) -> str:
    """The tRNA anticodon (5'->3') that pairs exactly with a codon given as
    DNA or RNA. ATG / AUG -> CAU."""
    rna = to_rna(codon)
    if len(rna) != 3 or set(rna) - set(RNA_COMPLEMENT):
        raise ValueError(f"a codon is three of A, C, G, T/U; got {codon!r}")
    return reverse_complement_rna(rna)


def property_change(reference_aa: str, sample_aa: str) -> dict:
    """The side-chain class, charge and hydropathy on each side of an amino
    acid change (three-letter codes, "*" for a stop). Values that don't apply
    to a stop are None."""
    def describe(aa: str) -> dict:
        cls = AMINO_ACID_CLASS.get(aa)
        return {"amino_acid": aa, "class": cls or ("stop" if aa == "*" else None),
                "charge": CHARGE.get(cls, 0) if cls else None, "hydropathy": HYDROPATHY.get(aa)}

    before, after = describe(reference_aa), describe(sample_aa)
    comparable = before["hydropathy"] is not None and after["hydropathy"] is not None
    return {
        "reference": before,
        "sample": after,
        "class_changed": before["class"] != after["class"],
        "charge_change": after["charge"] - before["charge"] if comparable else None,
        "hydropathy_change": round(after["hydropathy"] - before["hydropathy"], 1) if comparable else None,
    }


def reynolds_score(target: str) -> dict:
    """Reynolds et al. 2004's eight criteria for a 19-base sense-strand
    target (RNA letters), positions 1-based. Returns the total and which
    criteria contributed, so the page can show why a window scored as it did."""
    if len(target) != SIRNA_LENGTH:
        raise ValueError(f"an siRNA target is {SIRNA_LENGTH} bases")
    gc = sum(base in "GC" for base in target) / SIRNA_LENGTH
    au_tail = sum(base in "AU" for base in target[14:19])
    criteria = {
        "gc_30_to_52_percent": 1 if 0.30 <= gc <= 0.52 else 0,
        "au_at_15_to_19": au_tail,                                 # one point per A/U, up to 5
        "no_internal_repeat": 1 if not _has_hairpin(target) else 0,
        "a_at_19": 1 if target[18] == "A" else 0,
        "a_at_3": 1 if target[2] == "A" else 0,
        "u_at_10": 1 if target[9] == "U" else 0,
        "not_gc_at_19": -1 if target[18] in "GC" else 0,
        "not_g_at_13": -1 if target[12] == "G" else 0,
    }
    return {"score": sum(criteria.values()), "gc_content": round(gc, 3), "criteria": criteria}


def _has_hairpin(target: str, stem: int = 4) -> bool:
    """True if some `stem`-base stretch has its reverse complement elsewhere in
    the target, so the strand could fold back on itself. Reynolds used a
    melting-temperature cutoff; a 4-base self-complementary stem is the
    simple, checkable stand-in used here."""
    for i in range(len(target) - stem + 1):
        piece = reverse_complement_rna(target[i:i + stem])
        if piece in target[i + stem + 3:] or piece in target[:max(0, i - 3)]:
            return True
    return False


def sirna_candidates(sample: str, reference: str | None = None, top_n: int = 8,
                     covering_difference: bool = False) -> list[dict]:
    """The best-scoring 19-base siRNA target windows in `sample` (coding-strand
    DNA). With `reference` of equal length, each window also reports which of
    its bases differ from the reference allele, and `covering_difference`
    keeps only windows with at least one. Windows with a run of four identical
    bases are skipped, as most design tools do."""
    mrna = to_rna(sample)
    ref_mrna = to_rna(reference) if reference and len(reference) == len(sample) else None
    candidates = []
    for start in range(len(mrna) - SIRNA_LENGTH + 1):
        target = mrna[start:start + SIRNA_LENGTH]
        if set(target) - set(RNA_COMPLEMENT) or any(base * 4 in target for base in "ACGU"):
            continue
        scored = reynolds_score(target)
        mismatches = None
        if ref_mrna:
            window = ref_mrna[start:start + SIRNA_LENGTH]
            mismatches = [start + i + 1 for i, (a, b) in enumerate(zip(target, window)) if a != b]
        if covering_difference and not mismatches:
            continue
        candidates.append({
            "position": start + 1,
            "target_mrna": target,
            "guide_strand": reverse_complement_rna(target) + "UU",
            **scored,
            "reference_mismatch_positions": mismatches,
        })
    candidates.sort(key=lambda c: (-c["score"], c["position"]))
    return candidates[:top_n]


def rna_view(reference: str, sample: str, protein: list[dict]) -> dict:
    """Everything the twin page's RNA section shows: the protein table rows
    extended with anticodons and property changes, plus the siRNA scan."""
    rows = []
    for entry in protein:
        rows.append({
            **entry,
            "reference_anticodon": anticodon(entry["reference_codon"]),
            "sample_anticodon": anticodon(entry["sample_codon"]),
            "properties": property_change(entry["reference_amino_acid"], entry["sample_amino_acid"]),
        })
    return {
        "sample_mrna": to_rna(sample),
        "protein": rows,
        "sirna": sirna_candidates(sample, reference),
        "sirna_covering_difference": sirna_candidates(sample, reference, top_n=5, covering_difference=True),
        "sirna_note": SIRNA_NOTE,
        "property_note": PROPERTY_NOTE,
    }
