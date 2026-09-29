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
research_crispr_link.py
=======================
Connects the published research records to the project's CRISPR tools and to
the modeled remission workflow, and puts both connections on the node chain.

Two commands:

  tag       Reads every published record's title and tags the CRISPR work it
            mentions (crispr, base_editing, guide_rna, ...) plus the gene
            symbols it names, and publishes public_crispr_relevance events.
            A tag says what the title mentions. It is not a judgment that the
            research supports an edit, a treatment or a clinical outcome.

  link-run  Takes a remission_workflow.py result (remission-model.v1), hashes
            it, and publishes a public_model_run_record event tying that run
            to the published records tagged for the same gene, optionally
            with a guide-RNA scan of a sequence you supply. The chain then
            shows the provenance chain: these public records, this modeled
            edit, this modeled outcome.

What never goes on the chain: sequences, mutation positions and base
changes are genomic data, so only the run's hash and counts are published.
And nothing here claims an edit would produce remission in a person. The
model is a string substitution; MODELED_REFERENCE_MATCH is kept separate
from CLINICALLY_CONFIRMED_REMISSION, which only ever comes from supplied,
attributed clinical evidence.

Usage:
    python research_crispr_link.py tag
    python research_crispr_link.py tag --confirm-publication
    python research_crispr_link.py link-run result.json --gene BRCA1
    python research_crispr_link.py link-run result.json --gene BRCA1 \
        --sequence-file brca1_fragment.txt --confirm-publication
    python research_crispr_link.py status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import research_publish
from research_ledger import published_events
from research_provenance import (
    CRISPR_TAG_METHOD,
    GUIDE_DESIGN_METHOD,
    SEQUENCE_ORIGINS,
    MAX_PUBLISHED_RECORDS,
    MAX_TAGGED_GENES,
    ResearchProvenanceQueue,
    create_public_crispr_relevance_event,
    create_public_model_run_event,
    create_public_sequence_event,
)
from research_publish import DEFAULT_OUTBOX

ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_DIR = ROOT / "autonomous"

# Each tag's phrases, matched case-insensitively on word boundaries in a
# record's published title. Kept small and literal on purpose: a reader can
# check any tag by eye against the title, which is also on the chain.
TAG_PHRASES: dict[str, tuple[str, ...]] = {
    "crispr": ("crispr", "crispr-cas9", "crispr/cas9", "crispri", "crispra"),
    "cas9": ("cas9", "cas12", "cas12a", "cas13", "spcas9", "nuclease"),
    "base_editing": ("base editing", "base editor", "base editors", "base-editing", "cytosine deaminase",
                     "adenine base editor"),
    "prime_editing": ("prime editing", "prime editor", "prime editors", "prime-editing"),
    "guide_rna": ("guide rna", "sgrna", "grna", "single guide", "guide design", "protospacer", "pam site"),
    "knockout": ("knockout", "knock-out", "knockdown", "gene silencing", "gene disruption", "gene editing",
                 "genome editing", "gene correction"),
    "screen": ("crispr screen", "genome-wide screen", "loss-of-function screen", "pooled screen"),
    "delivery": ("lipid nanoparticle", "adeno-associated virus", "aav vector", "electroporation",
                 "viral vector", "nanoparticle delivery"),
    "gene_therapy": ("gene therapy", "gene therapies", "cell and gene therapy"),
}
# Cancer-related gene symbols this project already works with, so a title's
# "BRCA1" is tagged but an ordinary capitalised word is not. Extend with
# --gene; anything else in a title is left untagged rather than guessed at.
KNOWN_GENES = (
    "ATM", "BARD1", "BRCA1", "BRCA2", "BRIP1", "CDH1", "CHEK2", "EGFR", "ERBB2", "KRAS",
    "MLH1", "MSH2", "MSH6", "MYC", "NBN", "NF1", "PALB2", "PIK3CA", "PMS2", "POLQ",
    "PTEN", "RAD51C", "RAD51D", "RB1", "STK11", "TP53", "VHL",
)
_TAG_RE = {
    tag: re.compile("|".join(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])" for phrase in phrases))
    for tag, phrases in TAG_PHRASES.items()
}


