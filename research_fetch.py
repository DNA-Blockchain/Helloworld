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
research_fetch.py
=================
Fetch half of the split research agent. Queries public sources through
research_catalog.search_public_sources (PubMed, Europe PMC,
ClinicalTrials.gov, NIH RePORTER) over HTTPS on the host, and writes a
bounded RESEARCH.JSON that research_analysis.py ranks, either here or as a
Network OS MicroPython task (the kernel has no TLS, so fetching stays on
the host and the records reach the kernel as data, never code).

Usage:
    python research_fetch.py --query "CRISPR cancer" --term crispr --term "g>a"
    python research_fetch.py --query "CRISPR cancer" --output RESEARCH.JSON --analyze
    python research_fetch.py --fixture --output RESEARCH.JSON   # offline sample
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import research_analysis

DEFAULT_SOURCES = ("pubmed", "europe_pmc", "clinicaltrials.gov")
MAX_ABSTRACT_CHARS = 400
KEPT_FIELDS = ("source", "external_id", "title", "abstract", "source_url", "published_at", "classification")

# Synthetic, clearly labelled records for offline tests and the kernel boot
# check. The IDs are not real PubMed, Europe PMC or trial identifiers.
FIXTURE_REQUEST = {
    "schema": research_analysis.INPUT_SCHEMA,
    "query": "CRISPR cancer G>A",
    "terms": ["crispr", "cancer", "g>a"],
    "fetched_at": "synthetic",
    "records": [
        {"source": "pubmed", "external_id": "SYNTH-PM-1", "title": "CRISPR base editing of a G>A cancer variant",
         "abstract": "Synthetic record: correcting a G>A substitution with CRISPR base editors in cancer cells.",
         "source_url": "https://example.invalid/synth-pm-1", "published_at": "2025 Jan", "classification": "public"},
        {"source": "europe_pmc", "external_id": "SYNTH-EU-1", "title": "CRISPR Base Editing of a G>A Cancer Variant.",
         "abstract": "", "source_url": "https://example.invalid/synth-eu-1", "published_at": "2025",
         "classification": "public"},
        {"source": "clinicaltrials.gov", "external_id": "SYNTH-CT-1", "title": "Trial of CRISPR-edited cells in solid cancer",
         "abstract": "", "source_url": "https://example.invalid/synth-ct-1", "published_at": "2023",
         "classification": "public"},
        {"source": "pubmed", "external_id": "SYNTH-PM-2", "title": "Survey of gene therapy delivery methods",
         "abstract": "Synthetic record with no query terms in the title.", "source_url": "https://example.invalid/synth-pm-2",
         "published_at": "2019", "classification": "public"},
        {"source": "pubmed", "external_id": "SYNTH-PM-1", "title": "CRISPR base editing of a G>A cancer variant",
         "abstract": "Exact duplicate by source and ID.", "source_url": "https://example.invalid/synth-pm-1",
         "published_at": "2025 Jan", "classification": "public"},
    ],
}


def build_request(query: str, terms: list[str], records: list[dict]) -> dict:
    """Keep public records only, trim abstracts, and shrink until the JSON
    fits the kernel task's 64-KiB input limit."""
    kept = []
    for record in records:
        if record.get("classification", "public") != "public":
            continue
        if record.get("source") not in research_analysis.PUBLIC_SOURCES:
            continue
        slim = {field: str(record.get(field) or "") for field in KEPT_FIELDS}
        slim["abstract"] = slim["abstract"][:MAX_ABSTRACT_CHARS]
        slim["classification"] = "public"
        kept.append(slim)
    request = {
        "schema": research_analysis.INPUT_SCHEMA,
        "query": query,
        "terms": terms or query.lower().split(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "records": kept[: research_analysis.MAX_RECORDS],
    }
    while len(json.dumps(request).encode("utf-8")) > research_analysis.MAX_INPUT_BYTES and request["records"]:
        request["records"].pop()
    return request


def fetch(query: str, terms: list[str], sources: list[str], max_results: int) -> dict:
    from research_catalog import search_public_sources

    records = search_public_sources(query, sources=sources, max_results=max_results)
    return build_request(query, terms, records)


def format_ranking(result: dict) -> str:
    lines = [
        "Query: {query}  ({unique_records} unique of {input_records}, {duplicates_removed} duplicates)".format(**result)
    ]
    for entry in result["ranked"]:
        lines.append(
            "{rank:>2}. [{score}] {source}:{external_id}  {title}".format(**entry)
        )
    lines.append(research_analysis.NOTE)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--query", help="search query sent to each public source")
    parser.add_argument("--term", action="append", default=[], help="scoring term (repeatable; default: query words)")
    parser.add_argument("--source", action="append", choices=research_analysis.PUBLIC_SOURCES,
                        help="public source to query (repeatable; default: pubmed, europe_pmc, clinicaltrials.gov)")
    parser.add_argument("--max-results", type=int, default=10, help="records per source (1-100)")
    parser.add_argument("--fixture", action="store_true", help="use the synthetic offline records instead of fetching")
    parser.add_argument("--output", type=Path, help="write RESEARCH.JSON here")
    parser.add_argument("--analyze", action="store_true", help="also rank the records locally and print the result")
    args = parser.parse_args(argv)

    if args.fixture:
        request = FIXTURE_REQUEST
    elif args.query:
        request = fetch(args.query, [t.lower() for t in args.term], args.source or list(DEFAULT_SOURCES), args.max_results)
    else:
        parser.error("--query is required unless --fixture is given")

    if args.output:
        args.output.write_text(json.dumps(request, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {len(request['records'])} records to {args.output}")
    if args.analyze or not args.output:
        print(format_ranking(research_analysis.run(request)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
