"""The twin's RNA layer: anticodons, amino-acid properties, and the siRNA scan."""

import ast
import itertools
import json
import re
from pathlib import Path

import pytest

import dna_twin_viewer
import remission_core
import twin_rna as rna

BRCA1_FRAGMENT = (
    "ATGGATTTATCTGCTCTTCGCGTTGAAGAAGTACAAAATGTCATTAATGCTATGCAGAAA"
    "ATCTTAGAGTGTCCCATCTGTCTGGAGTTGATCAAGGAACCTGTCTCCACAAAGTGTGAC"
)
VARIANT = BRCA1_FRAGMENT[:40] + "A" + BRCA1_FRAGMENT[41:]


def test_anticodon_is_the_exact_reverse_complement_in_rna():
    assert rna.anticodon("ATG") == "CAU"          # tRNA-Met
    assert rna.anticodon("AUG") == "CAU"          # same codon given as RNA
    assert rna.anticodon("TGG") == "CCA"          # tRNA-Trp
    pair = {"A": "U", "U": "A", "G": "C", "C": "G"}
    for codon in map("".join, itertools.product("ACGU", repeat=3)):
        anti = rna.anticodon(codon)
        # Antiparallel: the anticodon's last base pairs with the codon's first.
        assert all(pair[c] == a for c, a in zip(codon, reversed(anti)))


def test_anticodon_rejects_anything_but_a_codon():
    for bad in ("AT", "ATGC", "ANG", ""):
        with pytest.raises(ValueError):
            rna.anticodon(bad)


def test_property_change_uses_the_published_class_and_hydropathy():
    change = rna.property_change("Ser", "Asp")
    assert (change["reference"]["class"], change["sample"]["class"]) == ("polar", "negative")
    assert change["class_changed"] and change["charge_change"] == -1
    assert change["hydropathy_change"] == -2.7    # -3.5 - (-0.8)
    same = rna.property_change("Leu", "Leu")
    assert not same["class_changed"] and same["charge_change"] == 0 and same["hydropathy_change"] == 0
    stop = rna.property_change("Trp", "*")
    assert stop["sample"]["class"] == "stop" and stop["charge_change"] is None


def test_every_amino_acid_has_a_class_and_a_hydropathy():
    assert set(rna.AMINO_ACID_CLASS) == set(rna.HYDROPATHY)
    coded = set(dna_twin_viewer.GENETIC_CODE.values()) - {"*"}
    assert coded == set(rna.AMINO_ACID_CLASS)


def test_reynolds_score_counts_each_criterion():
    #        1234567890123456789
    target = "GCAGCGCUGUCGCCCAUUA"
    scored = rna.reynolds_score(target)
    c = scored["criteria"]
    assert c["a_at_19"] == 1 and c["a_at_3"] == 1 and c["u_at_10"] == 1
    assert c["au_at_15_to_19"] == 4                # A U U A at 16-19, C at 15
    assert c["not_gc_at_19"] == 0 and c["not_g_at_13"] == 0
    assert scored["gc_content"] == round(12 / 19, 3) and c["gc_30_to_52_percent"] == 0
    assert scored["score"] == sum(c.values())
    with pytest.raises(ValueError):
        rna.reynolds_score("ACGU")


def test_guide_strand_is_the_target_reverse_complement_with_uu():
    for c in rna.sirna_candidates(VARIANT, BRCA1_FRAGMENT, top_n=50):
        assert len(c["target_mrna"]) == 19 and len(c["guide_strand"]) == 21
        assert c["guide_strand"] == rna.reverse_complement_rna(c["target_mrna"]) + "UU"
        assert c["target_mrna"] == rna.to_rna(VARIANT)[c["position"] - 1:c["position"] + 18]
        assert not any(base * 4 in c["target_mrna"] for base in "ACGU")


def test_covering_windows_include_the_variant_position():
    covering = rna.sirna_candidates(VARIANT, BRCA1_FRAGMENT, top_n=5, covering_difference=True)
    assert covering
    for c in covering:
        assert c["reference_mismatch_positions"] == [41]
        assert c["position"] <= 41 <= c["position"] + 18
    assert rna.sirna_candidates(BRCA1_FRAGMENT, BRCA1_FRAGMENT, covering_difference=True) == []


def test_short_sequence_has_no_candidates():
    assert rna.sirna_candidates("ACGTACGT") == []


def test_twin_page_shows_anticodons_properties_and_sirna():
    twin = dna_twin_viewer.twin_from_run(remission_core.run(
        {"reference": BRCA1_FRAGMENT, "sample": VARIANT, "case_label": "synthetic"}))
    html = dna_twin_viewer.build_page(twin, [], [], frame=1)
    data = json.loads(re.search(r"const DATA = (\{.*?\});\nconst T", html, re.S).group(1))
    [row] = data["protein"]
    assert (row["reference_codon"], row["sample_codon"]) == ("GTC", "GAC")     # codon 14
    assert (row["reference_anticodon"], row["sample_anticodon"]) == ("GAC", "GUC")
    assert row["properties"]["reference"]["class"] == "nonpolar"               # Val
    assert row["properties"]["sample"]["class"] == "negative"                  # Asp
    assert data["rna"]["sirna_covering_difference"][0]["reference_mismatch_positions"] == [41]
    assert "not validated" in data["rna"]["sirna_note"] or "heuristic" in data["rna"]["sirna_note"]
    assert "tRNA anticodon" in html and "siRNA candidates" in html


def test_twin_rna_cannot_publish():
    """The RNA layer is analysis only: it imports nothing that writes to the chain."""
    tree = ast.parse(Path(rna.__file__).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert imported <= {"__future__"}