def tags_for_title(title: str) -> list[str]:
    """Every CRISPR tag whose phrases appear in `title`."""
    lowered = title.lower()
    return sorted(tag for tag, pattern in _TAG_RE.items() if pattern.search(lowered))


def genes_for_record(record: dict, known_genes: tuple[str, ...] = KNOWN_GENES) -> list[str]:
    """Known gene symbols named in the record's title or in the query that
    published it (the query is on the chain beside the record)."""
    text = f"{record.get('title', '')} {record.get('query', '')}".upper()
    found = {gene for gene in known_genes
             if re.search(rf"(?<![A-Z0-9]){re.escape(gene)}(?![A-Z0-9])", text)}
    return sorted(found)[:MAX_TAGGED_GENES]


def published_records(base_dir: Path) -> list[dict]:
    """Every published record once, with its corrected title applied."""
    import research_viewer

    records, seen = [], set()
    for record in research_viewer.collect(str(base_dir))["records"]:
        key = (record["source"], record["external_id"])
        if key not in seen:
            seen.add(key)
            records.append(record)
    return records


def already_tagged(base_dir: Path) -> dict[tuple[str, str], dict]:
    """(source, external_id) -> the tags published for it, by record hash, so
    a record is re-tagged only when its hash changed (e.g. a correction)."""
    tagged = {}
    for event in sorted(published_events(str(base_dir), "public_crispr_relevance").values(),
                        key=lambda event: event["created_at"]):
        for record in event["records"]:
            tagged[(record["source"], record["external_id"])] = record
    return tagged


def plan_tags(records: list[dict], tagged: dict[tuple[str, str], dict],
              known_genes: tuple[str, ...] = KNOWN_GENES) -> list[dict]:
    """Records that mention CRISPR work and are not already tagged with the
    same hash, tags and genes."""
    planned = []
    for record in records:
        tags = tags_for_title(record["title"])
        if not tags:
            continue
        entry = {
            "source": record["source"],
            "external_id": record["external_id"],
            "record_sha256": record["record_sha256"],
            "tags": tags,
            "genes": genes_for_record(record, known_genes),
            "title": record["title"],
        }
        previous = tagged.get((record["source"], record["external_id"]))
        if previous and all(previous.get(field) == entry[field]
                            for field in ("record_sha256", "tags", "genes")):
            continue
        planned.append(entry)
    return planned


def tag_events(planned: list[dict], *, time_anchor: dict | None = None) -> list[dict]:
    return [
        create_public_crispr_relevance_event(
            planned[start:start + MAX_PUBLISHED_RECORDS],
            confirm_publication=True, time_anchor=time_anchor,
        )
        for start in range(0, len(planned), MAX_PUBLISHED_RECORDS)
    ]


# ------------------------------------------------------------- model runs

def run_digest(result: dict) -> str:
    """SHA-256 of the full run, canonically encoded. The run itself (which
    holds sequences) stays off the chain; this hash identifies it."""
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_sequence(path: Path) -> str:
    """A plain or FASTA DNA sequence from `path` (never published)."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return "".join(line for line in lines if line and not line.startswith(">"))


def guide_summary(sequence: str, top_n: int = 5) -> dict:
    """Guide-RNA candidates for `sequence`, reduced to what may be published:
    the sequence's hash, how many candidates the PAM scan found, and the best
    heuristic score as an integer per mille. No guide sequence is published,
    and the score is an efficiency heuristic, not a clinical judgment."""
    from crispr_guide_design import find_guide_candidates

    candidates = find_guide_candidates(sequence, top_n=top_n)
    return {
        "method": GUIDE_DESIGN_METHOD,
        "sequence_sha256": hashlib.sha256(sequence.upper().encode("utf-8")).hexdigest(),
        "candidate_count": len(candidates),
        "top_score": round(1000 * max((c["score"] for c in candidates), default=0.0)),
    }


def related_records(base_dir: Path, genes: list[str], tags: list[str] | None = None,
                    limit: int = MAX_PUBLISHED_RECORDS) -> list[dict]:
    """Published, CRISPR-tagged records naming any of `genes` (and, if given,
    carrying any of `tags`), newest first."""
    wanted_genes, wanted_tags = {g.upper() for g in genes}, set(tags or [])
    matched = []
    for record in published_records(base_dir):
        entry = already_tagged(base_dir).get((record["source"], record["external_id"]))
        if entry is None or not wanted_genes & set(entry["genes"]):
            continue
        if wanted_tags and not wanted_tags & set(entry["tags"]):
            continue
        matched.append({
            "source": record["source"],
            "external_id": record["external_id"],
            "record_sha256": record["record_sha256"],
            "title": record["title"],
            "tags": entry["tags"],
        })
    return matched[:limit]


def stage_ledger(result: dict) -> list[dict]:
    """remission_core.py's hash-linked stages, reduced to hashes. This is what
    makes the mutation detection and the modeled edit provable from the chain:
    each stage's payload hash and its link to the stage before it."""
    return [
        {
            "index": block["index"],
            "kind": block["kind"],
            "payload_sha256": block["payload_sha256"],
            "block_hash": block["block_hash"],
            "previous_hash": block["previous_hash"],
        }
        for block in result["ledger"]["blocks"]
    ]


