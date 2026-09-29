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
dna_twin_viewer.py
==================
A digital twin of one modeled cancer-to-reference-match run: a viewable
double helix of the same DNA the model worked on, beside its 2-bit binary
code, showing where the cancer sample differs from the reference, what
substitution the model applies at each difference, and the public research
linked to that gene on the chain.

Input is either a local run (remission_workflow.py --output) or, with
--from-chain, a published run: the sequences come back from the node chain's
public_sequence_record events and the mutations are recomputed from them, so
the twin can be rebuilt from the chain alone for synthetic and public
reference cases.

The page is a single local HTML file with no external resources. It is not
published: a run of a person's sample holds their genomic data, which stays
on this machine (research_provenance.py refuses to put it on the chain).

What this is NOT: the "modeled edit" is a string substitution that makes the
sample match the reference. It is not guide-RNA validation, not a delivery
method, and not a treatment. Guide candidates shown are an efficiency
heuristic over PAM sites. MODELED_REFERENCE_MATCH is a statement about
strings, never about a person's remission.

Usage:
    python remission_workflow.py --output run.json
    python dna_twin_viewer.py run.json --output twin.html --open
    python dna_twin_viewer.py --from-chain <run_event_id> --output twin.html
    python dna_twin_viewer.py run.json --gene BRCA1 --sequence-file brca1.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import webbrowser
from pathlib import Path

from dna_binary_codec import (
    REVERSE_MAP as BASE_TO_BITS,
    complement_strand,
    decode_from_dna,
    encode_to_dna,
)
from research_ledger import published_events

ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_DIR = ROOT / "autonomous"
DEFAULT_OUTPUT = ROOT / "dna_twin.html"
MODEL_NOTE = (
    "Computational model of DNA strings. The modeled edit is a substitution that makes the sample "
    "match the reference; it is not guide-RNA validation, a delivery method, or a treatment. "
    "A modeled reference match is not clinical remission."
)


def binary_of(sequence: str) -> list[str]:
    return [BASE_TO_BITS[base] for base in sequence]


def differences(reference: str, sample: str) -> list[dict]:
    """Positions (1-based) where `sample` differs from `reference`, with the
    2-bit code of each base. Equal-length sequences only, as the model
    requires."""
    return [
        {
            "position": index + 1,
            "reference": ref,
            "observed": obs,
            "reference_bits": BASE_TO_BITS[ref],
            "observed_bits": BASE_TO_BITS[obs],
        }
        for index, (ref, obs) in enumerate(zip(reference, sample))
        if ref != obs
    ]


def twin_from_run(result: dict) -> dict:
    """The twin's data from a local remission-model.v1 result."""
    if result.get("schema") != "remission-model.v1":
        raise ValueError("input must be a remission-model.v1 result from remission_workflow.py")
    records = result.get("records") or {}
    stages = {}
    for block in result["ledger"]["blocks"]:
        payload = records.get(block["payload_sha256"]) or {}
        if "sequence" in payload:
            stages.setdefault(block["kind"], payload["sequence"])
    reference = stages.get("REFERENCE")
    sample = stages.get("CANCER_SAMPLE") or (result.get("before") or {}).get("sequence")
    edited = stages.get("POST_EDIT") or (result.get("after") or {}).get("sequence")
    if not (reference and sample and edited):
        raise ValueError("the run does not carry its reference, sample and edited sequences")
    assessment = result["assessment"]
    return {
        "source": "local run",
        "case_label": result.get("case_label") or "unlabelled case",
        "reference": reference,
        "sample": sample,
        "edited": edited,
        "mutations": result["mutations"],
        "modeled_edit": result["modeled_edit"],
        "verification": result["verification"],
        "modeled_status": assessment["modeled_status"],
        "longitudinal_trend": assessment["longitudinal_trend"],
        "clinical_status": assessment["clinical_status"]["status"],
        "follow_ups": [
            {"label": f["label"], "sequence": f["sequence"], "collected_on": f.get("collected_on"),
             "differences_vs_reference": f["differences_vs_reference"]}
            for f in result.get("follow_ups") or []
        ],
        "stage_ledger": [
            {"index": b["index"], "kind": b["kind"], "block_hash": b["block_hash"]}
            for b in result["ledger"]["blocks"]
        ],
        "ledger_verified": result["ledger"]["verified"],
        "note": MODEL_NOTE,
    }


