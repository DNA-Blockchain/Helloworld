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
swarm_analysis.py
=================
Swarm verification of the DNA twin's analyses: the nodes split the work,
recompute each other's results, and only accept a result that two different
nodes reached independently.

It runs inside work sharing (work_sharing.py) as two jobs per swarm round:

  swarm:<round>        the first node in line picks a subject sequence, runs
                       the twin's RNA analyses on it (twin_rna.py: siRNA scan
                       and the protein-change lookups) and publishes the
                       result's SHA-256 in a signed work block.
  swarm_check:<round>  once that block is seen, a different node (the scanner
                       is excluded) resolves the same subject, recomputes the
                       analysis itself and publishes its own SHA-256.

SwarmTally watches every swarm work block. A result is ACCEPTED when two or
more distinct nodes published the same digest for the same subject, and
DISPUTED when their digests differ. With three nodes, one down still leaves
two to agree; a scan whose checker never shows up stays UNCONFIRMED.

Subjects are only sequences that are already public: public_sequence_record
events on the chain, and a fixed set of synthetic sequences labelled as
synthetic, used when the chain has none. A person's sample never becomes a
subject; research_provenance.py already refuses to publish one, so it cannot
be on the chain to pick. Only digests and subject ids go into blocks, never
sequences or analysis content.

What agreement means: the nodes ran the same deterministic code on the same
input and got the same answer, so no node's result was corrupted, faked or
computed on a different input. It does not make the analysis biologically
right; the siRNA scores are still Reynolds-criteria heuristics.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import twin_rna

ANALYSIS_VERSION = "swarm-rna.v1"
SYNTHETIC_COUNT = 8
SYNTHETIC_LENGTH = 120


def synthetic_subjects() -> list[dict]:
    """Fixed synthetic subjects: each a 120-base sequence expanded from a
    SHA-256 chain, with one substitution. Every node derives the same ones,
    so a checker can resolve them with no data sent."""
    subjects = []
    for n in range(SYNTHETIC_COUNT):
        stream, block = b"", f"swarm-synthetic-{n}".encode()
        while len(stream) * 4 < SYNTHETIC_LENGTH:
            block = hashlib.sha256(block).digest()
            stream += block
        reference = "".join("ACGT"[(byte >> shift) & 3] for byte in stream for shift in (6, 4, 2, 0))
        reference = reference[:SYNTHETIC_LENGTH]
        position = 30 + (stream[0] % 60)
        swap = {"A": "C", "C": "G", "G": "T", "T": "A"}[reference[position]]
        subjects.append({
            "id": f"synthetic:{n}",
            "label": f"synthetic swarm subject {n} (not a real gene)",
            "reference": reference,
            "sample": reference[:position] + swap + reference[position + 1:],
        })
    return subjects


def chain_subjects(ledger_dir: Optional[Path]) -> list[dict]:
    """Public sequences published on the chain, one subject each (sample =
    reference, so the scan is of the published sequence itself)."""
    if ledger_dir is None:
        return []
    try:
        from research_ledger import published_events

        events = published_events(str(ledger_dir), "public_sequence_record")
    except (OSError, ValueError, KeyError, ImportError):
        return []
    subjects = []
    for event_id, event in sorted(events.items()):
        bases = (event.get("sequence") or {}).get("bases", "")
        if len(bases) >= twin_rna.SIRNA_LENGTH and not set(bases) - set("ACGT"):
            subjects.append({"id": f"event:{event_id}", "label": event["sequence"].get("label", event_id),
                             "reference": bases, "sample": bases})
    return subjects


def all_subjects(ledger_dir: Optional[Path]) -> list[dict]:
    return chain_subjects(ledger_dir) or synthetic_subjects()


def resolve(subject_id: str, ledger_dir: Optional[Path]) -> Optional[dict]:
    """The subject with this id, if this node has it."""
    pool = synthetic_subjects() if subject_id.startswith("synthetic:") else chain_subjects(ledger_dir)
    return next((s for s in pool if s["id"] == subject_id), None)