def sequence_events(result: dict, *, origin: str, label: str, accession: str | None = None,
                    source: str | None = None, time_anchor: dict | None = None) -> list[dict]:
    """The run's reference and sample sequences as publishable events. Only
    for a public reference or a synthetic case: `origin` is checked by
    research_provenance.create_public_sequence_event, which refuses anything
    from a person's sample."""
    stage_labels = {"REFERENCE": "reference", "CANCER_SAMPLE": "cancer sample", "POST_EDIT": "modeled edit"}
    return [
        create_public_sequence_event(
            origin=origin, bases=bases, label=f"{label} ({stage_labels[part]})",
            accession=accession, source=source, confirm_publication=True, time_anchor=time_anchor,
        )
        for part in ("REFERENCE", "CANCER_SAMPLE", "POST_EDIT")
        if (bases := _stage_sequence(result, part))
    ]


def _stage_sequence(result: dict, kind: str) -> str | None:
    """The sequence a run stage holds. The run's `records` are keyed by each
    stage's payload hash (remission_core.py keeps the payloads off the
    ledger), so the stage's hash is the lookup key."""
    records = result.get("records") or {}
    for block in result["ledger"]["blocks"]:
        if block["kind"] == kind:
            return (records.get(block["payload_sha256"]) or {}).get("sequence")
    return None


