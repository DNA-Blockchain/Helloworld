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
dataset_publish.py
==================
Adds public reference datasets to the node chain: downloads each NCBI
nucleotide accession as FASTA into autonomous/datasets/, validates it with
the same FASTA checks as dna_shell.py, and queues a public_dataset_record
event (accession, title, sequence and base counts, SHA-256, NCBI link) for
node-0 to publish. The sequence itself never goes on the chain; the viewer
serves the verified local copy, and anyone can pull it from NCBI and check
it against the published hash.

Only public reference data belongs here (RefSeq/GenBank accessions). Local
or private FASTA files go through dna_shell.py and dataset_sharing.py.

Usage:
    python dataset_publish.py NM_007294.4 NM_000059.4               # dry run
    python dataset_publish.py NM_007294.4 --confirm-publication
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dna_shell import _analyze_fasta
from research_ledger import published_dataset_accessions
from research_provenance import ResearchProvenanceQueue, create_public_dataset_record_event
from research_publish import DEFAULT_OUTBOX

ROOT = Path(__file__).resolve().parent
DEFAULT_STORE = ROOT / "autonomous" / "datasets"


def fetch_dataset(accession: str, store: Path) -> dict:
    """Download (or reuse) <store>/<accession>.fasta and return its manifest.
    A manifest is reused only if the stored file still matches its hash, so
    the dataset keeps one ID across runs."""
    from public_variant_sources import fetch_nuccore_fasta

    store.mkdir(parents=True, exist_ok=True)
    fasta_path = store / f"{accession}.fasta"
    manifest_path = store / f"{accession}.json"
    if manifest_path.exists() and fasta_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if _analyze_fasta(fasta_path)["sha256"] == manifest.get("sha256"):
            return manifest
    data = fetch_nuccore_fasta(accession)
    fasta_path.write_bytes(data)
    report = _analyze_fasta(fasta_path)
    if not report["valid"]:
        fasta_path.unlink()
        raise ValueError(f"{accession} is not valid FASTA: {'; '.join(report['errors'][:3])}")
    header = data.split(b"\n", 1)[0][1:].decode("utf-8", "replace").strip()
    manifest = {
        "schema_version": 1,
        "dataset_id": str(uuid.uuid4()),
        "accession": accession,
        "source": "ncbi_nuccore",
        "title": header[:200] or accession,
        "format": "FASTA",
        "classification": "public",
        "stored_file": fasta_path.name,
        "sha256": report["sha256"],
        "sequence_count": report["sequence_count"],
        "total_bases": report["total_bases"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("accessions", nargs="+", help="versioned NCBI nucleotide accessions, e.g. NM_007294.4")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE, help="where the FASTA files are kept")
    parser.add_argument("--ledgers", type=Path, default=ROOT / "autonomous")
    parser.add_argument("--outbox", type=Path, default=DEFAULT_OUTBOX)
    parser.add_argument("--confirm-publication", action="store_true",
                        help="queue the dataset records for the permanent node chain")
    args = parser.parse_args(argv)

    already = published_dataset_accessions(str(args.ledgers))
    events = []
    for accession in dict.fromkeys(args.accessions):
        if accession in already:
            print(f"{accession}: already published, skipped")
            continue
        try:
            manifest = fetch_dataset(accession, args.store)
        except (RuntimeError, ValueError) as error:
            print(f"{accession}: {error}")
            continue
        events.append(create_public_dataset_record_event(
            dataset_id=manifest["dataset_id"],
            accession=accession,
            title=manifest["title"],
            sequence_count=manifest["sequence_count"],
            total_bases=manifest["total_bases"],
            dataset_sha256=manifest["sha256"],
            confirm_publication=True,
        ))
        print(f"{accession}: {manifest['total_bases']} bases, sha256 {manifest['sha256'][:16]}...  {manifest['title'][:80]}")
    if not args.confirm_publication:
        print(f"Dry run: {len(events)} dataset record(s) not queued. Add --confirm-publication to publish.")
        return 0
    queue = ResearchProvenanceQueue(args.outbox)
    for event in events:
        queue.enqueue(event)
    print(f"Queued {len(events)} dataset record(s) for node-0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
