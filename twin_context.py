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
twin_context.py
===============
Context for a DNA digital twin that is not part of the model: what public
databases say about a gene's variants, and what clinical annotations describe
a case. Both stay on this machine.

Two kinds:

  ClinVar classifications   ClinVar's own reported significance for variants
                            in a gene, with its review status, the conditions
                            named, and a link. Fetched once and cached under
                            autonomous/clinvar/, so the twin works offline
                            afterwards. Every row is attributed to ClinVar and
                            its submitters, never to this project.

  Clinical context          Hormone-receptor and similar tumour annotations
                            (ER, PR, HER2, grade, stage). These describe a
                            tumour, not a DNA sequence: receptor status
                            reflects which proteins a cell makes, not which
                            bases it carries. So context never feeds the
                            modeled edit. It is recorded beside the twin and
                            used to choose which published research to show.

Why context cannot drive an edit: hormones change what a gene transcribes,
not the gene's sequence. There is no step from a receptor status to a base to
change, so this module deliberately offers none. It filters reading material
and labels a case; that is all.

Nothing here is published. Receptor status and stage are clinical details
about a person, and the chain is append-only, so this module has no publish
path at all.

Usage:
    python twin_context.py clinvar BRCA1 --fetch
    python twin_context.py clinvar BRCA1
    python twin_context.py context --set ER+ --set HER2- --label "case A"
    python twin_context.py context
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_DIR = ROOT / "autonomous"
CONTEXT_SCHEMA = "twin-clinical-context.v1"
CLINVAR_CACHE_SCHEMA = "clinvar-cache.v1"

# Tumour annotations this module understands. Each is a standard reported
# status, and each maps to the research tags worth reading for it -- never to
# a DNA edit.
RECEPTOR_MARKERS = {
    "ER+": ("hormone_signalling", "expression"),
    "ER-": ("expression",),
    "PR+": ("hormone_signalling", "expression"),
    "PR-": ("expression",),
    "HER2+": ("expression",),
    "HER2-": ("expression",),
    "TRIPLE-NEGATIVE": ("expression", "knockout"),
}
_GRADE_RE = re.compile(r"^G[1-3]$")
_STAGE_RE = re.compile(r"^(0|I|II|III|IV)[ABC]?$")
MAX_CONTEXT_ENTRIES = 12


def clinvar_cache_path(base_dir: Path, gene: str) -> Path:
    return Path(base_dir) / "clinvar" / f"{gene.strip().upper()}.json"


def load_clinvar(base_dir: Path, gene: str) -> dict | None:
    """The cached ClinVar classifications for `gene`, or None."""
    try:
        cached = json.loads(clinvar_cache_path(base_dir, gene).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cached if cached.get("schema") == CLINVAR_CACHE_SCHEMA else None


def fetch_clinvar(base_dir: Path, gene: str, *, max_results: int = 10,
                  significance: str | None = None, fetcher=None) -> dict:
    """Fetch ClinVar's classifications for `gene` and cache them locally."""
    if fetcher is None:
        from public_variant_sources import clinvar_classifications as fetcher
    records = fetcher(gene, max_results=max_results, significance=significance)
    cached = {
        "schema": CLINVAR_CACHE_SCHEMA,
        "gene": gene.strip().upper(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query_significance": significance,
        "record_count": len(records),
        "records": records,
        "attribution": "ClinVar (NCBI) and its submitters. Not a judgment by this project.",
    }
    path = clinvar_cache_path(base_dir, gene)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cached, indent=1, ensure_ascii=False), encoding="utf-8")
    return cached


def clinvar_for_genes(base_dir: Path, genes: list[str]) -> list[dict]:
    """Cached ClinVar classifications for these genes, newest cache first."""
    found = []
    for gene in genes:
        cached = load_clinvar(base_dir, gene)
        if cached:
            found.extend(cached["records"])
    return found


