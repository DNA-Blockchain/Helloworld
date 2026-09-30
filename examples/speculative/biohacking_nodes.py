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
examples/speculative/biohacking_nodes.py  --  SPECULATIVE FICTION
==================================================================
A science-fiction "biohacking node" toy: DNA and RNA sequences are given
imaginary radio "resonances", guide RNAs "reprogram" nodes, methylation
"blocks frequencies", and siRNA "silences" them. None of that is real.
DNA has no radio frequency, and no RF node can be edited by an RNA sequence.
Everything marked FICTIONAL is invented for storytelling and art.

It is kept honest in two ways:
  * Every fictional result is printed beside the REAL fact it riffs on,
    computed by the project's actual code: the genetic code, tRNA anticodons
    (twin_rna.py), Reynolds siRNA scores, 2-bit DNA storage
    (dna_binary_codec.py), and measured EEG alpha or radio peaks
    (signal_io.py).
  * It can't publish: it imports nothing that writes to the chain, and a
    test holds it to that. Its output is text on your screen.

It began as a pasted script. These bugs are fixed here:
  * the codon table listed AUG twice, so the start codon's value was silently
    overwritten;
  * codon offsets were labelled MHz but added as GHz;
  * the "tRNA anticodon" was the codon itself, not its reverse complement;
  * RNA was converted back to DNA first, so uracil's value was never used;
  * DNA storage decoded partial trailing bytes as data;
  * a person's DNA was "registered" to a node. Here only the twin's sequences
    or synthetic ones are used.

  python examples/speculative/biohacking_nodes.py demo [--twin run.json]
  python examples/speculative/biohacking_nodes.py live --source eeg:synthetic --seconds 10
  python examples/speculative/biohacking_nodes.py live --source rf:sim --seconds 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import twin_rna  # noqa: E402
from dna_binary_codec import decode_from_dna, encode_to_dna  # noqa: E402
from dna_twin_viewer import GENETIC_CODE  # noqa: E402

FICTION = "FICTIONAL"
NOTICE = ("SPECULATIVE FICTION: the 'resonances', 'node programming', 'methylation' and 'silencing' below are "
          "invented. Lines marked REAL are computed facts.")
DEMO_SEQUENCE = "ATGGCGTAGCTTAGCTAGCTAGCTAGCTAGC"     # the pasted script's example, not a person's DNA

# Fictional base tones, GHz. Uracil gets its own, and RNA keeps its U.
BASE_TONE_GHZ = {"A": 10.23, "T": 10.24, "U": 10.25, "G": 10.26, "C": 10.27}
# Fictional codon offsets: one per codon, 0-63 kHz, in the genetic code's own
# order, so no codon repeats (the paste had AUG twice).
CODON_OFFSET_MHZ = {codon: index / 1000 for index, codon in enumerate(sorted(GENETIC_CODE))}


def fictional_resonance(sequence: str) -> dict:
    """The toy's imaginary 'resonance' for a DNA or RNA sequence, in GHz.
    Deterministic, and meaningless outside the story."""
    seq = sequence.upper()
    base = float(np.mean([BASE_TONE_GHZ.get(b, 10.25) for b in seq]))
    dna_codons = [seq[i:i + 3].replace("U", "T") for i in range(0, len(seq) - 2, 3)]
    offsets = [CODON_OFFSET_MHZ.get(c, 0.0) for c in dna_codons]
    offset_ghz = (float(np.mean(offsets)) if offsets else 0.0) / 1000     # MHz -> GHz, correctly
    return {"kind": FICTION, "resonance_ghz": round(base + offset_ghz, 6),
            "fingerprint": hashlib.sha3_256(seq.encode()).hexdigest()[:16]}


def real_translation(dna: str) -> list[dict]:
    """REAL: codon, amino acid and the tRNA anticodon that reads it."""
    rows = []
    for i in range(0, len(dna) - 2, 3):
        codon = dna[i:i + 3].upper()
        rows.append({"codon": codon, "amino_acid": GENETIC_CODE.get(codon, "?"),
                     "trna_anticodon": twin_rna.anticodon(codon)})
    return rows


def fictional_guide_program(guide_rna: str, operation: str) -> dict:
    target = twin_rna.reverse_complement_rna(guide_rna)
    return {
        "fictional": {"kind": FICTION, "operation": operation,
                      "node_response": f"node retuned to {fictional_resonance(guide_rna)['resonance_ghz']} GHz "
                                       f"for '{operation}'"},
        "real": {"fact": "A guide RNA pairs with the complementary sequence; CRISPR also needs a PAM site "
                         "and a Cas protein, and acts on DNA in cells, not on radios.",
                 "sequence_it_pairs_with": target},
    }


