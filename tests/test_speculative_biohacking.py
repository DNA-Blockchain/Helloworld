"""The speculative-fiction biohacking example: fixed bugs stay fixed, every
fictional claim is labelled, and it can't publish."""
import ast
import importlib.util
from pathlib import Path

import numpy as np

import twin_signals

PATH = Path(__file__).resolve().parents[1] / "examples" / "speculative" / "biohacking_nodes.py"
spec = importlib.util.spec_from_file_location("biohacking_nodes", PATH)
bio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bio)


def test_codon_offsets_are_unique_and_cover_every_codon():
    assert len(bio.CODON_OFFSET_MHZ) == 64
    assert len(set(bio.CODON_OFFSET_MHZ.values())) == 64          # the paste had AUG twice


def test_codon_offsets_are_converted_from_mhz_to_ghz():
    r = bio.fictional_resonance("TTT")                            # last codon alphabetically: 63 kHz
    assert r["resonance_ghz"] == round(10.24 + 0.063 / 1000, 6)


def test_rna_keeps_its_uracil():
    assert bio.fictional_resonance("UUU") != bio.fictional_resonance("TTT")


def test_trna_anticodon_is_the_reverse_complement_not_the_codon():
    [row] = bio.real_translation("ATG")
    assert row == {"codon": "ATG", "amino_acid": "Met", "trna_anticodon": "CAU"}


def test_every_fictional_operation_carries_a_real_counterpart():
    for result in (bio.fictional_guide_program("AUGGCUAGCCUAGCUAGC", "x"),
                   bio.fictional_silencing("ATGGCGTAGCTTAGCTAGCTAGC"),
                   bio.fictional_methylation("101")):
        assert result["fictional"]["kind"] == bio.FICTION
        assert result["real"]["fact"]


def test_demo_labels_every_line(capsys):
    bio.demo(bio.DEMO_SEQUENCE, "demo")
    lines = [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0].startswith("SPECULATIVE FICTION")
    body = [line for line in lines[1:] if not line.startswith("Sequence:")]
    assert body and all(line.startswith(("FICTIONAL", "REAL")) for line in body)


def test_storage_round_trips_through_the_projects_codec():
    assert bio.real_storage(b"any bytes \x00\xff")["round_trip_ok"]


def test_it_cannot_publish():
    tree = ast.parse(PATH.read_text(encoding="utf-8"))
    names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    allowed = {"__future__", "argparse", "hashlib", "json", "sys", "time", "pathlib", "numpy", "twin_rna",
               "dna_binary_codec", "dna_twin_viewer", "signal_io", "twin_signals"}
    assert names <= allowed, names - allowed


def test_relative_alpha_is_a_fraction():
    rate = 250.0
    t = np.arange(500) / rate
    pure_alpha = np.sin(2 * np.pi * 10 * t)[None, :].repeat(4, axis=0)
    value = twin_signals.relative_alpha(pure_alpha, rate)
    assert 0.9 < value <= 1.0