def twin_from_chain(base_dir: Path, run_event_id: str) -> dict:
    """The twin's data from the chain: a published run event plus the
    public_sequence_record events it names. Mutations are recomputed from the
    published sequences, so the chain alone is enough to rebuild the twin."""
    runs = published_events(str(base_dir), "public_model_run_record")
    run = runs.get(run_event_id)
    if run is None:
        raise ValueError(f"no published model run with event ID {run_event_id}")
    published = published_events(str(base_dir), "public_sequence_record")
    sequences = {}
    for event_id in run["sequence_event_ids"]:
        event = published.get(event_id)
        if event is None:
            continue
        sequences[event["sequence"]["label"].rsplit("(", 1)[-1].rstrip(")")] = event["sequence"]
    reference, sample, edited = (sequences.get(part) for part in ("reference", "cancer sample", "modeled edit"))
    if not (reference and sample and edited):
        raise ValueError(
            "this run's sequences are not on the chain (only its hashes were published), so the twin "
            "must be built from the local run file instead"
        )
    recomputed = differences(reference["bases"], sample["bases"])
    return {
        "source": f"chain: run event {run_event_id}",
        "case_label": sample["label"].rsplit("(", 1)[0].strip() or "published run",
        "sequence_origin": sample["origin"],
        "reference": reference["bases"],
        "sample": sample["bases"],
        "edited": edited["bases"],
        "mutations": [
            dict(difference, mutation_id=f"MUT-{difference['position']:06d}", type="substitution")
            for difference in recomputed
        ],
        "modeled_edit": [
            {"mutation_id": f"MUT-{d['position']:06d}", "position": d["position"],
             "from": d["observed"], "to": d["reference"],
             "from_bits": d["observed_bits"], "to_bits": d["reference_bits"]}
            for d in recomputed
        ],
        "verification": {
            "total_positions": len(reference["bases"]),
            "different_positions": len(differences(reference["bases"], edited["bases"])),
            "status": run["modeled_status"],
        },
        "modeled_status": run["modeled_status"],
        "longitudinal_trend": run["longitudinal_trend"],
        "clinical_status": run["clinical_status"],
        "follow_ups": [],
        "stage_ledger": [{"index": s["index"], "kind": s["kind"], "block_hash": s["block_hash"]}
                         for s in run["stage_ledger"]],
        "ledger_verified": None,
        "run_sha256": run["run_sha256"],
        "guide_design": run["guide_design"],
        "note": MODEL_NOTE,
    }


def twin_from_baseline(sequence: str, label: str = "cancer-free baseline") -> dict:
    """A cancer-free baseline twin: one sequence with no differences from
    itself. This is the reference every modeled edit is derived from, since
    the model's only edit is to make a sample match this baseline. Build it
    from a public reference sequence (e.g. an NCBI RefSeq fragment)."""
    bases = "".join(sequence.upper().split())
    if not bases or set(bases) - set("ACGT"):
        raise ValueError("a baseline must be a non-empty ACGT sequence")
    return {
        "source": "cancer-free baseline",
        "case_label": label,
        "is_baseline": True,
        "reference": bases,
        "sample": bases,
        "edited": bases,
        "mutations": [],
        "modeled_edit": [],
        "verification": {"total_positions": len(bases), "different_positions": 0,
                         "status": "MODELED_REFERENCE_MATCH"},
        "modeled_status": "MODELED_REFERENCE_MATCH",
        "longitudinal_trend": "NO_FOLLOW_UP_DATA",
        "clinical_status": "NOT_CLINICALLY_CONFIRMED",
        "follow_ups": [],
        "stage_ledger": [],
        "ledger_verified": None,
        "note": (
            "A cancer-free baseline: the reference sequence a sample is compared against. "
            "Every modeled edit is simply the substitution that restores this baseline at a differing "
            "position. " + MODEL_NOTE
        ),
    }


def linked_research(base_dir: Path, genes: list[str]) -> list[dict]:
    """Published CRISPR-tagged records for these genes (research_crispr_link.py)."""
    if not genes:
        return []
    try:
        import research_crispr_link

        return [
            {"source": r["source"], "external_id": r["external_id"], "title": r["title"], "tags": r["tags"]}
            for r in research_crispr_link.related_records(base_dir, genes)
        ]
    except (OSError, ValueError, KeyError, ImportError):
        return []