# ------------------------------------------------------- publishing ClinVar
# Cached ClinVar rows are public metadata from an allowed public database, so
# they may go on the chain, attributed to ClinVar. The local clinical context
# above never can: that describes a person.

def published_accessions(base_dir: Path) -> set[str]:
    """Accessions already carried by a published variant classification."""
    from research_ledger import published_events

    return {
        record["accession"]
        for event in published_events(str(base_dir), "public_variant_classification").values()
        for record in event["records"]
    }


def plan_variant_events(base_dir: Path, genes: list[str], *, time_anchor: dict | None = None) -> list[dict]:
    """One event per 20 cached ClinVar rows that are not on the chain yet."""
    from research_provenance import MAX_VARIANT_RECORDS, create_public_variant_classification_event

    known = published_accessions(base_dir)
    pending, seen = [], set()
    for record in clinvar_for_genes(base_dir, genes):
        accession = record["accession"]
        if accession in known or accession in seen:
            continue
        seen.add(accession)
        pending.append({
            "uid": record["uid"],
            "accession": accession,
            "gene": record["gene"],
            "title": record["title"],
            "variant_type": record.get("variant_type", ""),
            "significance": record["clinvar_classification"],
            "review_status": record.get("clinvar_review_status", ""),
            "last_evaluated": record.get("clinvar_last_evaluated", ""),
            "conditions": record.get("conditions") or [],
            "source_url": record["source_url"],
        })
    return [
        create_public_variant_classification_event(
            pending[start:start + MAX_VARIANT_RECORDS],
            confirm_publication=True, time_anchor=time_anchor,
        )
        for start in range(0, len(pending), MAX_VARIANT_RECORDS)
    ]


# ------------------------------------------------------------------ context

def normalise_marker(value: str) -> str:
    text = " ".join(str(value).strip().upper().split())
    return text.replace("TRIPLE NEGATIVE", "TRIPLE-NEGATIVE")


def validate_context(entries: list[str]) -> dict:
    """Turn reported annotations into a checked context record. Unknown values
    are refused rather than guessed at, so the twin never shows an annotation
    this module does not understand."""
    if len(entries) > MAX_CONTEXT_ENTRIES:
        raise ValueError(f"at most {MAX_CONTEXT_ENTRIES} context entries")
    markers, grade, stage = [], None, None
    for raw in entries:
        value = normalise_marker(raw)
        if value in RECEPTOR_MARKERS:
            if value not in markers:
                markers.append(value)
        elif _GRADE_RE.fullmatch(value):
            grade = value
        elif _STAGE_RE.fullmatch(value):
            stage = value
        else:
            raise ValueError(
                f"unknown clinical context {raw!r}; use one of "
                f"{sorted(RECEPTOR_MARKERS)}, a grade G1-G3, or a stage 0/I/II/III/IV"
            )
    return {
        "schema": CONTEXT_SCHEMA,
        "markers": sorted(markers),
        "grade": grade,
        "stage": stage,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "published": False,
        "note": (
            "Reported tumour annotations, recorded locally and never published. They describe which "
            "proteins a tumour makes and how it was staged, not which DNA bases it carries, so they "
            "do not affect the modeled edit; they select which published research is shown."
        ),
    }


def research_tags_for_context(context: dict | None) -> list[str]:
    """The research tags worth reading for this context."""
    if not context:
        return []
    tags = set()
    for marker in context.get("markers") or []:
        tags.update(RECEPTOR_MARKERS.get(marker, ()))
    return sorted(tags)


def context_path(base_dir: Path, label: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip()) or "case"
    return Path(base_dir) / "context" / f"{safe[:60]}.json"


def save_context(base_dir: Path, label: str, context: dict) -> Path:
    path = context_path(base_dir, label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**context, "label": label}, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    return path