def analyze(subject: dict) -> dict:
    """The deterministic analysis every node must reproduce exactly."""
    reference, sample = subject["reference"], subject["sample"]
    from dna_twin_viewer import protein_consequences

    view = twin_rna.rna_view(reference, sample, protein_consequences(reference, sample, 1))
    return {
        "version": ANALYSIS_VERSION,
        "subject": subject["id"],
        "protein": [{k: p[k] for k in ("position", "reference_codon", "sample_codon", "reference_anticodon",
                                       "sample_anticodon", "consequence")}
                    | {"hydropathy_change": p["properties"]["hydropathy_change"]}
                    for p in view["protein"]],
        "sirna": [{k: c[k] for k in ("position", "target_mrna", "score", "reference_mismatch_positions")}
                  for c in view["sirna"] + view["sirna_covering_difference"]],
    }


def digest(analysis: dict) -> str:
    return hashlib.sha256(
        json.dumps(analysis, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class SwarmScan:
    """work_sharing runner for swarm:<round>: pick the round's subject and
    return its analysis digest."""
    wants_task = True

    def __init__(self, ledger_dir: Optional[Path] = None):
        self.ledger_dir = ledger_dir

    def __call__(self, task) -> dict:
        subjects = all_subjects(self.ledger_dir)
        subject = subjects[task.round_no % len(subjects)]
        return {"source": "swarm", "swarm": {"subject": subject["id"],
                                             "analysis_sha256": digest(analyze(subject))}}


class SwarmCheck:
    """work_sharing runner for swarm_check:<round>: recompute the scanned
    subject's analysis here. Returns None when this node doesn't have the
    subject, so the job passes to the next node in line."""

    def __init__(self, ledger_dir: Optional[Path] = None):
        self.ledger_dir = ledger_dir

    def __call__(self, task, scan_work: dict) -> Optional[dict]:
        claimed = ((scan_work.get("result_provenance") or {}).get("summary") or {}).get("swarm") or {}
        subject = resolve(claimed.get("subject", ""), self.ledger_dir)
        if subject is None:
            return None
        mine = digest(analyze(subject))
        return {"source": "swarm", "swarm": {"subject": subject["id"], "analysis_sha256": mine,
                                             "checks": scan_work.get("task"),
                                             "agrees": mine == claimed.get("analysis_sha256")}}


class SwarmTally:
    """Counts the swarm results this node has seen, its own included."""

    def __init__(self, quorum: int = 2, log=None):
        self.quorum = quorum
        self.rounds: dict[int, dict] = {}
        self.log = log

    def record(self, work: dict, origin) -> None:
        before = self.verdict(work.get("round"))["status"]
        self._record(work, origin)
        after = self.verdict(work.get("round"))
        if self.log and after["status"] != before and after["status"] in ("ACCEPTED", "DISPUTED"):
            self.log(f"swarm round {after['round']}: {after['status']} {after['subject']} "
                     f"(nodes {', '.join(after['agreeing_nodes'])} agree on "
                     f"{after['analysis_sha256'][:12]}…, {after['digests_seen']} digest(s) seen)")

    def _record(self, work: dict, origin) -> None:
        if work.get("kind") not in ("swarm", "swarm_check"):
            return
        swarm = ((work.get("result_provenance") or {}).get("summary") or {}).get("swarm") or {}
        if not swarm.get("analysis_sha256"):
            return
        entry = self.rounds.setdefault(work.get("round"), {"subject": swarm.get("subject"), "results": {}})
        if swarm.get("subject") != entry["subject"]:
            entry["subject_mismatch"] = True
        entry["results"][str(origin)] = swarm["analysis_sha256"]

    def verdict(self, round_no: int) -> dict:
        entry = self.rounds.get(round_no)
        if entry is None:
            return {"round": round_no, "status": "NOT_SEEN"}
        by_digest: dict[str, list[str]] = {}
        for origin, value in entry["results"].items():
            by_digest.setdefault(value, []).append(origin)
        best, nodes = max(by_digest.items(), key=lambda item: len(item[1]))
        if len(by_digest) > 1 or entry.get("subject_mismatch"):
            status = "DISPUTED"
        elif len(nodes) >= self.quorum:
            status = "ACCEPTED"
        else:
            status = "UNCONFIRMED"
        return {"round": round_no, "subject": entry["subject"], "status": status,
                "analysis_sha256": best, "agreeing_nodes": sorted(nodes),
                "digests_seen": len(by_digest)}

    def status(self) -> dict:
        verdicts = [self.verdict(r) for r in sorted(self.rounds)[-10:]]
        counts: dict[str, int] = {}
        for v in verdicts:
            counts[v["status"]] = counts.get(v["status"], 0) + 1
        return {"counts": counts, "recent": verdicts}