def guides_near_mutations(sequence: str, mutations: list[dict], window: int = 30, top_n: int = 5) -> list[dict]:
    """Guide-RNA candidates whose target lies within `window` bases of a
    modeled difference. An efficiency heuristic over PAM sites, offered as
    reading for a human, not a validated design."""
    if not sequence or not mutations:
        return []
    from crispr_guide_design import find_guide_candidates

    positions = [m["position"] for m in mutations]
    near = []
    for candidate in find_guide_candidates(sequence, top_n=200):
        start = candidate["position"] + 1
        end = start + len(candidate["guide_sequence"])
        closest = min((abs(start - p), p) for p in positions)
        if closest[0] <= window or start <= closest[1] <= end:
            near.append({**candidate, "nearest_difference": closest[1], "distance": closest[0]})
    near.sort(key=lambda c: (c["distance"], -c["score"]))
    return near[:top_n]


def strand_pair(sequence: str) -> dict:
    """Both strands of the double helix for `sequence`, from the project's own
    codec, with the binary check that makes the pairing verifiable: because
    A=00/T=11 and C=01/G=10, the complementary strand's bits are exactly the
    bitwise NOT of the first strand's (dna_binary_codec.complement_strand)."""
    complement = complement_strand(sequence)
    forward_bits = binary_of(sequence)
    complement_bits = binary_of(complement)
    flipped = ["".join("1" if bit == "0" else "0" for bit in code) for code in forward_bits]
    return {
        "forward": sequence,
        "complement": complement,
        "forward_bits": forward_bits,
        "complement_bits": complement_bits,
        "complement_is_bitwise_not": complement_bits == flipped,
        "pairs_watson_crick": all(
            {base, partner} in ({"A", "T"}, {"C", "G"}) for base, partner in zip(sequence, complement)
        ),
    }


def build_page(twin: dict, research: list[dict], guides: list[dict]) -> str:
    strands = {part: strand_pair(twin[part]) for part in ("reference", "sample", "edited")}
    data = {
        "twin": twin,
        "strands": strands,
        "reference_bits": strands["reference"]["forward_bits"],
        "sample_bits": strands["sample"]["forward_bits"],
        "edited_bits": strands["edited"]["forward_bits"],
        "helix_verified": all(
            pair["complement_is_bitwise_not"] and pair["pairs_watson_crick"] for pair in strands.values()
        ),
        "research": research,
        "guides": guides,
    }
    return PAGE.replace("__TWIN_DATA__", json.dumps(data, ensure_ascii=False))