def model_run_event(result: dict, records: list[dict], *, guide_design: dict | None = None,
                    sequence_event_ids: list[str] | None = None, time_anchor: dict | None = None) -> dict:
    """The publishable provenance of one remission_workflow.py result."""
    assessment = result["assessment"]
    return create_public_model_run_event(
        run_sha256=run_digest(result),
        modeled_status=assessment["modeled_status"],
        longitudinal_trend=assessment["longitudinal_trend"],
        clinical_status=assessment["clinical_status"]["status"],
        mutation_count=len(result.get("mutations") or []),
        records=[{k: r[k] for k in ("source", "external_id", "record_sha256")} for r in records],
        stage_ledger=stage_ledger(result),
        sequence_event_ids=sequence_event_ids,
        guide_design=guide_design,
        confirm_publication=True,
        time_anchor=time_anchor,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    tag = sub.add_parser("tag", help="tag published records for CRISPR relevance")
    link = sub.add_parser("link-run", help="link a modeled remission run to published records")
    link.add_argument("result", type=Path, help="remission_workflow.py --output JSON")
    link.add_argument("--gene", action="append", default=[], required=True,
                      help="gene this case is about (repeatable); links records tagged with it")
    link.add_argument("--tag", action="append", default=[], help="only link records carrying this CRISPR tag")
    link.add_argument("--sequence-file", type=Path,
                      help="DNA sequence (plain or FASTA) to scan for guide-RNA candidates; never published")
    link.add_argument("--publish-sequences", choices=sorted(SEQUENCE_ORIGINS),
                      help="also put this run's reference, sample and edited sequences on the chain. Only for "
                           "'public_reference' (needs --accession) or 'synthetic' cases. A sequence from a "
                           "person's sample must not be published and is refused.")
    link.add_argument("--accession", help="public database accession for --publish-sequences public_reference")
    link.add_argument("--sequence-label", default="modeled remission run",
                      help="short label published with the sequences (no identifiers)")
    status = sub.add_parser("status", help="how many published records are tagged, and which runs are linked")
    for p in (tag, link, status):
        p.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
        p.add_argument("--outbox", type=Path, default=DEFAULT_OUTBOX)
        if p is not status:
            p.add_argument("--confirm-publication", action="store_true",
                           help="queue the event(s) for the permanent node chain")
    args = parser.parse_args(argv)

    if args.command == "status":
        records = published_records(args.base_dir)
        tagged = already_tagged(args.base_dir)
        runs = published_events(str(args.base_dir), "public_model_run_record")
        print(f"{len(tagged)} of {len(records)} published records tagged (method {CRISPR_TAG_METHOD})")
        for run in sorted(runs.values(), key=lambda event: event["created_at"]):
            guide = run["guide_design"]
            print(f"  run {run['run_sha256'][:12]}: {run['modeled_status']}, {run['clinical_status']}, "
                  f"{run['record_count']} linked record(s)"
                  + (f", {guide['candidate_count']} guide candidate(s)" if guide else ""))
        return 0

    if args.command == "tag":
        planned = plan_tags(published_records(args.base_dir), already_tagged(args.base_dir))
        for entry in planned:
            print(f"{entry['source']}:{entry['external_id']}  {','.join(entry['tags'])}"
                  f"  genes={','.join(entry['genes']) or '-'}")
            print(f"   {entry['title'][:110]}")
        events = tag_events(planned, time_anchor=research_publish.current_time_anchor()
                            if args.confirm_publication and planned else None)
        print(f"{len(planned)} record(s) to tag in {len(events)} event(s)")
    else:
        result = json.loads(args.result.read_text(encoding="utf-8"))
        if result.get("schema") != "remission-model.v1":
            print("Result must be a remission-model.v1 JSON from remission_workflow.py.")
            return 2
        records = related_records(args.base_dir, args.gene, args.tag)
        guide = guide_summary(read_sequence(args.sequence_file)) if args.sequence_file else None
        anchor = research_publish.current_time_anchor() if args.confirm_publication else None
        sequences = []
        if args.publish_sequences:
            if args.publish_sequences == "public_reference" and not args.accession:
                print("--publish-sequences public_reference needs --accession naming the public record.")
                return 2
            sequences = sequence_events(
                result, origin=args.publish_sequences, label=args.sequence_label,
                accession=args.accession, source="ncbi_nuccore" if args.accession else None,
                time_anchor=anchor,
            )
        event = model_run_event(result, records, guide_design=guide,
                               sequence_event_ids=[s["event_id"] for s in sequences], time_anchor=anchor)
        print(f"modeled status: {event['modeled_status']}   clinical status: {event['clinical_status']}")
        print(f"run hash: {event['run_sha256']}")
        if guide:
            print(f"guide scan: {guide['candidate_count']} candidate(s), best heuristic score "
                  f"{guide['top_score'] / 1000:.3f} (efficiency heuristic, not clinical evidence)")
        print(f"stage ledger: {len(event['stage_ledger'])} hash-linked stage(s) "
              f"({', '.join(s['kind'] for s in event['stage_ledger'])})")
        if sequences:
            print(f"sequences on chain ({args.publish_sequences}): "
                  + ", ".join(f"{s['sequence']['label']} {s['sequence']['base_count']} bases" for s in sequences))
        else:
            print("sequences: kept off the chain (hashes only)")
        print(f"linked {len(records)} published record(s) for {','.join(args.gene)}:")
        for record in records:
            print(f"  {record['source']}:{record['external_id']}  {','.join(record['tags'])}"
                  f"  {record['title'][:80]}")
        print(event["disclaimer"])
        events = [*sequences, event]

    if not args.confirm_publication:
        print("Dry run: nothing queued. Add --confirm-publication to publish these permanently.")
        return 0
    queue = ResearchProvenanceQueue(args.outbox)
    for event in events:
        queue.enqueue(event)
    print(f"Queued {len(events)} event(s) for node-0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