def load_context(base_dir: Path, label: str) -> dict | None:
    try:
        stored = json.loads(context_path(base_dir, label).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stored if stored.get("schema") == CONTEXT_SCHEMA else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    clinvar = sub.add_parser("clinvar", help="show or fetch ClinVar's classifications for a gene")
    clinvar.add_argument("gene")
    clinvar.add_argument("--fetch", action="store_true", help="query NCBI now and refresh the local cache")
    clinvar.add_argument("--max-results", type=int, default=10)
    clinvar.add_argument("--significance", help="only this reported significance (e.g. Pathogenic)")
    clinvar.add_argument("--publish", action="store_true",
                        help="also queue the cached rows for the chain as ClinVar's own attributed "
                             "classifications (needs --confirm-publication)")
    clinvar.add_argument("--confirm-publication", action="store_true",
                        help="with --publish, queue the events permanently for node-0")
    clinvar.add_argument("--outbox", type=Path, help="provenance outbox (default: research_publish's)")
    context = sub.add_parser("context", help="record or show local clinical context for a case")
    context.add_argument("--set", action="append", default=[], dest="entries",
                         help="an annotation such as ER+, HER2-, G2, II (repeatable)")
    context.add_argument("--label", default="case", help="which case this context belongs to")
    for p in (clinvar, context):
        p.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    args = parser.parse_args(argv)

    if args.command == "clinvar":
        if args.fetch:
            try:
                cached = fetch_clinvar(args.base_dir, args.gene, max_results=args.max_results,
                                       significance=args.significance)
            except (OSError, ValueError, RuntimeError) as error:
                print(f"ClinVar fetch failed: {error}")
                return 1
            print(f"cached {cached['record_count']} ClinVar record(s) for {cached['gene']}")
        cached = load_clinvar(args.base_dir, args.gene)
        if not cached:
            print(f"No cached ClinVar records for {args.gene.upper()}. Run with --fetch.")
            return 1
        print(f"{cached['gene']}: {cached['record_count']} record(s), fetched {cached['fetched_at'][:19]}")
        for record in cached["records"]:
            print(f"  {record['accession']}  {record['clinvar_classification']}"
                  f"  ({record['clinvar_review_status'] or 'no review status'})")
            print(f"     {record['title'][:100]}")
            if record["conditions"]:
                print(f"     conditions: {', '.join(record['conditions'][:3])}")
        print(cached["attribution"])
        if not args.publish:
            return 0

        import research_publish
        from research_provenance import ResearchProvenanceQueue

        anchor = research_publish.current_time_anchor() if args.confirm_publication else None
        events = plan_variant_events(args.base_dir, [args.gene], time_anchor=anchor)
        new_rows = sum(event["record_count"] for event in events)
        already = len(cached["records"]) - new_rows
        print(f"{new_rows} classification(s) to publish in {len(events)} event(s)"
              + (f"; {already} already on the chain" if already > 0 else ""))
        if not args.confirm_publication:
            print("Dry run: nothing queued. Add --confirm-publication to publish these permanently.")
            return 0
        queue = ResearchProvenanceQueue(args.outbox or research_publish.DEFAULT_OUTBOX)
        for event in events:
            queue.enqueue(event)
        print(f"Queued {len(events)} event(s) for node-0, attributed to ClinVar.")
        return 0

    if args.entries:
        try:
            context = validate_context(args.entries)
        except ValueError as error:
            print(error)
            return 2
        path = save_context(args.base_dir, args.label, context)
        print(f"recorded {len(context['markers'])} marker(s) for {args.label} in {path}")
    context = load_context(args.base_dir, args.label)
    if not context:
        print(f"No clinical context recorded for {args.label!r}. Add some with --set.")
        return 1
    print(f"{args.label}: markers {', '.join(context['markers']) or '-'}"
          f"  grade {context['grade'] or '-'}  stage {context['stage'] or '-'}")
    print(f"research tags to read for this context: {', '.join(research_tags_for_context(context)) or '-'}")
    print(context["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