def read_fasta_or_plain(path: Path) -> str:
    """A DNA sequence from a plain or FASTA file."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return "".join(line for line in lines if line and not line.startswith(">"))


def pack_bases(sequence: str) -> bytes:
    """The sequence as packed 2-bit binary, 4 bases per byte, through the
    project's own codec (dna_binary_codec.decode_from_dna is its exact
    inverse, so the dataset round-trips). The tail is padded with A (00) to a
    4-base boundary; base_count in the manifest gives the real length."""
    padded = sequence + "A" * (-len(sequence) % 4)
    return decode_from_dna(padded)


def unpack_bases(packed: bytes, base_count: int) -> str:
    """The sequence back from packed bytes, dropping the padding."""
    return encode_to_dna(packed)[:base_count]


DATASET_SCHEMA = "dna-twin-dataset.v1"
# NOSFS file names: uppercase, at most 15 characters (os/schemas, storage.rs).
DATASET_FILES = {"reference": "REFDNA.BIN", "sample": "SAMPDNA.BIN", "edited": "EDITDNA.BIN"}
DATASET_MANIFEST = "TWINMETA.JSON"
DATASET_TASK_INPUT = "SAMPLE.JSON"


def dataset_files(twin: dict) -> dict[str, bytes]:
    """The twin as a binary dataset the Network OS can read: one packed 2-bit
    file per strand, a manifest of counts and hashes, and a SAMPLE.JSON in the
    shape remission_core.py's task bundle already takes, so the kernel's
    MicroPython can model the same sequences from these files."""
    files: dict[str, bytes] = {}
    strands = {}
    for part, name in DATASET_FILES.items():
        packed = pack_bases(twin[part])
        files[name] = packed
        strands[part] = {
            "file": name,
            "base_count": len(twin[part]),
            "packed_bytes": len(packed),
            "bases_sha256": hashlib.sha256(twin[part].encode("utf-8")).hexdigest(),
            "packed_sha256": hashlib.sha256(packed).hexdigest(),
        }
    manifest = {
        "schema": DATASET_SCHEMA,
        "case_label": twin["case_label"],
        "is_baseline": bool(twin.get("is_baseline")),
        "encoding": {"bits_per_base": 2, "map": {"A": "00", "C": "01", "G": "10", "T": "11"},
                     "bases_per_byte": 4, "padding_base": "A",
                     "note": "complementing a base flips both bits, so the second strand is a bitwise NOT"},
        "strands": strands,
        "difference_positions": [m["position"] for m in twin["mutations"]],
        "modeled_status": twin["modeled_status"],
        "clinical_status": twin["clinical_status"],
        "stage_ledger": twin["stage_ledger"],
        "run_sha256": twin.get("run_sha256"),
        "source": twin["source"],
        "task_input": DATASET_TASK_INPUT,
        "note": MODEL_NOTE,
    }
    files[DATASET_MANIFEST] = (json.dumps(manifest, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    files[DATASET_TASK_INPUT] = (json.dumps(
        {"reference": twin["reference"], "sample": twin["sample"], "case_label": twin["case_label"]},
        indent=1) + "\n").encode("utf-8")
    return files


def write_dataset(directory: Path, twin: dict) -> dict[str, int]:
    """Writes the dataset files and returns each one's size."""
    directory.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, data in dataset_files(twin).items():
        (directory / name).write_bytes(data)
        written[name] = len(data)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("result", nargs="?", type=Path, help="remission_workflow.py --output JSON")
    parser.add_argument("--from-chain", metavar="EVENT_ID",
                        help="rebuild the twin from a published model run instead of a local file")
    parser.add_argument("--baseline", type=Path, metavar="FILE",
                        help="build a cancer-free baseline twin from a reference sequence (plain or FASTA) "
                             "instead of a run; this baseline is what every modeled edit restores")
    parser.add_argument("--label", help="case label for the page and dataset")
    parser.add_argument("--gene", action="append", default=[],
                        help="gene this case is about (repeatable); shows the chain's tagged research for it")
    parser.add_argument("--sequence-file", type=Path,
                        help="a longer DNA sequence to scan for guide candidates near the differences")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--open", action="store_true", help="open the page in your browser when it is written")
    parser.add_argument("--export-dataset", type=Path, metavar="DIR",
                        help="also write the twin as a packed 2-bit binary dataset the Network OS can read")
    args = parser.parse_args(argv)

    sources = [bool(args.result), bool(args.from_chain), bool(args.baseline)]
    if sum(sources) != 1:
        parser.error("give exactly one of: a run JSON file, --from-chain EVENT_ID, or --baseline FILE")
    try:
        if args.from_chain:
            twin = twin_from_chain(args.base_dir, args.from_chain)
        elif args.baseline:
            twin = twin_from_baseline(read_fasta_or_plain(args.baseline),
                                      args.label or f"cancer-free baseline ({args.baseline.stem})")
        else:
            twin = twin_from_run(json.loads(args.result.read_text(encoding="utf-8")))
        if args.label:
            twin["case_label"] = args.label
    except (OSError, ValueError) as error:
        print(f"Could not build the twin: {error}")
        return 2

    scan_sequence = read_fasta_or_plain(args.sequence_file) if args.sequence_file else None
    guides = guides_near_mutations(scan_sequence or twin["sample"], twin["mutations"])
    research = linked_research(args.base_dir, args.gene)

    args.output.write_text(build_page(twin, research, guides), encoding="utf-8")
    print(f"Digital twin written to {args.output}  ({twin['source']})")
    print(f"{len(twin['sample'])} bases, {len(twin['mutations'])} difference(s) from reference; "
          f"{twin['modeled_status']}, {twin['clinical_status']}")
    if guides:
        print(f"{len(guides)} guide candidate(s) near a difference (efficiency heuristic, not validated)")
    if research:
        print(f"{len(research)} linked research record(s) from the chain")
    if args.export_dataset:
        written = write_dataset(args.export_dataset, twin)
        print(f"Binary dataset written to {args.export_dataset}: "
              + ", ".join(f"{name} {size} bytes" for name, size in written.items()))
        print(f"{DATASET_TASK_INPUT} is in the shape os/tasks/remission takes, so the kernel's "
              f"MicroPython can model these same sequences.")
    print(MODEL_NOTE)
    if args.open:
        webbrowser.open(args.output.resolve().as_uri())
    return 0


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DNA Digital Twin</title>
<style>
:root{--bg:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e3e8;--accent:#2457c5;--bad:#b3261e;--ok:#1d7a3a;
--a:#2f855a;--c:#2b6cb0;--g:#b7791f;--t:#9b2c2c;--panel:#f7f7fa}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141416;--fg:#ececf0;--muted:#9a9aa3;
--line:#2c2c31;--accent:#7aa2ff;--bad:#ff8a80;--ok:#5fcf85;--a:#68d391;--c:#63b3ed;--g:#f6d55c;--t:#fc8181;
--panel:#1c1c20}}
:root[data-theme="dark"]{--bg:#141416;--fg:#ececf0;--muted:#9a9aa3;--line:#2c2c31;--accent:#7aa2ff;
--bad:#ff8a80;--ok:#5fcf85;--a:#68d391;--c:#63b3ed;--g:#f6d55c;--t:#fc8181;--panel:#1c1c20}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px}
h1{font-size:23px;margin:0 0 4px}h2{font-size:17px;margin:30px 0 10px}
.muted{color:var(--muted)}.small{font-size:13px}.bad{color:var(--bad)}.ok{color:var(--ok)}
.notice{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--accent);
border-radius:6px;padding:11px 13px;margin:14px 0}
.cards{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 13px;flex:1;min-width:150px}
.card b{display:block;font-size:19px;margin-top:3px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
svg{display:block}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
code{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.tag{display:inline-block;background:var(--bg);border:1px solid var(--line);border-radius:4px;
padding:1px 6px;margin-right:4px;font-size:12px}
.legend span{margin-right:12px;font-size:13px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px}
.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0}
button{font:inherit;padding:6px 11px;border:1px solid var(--line);border-radius:6px;background:var(--panel);
color:var(--fg);cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);color:var(--accent)}
</style></head><body><main>
<h1>DNA Digital Twin</h1>
<div class="muted small" id="subtitle"></div>
<div class="notice" id="note"></div>
<div class="cards" id="cards"></div>

<h2>Double helix</h2>
<div class="legend muted" id="legend"></div>
<div class="controls" id="controls"></div>
<div class="scroll"><svg id="helix" role="img" aria-label="DNA double helix with modeled differences"></svg></div>
<div class="muted small" id="helixNote"></div>

<h2>Binary code (2 bits per base: A=00 C=01 G=10 T=11)</h2>
<div class="muted small" id="binaryNote"></div>
<div class="scroll"><svg id="binary" role="img" aria-label="Binary code of each strand"></svg></div>

<h2>Differences and the modeled edit</h2>
<div class="scroll"><table><thead><tr><th>Position</th><th>Reference</th><th>Cancer sample</th>
<th>Binary</th><th>Modeled substitution</th></tr></thead><tbody id="muts"></tbody></table></div>

<h2>Guide-RNA candidates near a difference</h2>
<div class="muted small">A PAM-site scan with a GC-content efficiency heuristic. Reading for a human,
not a validated design, and not a treatment.</div>
<div class="scroll"><table><thead><tr><th>Guide</th><th>PAM</th><th>Strand</th><th>Position</th>
<th>GC</th><th>Heuristic score</th><th>Nearest difference</th></tr></thead><tbody id="guides"></tbody></table></div>

<h2>Linked research on the chain</h2>
<div class="scroll"><table><thead><tr><th>Record</th><th>Source</th><th>CRISPR tags</th></tr></thead>
<tbody id="research"></tbody></table></div>

<h2>Chain provenance of this run</h2>
<div class="muted small">Each stage of the model is hash-linked to the one before it, so the order of
detection, edit and verification is checkable.</div>
<div class="scroll"><table><thead><tr><th>#</th><th>Stage</th><th>Block hash</th></tr></thead>
<tbody id="stages"></tbody></table></div>
</main><script>
const DATA = __TWIN_DATA__;
const T = DATA.twin, BASES = ["A","C","G","T"];
const colour = b => ({A:"var(--a)",C:"var(--c)",G:"var(--g)",T:"var(--t)"}[b] || "var(--muted)");
const el = id => document.getElementById(id);
const diffPositions = new Set(T.mutations.map(m => m.position));

el("subtitle").textContent = `${T.case_label} — ${T.sample.length} bases, `
  + `${T.mutations.length} difference(s) from reference · source: ${T.source}`
  + (T.sequence_origin ? ` · sequence origin: ${T.sequence_origin}` : "");
el("note").textContent = T.note;

const cards = [
  ["Modeled status", T.modeled_status],
  ["Clinical status", T.clinical_status],
  ["Differences after the modeled edit", String(T.verification.different_positions)],
  ["Follow-up trend", T.longitudinal_trend],
];
for (const [label, value] of cards) {
  const d = document.createElement("div"); d.className = "card";
  const s = document.createElement("span"); s.className = "muted small"; s.textContent = label;
  const b = document.createElement("b"); b.textContent = value;
  if (label === "Clinical status" && value === "NOT_CLINICALLY_CONFIRMED") b.className = "muted";
  d.append(s, b); el("cards").append(d);
}

el("legend").innerHTML = "";
for (const b of BASES) {
  const s = document.createElement("span");
  const dot = document.createElement("i"); dot.className = "dot"; dot.style.background = colour(b);
  s.append(dot, document.createTextNode(b)); el("legend").append(s);
}
const diffLegend = document.createElement("span");
diffLegend.innerHTML = '<i class="dot" style="background:var(--bad)"></i>difference from reference';
el("legend").append(diffLegend);

// --- which strand pair the helix shows
let view = "sample";
const views = [["sample","Cancer sample"],["edited","After modeled edit"],["reference","Reference"]];
for (const [key, label] of views) {
  const b = document.createElement("button"); b.textContent = label;
  b.setAttribute("aria-pressed", String(key === view));
  b.onclick = () => { view = key; for (const o of el("controls").children)
    o.setAttribute("aria-pressed", String(o === b)); draw(); };
  el("controls").append(b);
}

function draw() {
  const seq = T[view], step = 26, amp = 21, mid = 52, pad = 26;
  const width = pad * 2 + seq.length * step, height = 150;
  const svg = el("helix"); svg.setAttribute("width", width); svg.setAttribute("height", height);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const parts = [];
  const x = i => pad + i * step;
  const yTop = i => mid + amp * Math.sin(i / 2.6);
  const yBot = i => mid - amp * Math.sin(i / 2.6);
  const path = f => seq.split("").map((_, i) => `${i ? "L" : "M"}${x(i)},${f(i)}`).join("");
  parts.push(`<path d="${path(yTop)}" fill="none" stroke="var(--line)" stroke-width="2.5"/>`);
  parts.push(`<path d="${path(yBot)}" fill="none" stroke="var(--line)" stroke-width="2.5"/>`);
  // The second strand comes from dna_binary_codec.complement_strand, not from
  // a map in this page, so what is drawn is what the project computes.
  const comp = DATA.strands[view].complement;
  seq.split("").forEach((base, i) => {
    const isDiff = diffPositions.has(i + 1);
    const rung = isDiff ? "var(--bad)" : "var(--line)";
    parts.push(`<line x1="${x(i)}" y1="${yTop(i)}" x2="${x(i)}" y2="${yBot(i)}" stroke="${rung}" `
      + `stroke-width="${isDiff ? 2.5 : 1.2}"/>`);
    for (const [y, b] of [[yTop(i), base], [yBot(i), comp[i] || "N"]]) {
      parts.push(`<circle cx="${x(i)}" cy="${y}" r="8.5" fill="${colour(b)}" opacity="${isDiff ? 1 : .78}"/>`);
      parts.push(`<text x="${x(i)}" y="${y + 4}" text-anchor="middle" font-size="11" `
        + `fill="var(--bg)" font-weight="600">${b}</text>`);
    }
    if (isDiff) parts.push(`<text x="${x(i)}" y="${height - 6}" text-anchor="middle" font-size="10" `
      + `fill="var(--bad)">${i + 1}</text>`);
    else if ((i + 1) % 10 === 0) parts.push(`<text x="${x(i)}" y="${height - 6}" text-anchor="middle" `
      + `font-size="10" fill="var(--muted)">${i + 1}</text>`);
  });
  svg.innerHTML = parts.join("");
  const pair = DATA.strands[view];
  const which = view === "sample"
    ? "The cancer sample. Red rungs are the positions that differ from the reference."
    : view === "edited"
    ? "After the model's substitutions. Red marks the positions it changed."
    : "The reference sequence the sample is compared against.";
  const check = pair.pairs_watson_crick && pair.complement_is_bitwise_not
    ? "Double strand verified: every rung is an A-T or C-G pair, and the second strand's 2-bit code is "
      + "exactly the bitwise NOT of the first."
    : "WARNING: the second strand did not verify as complementary.";
  el("helixNote").textContent = `${which} ${check}`;
  el("helixNote").className = pair.pairs_watson_crick && pair.complement_is_bitwise_not
    ? "muted small" : "bad small";
  drawBinary();
}

function drawBinary() {
  const rows = [["Reference", DATA.reference_bits], ["Cancer sample", DATA.sample_bits],
                ["After edit", DATA.edited_bits],
                [`2nd strand (${views.find(v => v[0] === view)[1]})`, DATA.strands[view].complement_bits]];
  const cell = 26, labelW = 104, height = rows.length * 24 + 26;
  const width = labelW + DATA.sample_bits.length * cell + 12;
  const svg = el("binary"); svg.setAttribute("width", width); svg.setAttribute("height", height);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const parts = [];
  DATA.sample_bits.forEach((_, i) => {
    if ((i + 1) % 5 === 0 || diffPositions.has(i + 1))
      parts.push(`<text x="${labelW + i * cell + cell / 2}" y="12" text-anchor="middle" font-size="9" `
        + `fill="${diffPositions.has(i + 1) ? "var(--bad)" : "var(--muted)"}">${i + 1}</text>`);
  });
  rows.forEach(([label, bits], r) => {
    const y = 26 + r * 24;
    parts.push(`<text x="0" y="${y + 13}" font-size="12" fill="var(--muted)">${label}</text>`);
    bits.forEach((code, i) => {
      const diff = diffPositions.has(i + 1);
      const changed = diff && DATA.reference_bits[i] !== bits[i];
      parts.push(`<rect x="${labelW + i * cell}" y="${y}" width="${cell - 2}" height="19" rx="3" `
        + `fill="${changed ? "var(--bad)" : "var(--bg)"}" stroke="var(--line)" opacity="${changed ? .9 : 1}"/>`);
      parts.push(`<text x="${labelW + i * cell + (cell - 2) / 2}" y="${y + 13}" text-anchor="middle" `
        + `font-size="11" font-family="ui-monospace,monospace" `
        + `fill="${changed ? "var(--bg)" : "var(--fg)"}">${code}</text>`);
    });
  });
  svg.innerHTML = parts.join("");
  el("binaryNote").textContent =
    "The last row is the shown strand's complementary strand. Each of its codes is the first strand's "
    + "code with both bits flipped, which is why the two strands are a bitwise NOT of each other.";
}

const row = (body, cells) => { const tr = body.insertRow();
  for (const c of cells) { const td = tr.insertCell();
    if (c instanceof Node) td.append(c); else td.textContent = c; } return tr; };

for (const m of T.mutations) {
  const edit = (T.modeled_edit || []).find(e => e.position === m.position);
  row(el("muts"), [String(m.position), m.reference, m.observed,
    `${m.observed_bits} → ${m.reference_bits}`,
    edit ? `${edit.from} → ${edit.to} (model substitution)` : "—"]);
}
if (!T.mutations.length) row(el("muts"), ["The sample matches the reference at every position."]);

for (const g of DATA.guides) {
  row(el("guides"), [g.guide_sequence, g.pam, g.strand, String(g.position + 1),
    g.gc_content.toFixed(3), g.score.toFixed(3),
    `position ${g.nearest_difference} (${g.distance} base(s) away)`]);
}
if (!DATA.guides.length) row(el("guides"), ["No PAM-site candidate falls near a difference in this sequence."]);

for (const r of DATA.research) {
  const tags = document.createElement("span");
  for (const t of r.tags) { const s = document.createElement("span"); s.className = "tag";
    s.textContent = t; tags.append(s); }
  row(el("research"), [r.title, `${r.source}:${r.external_id}`, tags]);
}
if (!DATA.research.length) row(el("research"),
  ["No tagged research linked. Pass --gene, and tag records with research_crispr_link.py."]);

for (const s of T.stage_ledger) {
  const code = document.createElement("code"); code.textContent = s.block_hash.slice(0, 24) + "…";
  row(el("stages"), [String(s.index), s.kind, code]);
}
if (T.ledger_verified === false) {
  const p = document.createElement("div"); p.className = "bad";
  p.textContent = "This run's stage ledger did not verify.";
  el("stages").parentElement.before(p);
}
draw();
</script></body></html>
"""


if __name__ == "__main__":
    sys.exit(main())