def fictional_silencing(sirna_target_dna: str) -> dict:
    target = twin_rna.to_rna(sirna_target_dna)[:twin_rna.SIRNA_LENGTH]
    real = (twin_rna.reynolds_score(target) if len(target) == twin_rna.SIRNA_LENGTH
            else {"score": None, "note": "needs 19 bases"})
    return {
        "fictional": {"kind": FICTION, "node_silenced_seconds": round(len(target) / 19 * 3600)},
        "real": {"fact": "siRNA silences an mRNA it pairs with, inside cells. The Reynolds score is a design "
                         "heuristic for how well a 19-base target might work.",
                 "target_mrna": target, "reynolds": real},
    }


def fictional_methylation(pattern: str) -> dict:
    blocked = [round(10.20 + i * 0.01, 2) for i, bit in enumerate(pattern[:10]) if bit == "1"]
    return {
        "fictional": {"kind": FICTION, "blocked_ghz": blocked},
        "real": {"fact": "DNA methylation adds methyl groups (usually to C in CpG sites) and changes gene "
                         "expression. It does not block radio frequencies."},
    }


def real_storage(data: bytes) -> dict:
    """REAL: 2-bit DNA storage through the project's own codec."""
    dna = encode_to_dna(data)
    back = decode_from_dna(dna)
    return {"bytes": len(data), "bases": len(dna), "bits_per_base": 2, "round_trip_ok": back == data,
            "dna_preview": dna[:32]}


def demo(sequence: str, label: str, out=print) -> dict:
    out(NOTICE)
    out(f"\nSequence: {label}, {len(sequence)} bases")
    resonance = fictional_resonance(sequence)
    rna = twin_rna.to_rna(sequence)
    out(f"  FICTIONAL  DNA resonance {resonance['resonance_ghz']} GHz, "
        f"RNA resonance {fictional_resonance(rna)['resonance_ghz']} GHz")
    translation = real_translation(sequence)
    out("  REAL       translation: " + " ".join(
        f"{r['codon']}>{r['amino_acid']}(tRNA {r['trna_anticodon']})" for r in translation[:6])
        + (" ..." if len(translation) > 6 else ""))
    guide = fictional_guide_program(rna[:20], "increase_sensitivity")
    out(f"  FICTIONAL  {guide['fictional']['node_response']}")
    out(f"  REAL       {guide['real']['fact']}")
    silencing = fictional_silencing(sequence)
    out(f"  FICTIONAL  node silenced for {silencing['fictional']['node_silenced_seconds']} s")
    out(f"  REAL       Reynolds score of the first 19-base window: {silencing['real']['reynolds'].get('score')}")
    methylation = fictional_methylation("1011001110")
    out(f"  FICTIONAL  methylation blocks {methylation['fictional']['blocked_ghz']} GHz")
    out(f"  REAL       {methylation['real']['fact']}")
    storage = real_storage(b"Neural node biohacking integration test")
    out(f"  REAL       DNA storage: {storage['bytes']} bytes -> {storage['bases']} bases, "
        f"round trip {'OK' if storage['round_trip_ok'] else 'FAILED'}")
    return {"resonance": resonance, "translation": translation, "guide": guide, "silencing": silencing,
            "methylation": methylation, "storage": storage}


def live(source_spec: str, seconds: float, out=print) -> int:
    """Measured signal in, fictional node 'resonance meter' out."""
    import signal_io
    import twin_signals

    out(NOTICE)
    source = signal_io.open_source(source_spec)
    started, frames = time.time(), 0
    try:
        for frame in source.frames():
            frames += 1
            if frame.kind == "eeg":
                window = frame.data.astype(np.float64)
                measured = twin_signals.relative_alpha(window, frame.sample_rate) if window.shape[1] >= 64 else 0
                real = f"REAL relative alpha {measured:.3f}"
                level = float(measured)                            # already 0-1
            else:
                real = "REAL " + signal_io.describe(frame).split(": ", 1)[1]
                dbfs = 10 * np.log10(np.mean(np.abs(frame.data) ** 2) + 1e-20)
                level = float(np.clip((dbfs + 60) / 60, 0, 1))      # -60..0 dBFS -> 0..1
            meter = "#" * int(level * 20)
            out(f"{real:<60} | FICTIONAL node resonance [{meter:<20}] {10.23 + level * 0.04:.4f} GHz")
            if time.time() - started >= seconds:
                break
    finally:
        source.close()
    return 0 if frames else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Speculative-fiction biohacking nodes (see the module docstring)")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--twin", type=Path, help="use this twin run's sample sequence instead of the demo one")
    d.add_argument("--json", action="store_true", help="print the results as JSON too")
    lv = sub.add_parser("live")
    lv.add_argument("--source", default="eeg:synthetic", help="any signal_io.py source spec")
    lv.add_argument("--seconds", type=float, default=10)
    args = p.parse_args(argv)
    if args.command == "live":
        return live(args.source, args.seconds)
    sequence, label = DEMO_SEQUENCE, "the original script's example (synthetic)"
    if args.twin:
        import dna_twin_viewer

        twin = dna_twin_viewer.twin_from_run(json.loads(args.twin.read_text(encoding="utf-8")))
        sequence, label = twin["sample"], f"twin sample: {twin['case_label']}"
    result = demo(sequence, label)
    if args.json:
        print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
