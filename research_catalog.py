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

"""Local provider-neutral catalog for cited, permission-classified research."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Iterable

from extended_research_sources import search_europepmc, search_nih_grants
from multi_source_research import search_pubmed
from public_variant_sources import (
    lookup_ensembl_gene,
    lookup_gnomad_variant,
    search_ncbi_variants,
)
from research_matcher import find_trials

DEFAULT_CATALOG = Path("dna_shell_data") / "research_catalog.sqlite3"
CLASSIFICATIONS = frozenset({"public", "restricted", "private"})
SOURCE_TERMS = {
    "clinicaltrials.gov": "https://clinicaltrials.gov/policy",
    "pubmed": "https://www.ncbi.nlm.nih.gov/home/about/policies/",
    "nih_reporter": "https://reporter.nih.gov/",
    "europe_pmc": "https://europepmc.org/terms",
    "clinvar": "https://www.ncbi.nlm.nih.gov/home/about/policies/",
    "dbsnp": "https://www.ncbi.nlm.nih.gov/home/about/policies/",
    "ensembl": "https://www.ensembl.org/info/about/legal/",
    "gnomad": "https://gnomad.broadinstitute.org/terms",
}


class ResearchCatalog:
    def __init__(self, path: str | Path = DEFAULT_CATALOG):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS research_records (
                    record_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    abstract TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL,
                    published_at TEXT NOT NULL DEFAULT '',
                    retrieved_at REAL NOT NULL,
                    classification TEXT NOT NULL CHECK (
                        classification IN ('public', 'restricted', 'private')
                    ),
                    rights_status TEXT NOT NULL,
                    terms_url TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def add_records(self, records: Iterable[dict]) -> int:
        now = time.time()
        inserted = 0
        with self._connect() as connection:
            for record in records:
                normalized = normalize_record(record)
                key = hashlib.sha256(
                    f"{normalized['source']}\0{normalized['external_id']}".encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO research_records (
                        record_key, source, external_id, title, abstract, source_url,
                        published_at, retrieved_at, classification, rights_status, terms_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_key) DO UPDATE SET
                        title=excluded.title,
                        abstract=excluded.abstract,
                        source_url=excluded.source_url,
                        published_at=excluded.published_at,
                        retrieved_at=excluded.retrieved_at,
                        classification=excluded.classification,
                        rights_status=excluded.rights_status,
                        terms_url=excluded.terms_url
                    """,
                    (
                        key, normalized["source"], normalized["external_id"], normalized["title"],
                        normalized["abstract"], normalized["source_url"], normalized["published_at"],
                        now, normalized["classification"], normalized["rights_status"],
                        normalized["terms_url"],
                    ),
                )
                inserted += 1
        return inserted

    def retrieve(
        self,
        query: str,
        *,
        classification: str = "public",
        limit: int = 5,
    ) -> list[dict]:
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"classification must be one of {sorted(CLASSIFICATIONS)}")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        terms = list(dict.fromkeys(re.findall(r"[\w-]+", query.casefold())))
        if not terms:
            raise ValueError("query must contain at least one searchable word")

        conditions = " OR ".join("(lower(title) LIKE ? OR lower(abstract) LIKE ?)" for _ in terms)
        parameters: list[str] = []
        for term in terms:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parameters.extend((f"%{escaped}%", f"%{escaped}%"))

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT source, external_id, title, abstract, source_url, published_at,
                       classification, rights_status, terms_url
                FROM research_records
                WHERE classification = ? AND ({conditions})
                LIMIT 5000
                """,
                [classification, *parameters],
            ).fetchall()

        ranked = []
        for row in rows:
            title = row["title"].casefold()
            abstract = row["abstract"].casefold()
            title_hits = sum(title.count(term) for term in terms)
            abstract_hits = sum(abstract.count(term) for term in terms)
            score = (title_hits * 3) + abstract_hits
            if query.casefold() in title or query.casefold() in abstract:
                score += 5
            ranked.append((score, row))
        ranked.sort(key=lambda item: (-item[0], item[1]["source"], item[1]["external_id"]))

        results = []
        for score, row in ranked[:limit]:
            results.append({
                "citation": {
                    "source": row["source"],
                    "record_id": row["external_id"],
                    "title": row["title"],
                    "url": row["source_url"],
                    "published_at": row["published_at"] or None,
                },
                "abstract": row["abstract"],
                "retrieval_score": score,
                "classification": row["classification"],
                "rights_status": row["rights_status"],
                "terms_url": row["terms_url"],
            })
        return results

    def count(self, *, classification: str | None = None) -> int:
        with self._connect() as connection:
            if classification is None:
                row = connection.execute("SELECT COUNT(*) AS n FROM research_records").fetchone()
            else:
                if classification not in CLASSIFICATIONS:
                    raise ValueError(f"classification must be one of {sorted(CLASSIFICATIONS)}")
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM research_records WHERE classification = ?",
                    (classification,),
                ).fetchone()
        return int(row["n"])


def normalize_record(record: dict) -> dict[str, str]:
    source = str(record.get("source", "")).strip().lower()
    external_id = str(record.get("external_id", "")).strip()
    title = str(record.get("title", "")).strip()
    source_url = str(record.get("source_url", "")).strip()
    classification = str(record.get("classification", "private")).strip().lower()
    if not source or not external_id or not title or not source_url:
        raise ValueError("record requires source, external_id, title, and source_url")
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"classification must be one of {sorted(CLASSIFICATIONS)}")
    return {
        "source": source,
        "external_id": external_id,
        "title": title,
        "abstract": str(record.get("abstract", "")).strip(),
        "source_url": source_url,
        "published_at": str(record.get("published_at", "")).strip(),
        "classification": classification,
        "rights_status": str(record.get("rights_status", "unknown; check source terms")).strip(),
        "terms_url": str(record.get("terms_url", "")).strip(),
    }


def search_public_sources(
    query: str,
    *,
    sources: Iterable[str] = ("pubmed", "clinicaltrials.gov", "nih_reporter", "europe_pmc"),
    max_results: int = 10,
) -> list[dict]:
    """Query selected public sources and normalize citation-linked records."""
    if not query.strip():
        raise ValueError("query cannot be empty")
    if not 1 <= max_results <= 100:
        raise ValueError("max_results must be between 1 and 100")

    connectors = {
        "pubmed": search_pubmed,
        "clinicaltrials.gov": find_trials,
        "nih_reporter": search_nih_grants,
        "europe_pmc": search_europepmc,
        "clinvar": search_ncbi_variants,
        "dbsnp": search_ncbi_variants,
        "ensembl": lookup_ensembl_gene,
        "gnomad": lookup_gnomad_variant,
    }
    selected = list(dict.fromkeys(sources))
    if not selected:
        raise ValueError("at least one public source must be selected")
    unknown = set(selected) - set(connectors)
    if unknown:
        raise ValueError(f"unknown public source(s): {', '.join(sorted(unknown))}")

    normalized: list[dict] = []
    for source in selected:
        if source == "clinvar":
            normalized.extend(search_ncbi_variants(
                query, database="clinvar", max_results=max_results
            ))
            continue
        if source == "dbsnp":
            normalized.extend(search_ncbi_variants(
                query, database="snp", max_results=max_results
            ))
            continue
        if source == "ensembl":
            normalized.extend(lookup_ensembl_gene(query))
            continue
        if source == "gnomad":
            normalized.extend(lookup_gnomad_variant(query))
            continue
        records = (
            find_trials(query, max_results=max_results)
            if source == "clinicaltrials.gov"
            else connectors[source](query, max_results=max_results)
        )
        for record in records:
            external_id = (
                record.get("pmid") if source == "pubmed"
                else record.get("nct_id") if source == "clinicaltrials.gov"
                else record.get("project_num") if source == "nih_reporter"
                else record.get("id")
            )
            title = record.get("title")
            if not external_id or not title:
                continue
            source_url = record.get("url")
            if not source_url and source == "nih_reporter":
                source_url = f"https://reporter.nih.gov/project-details/{external_id}"
            if not source_url:
                continue
            published_at = (
                record.get("pub_date") or record.get("pub_year") or record.get("fiscal_year") or ""
            )
            normalized.append({
                "source": source,
                "external_id": str(external_id),
                "title": str(title),
                "abstract": str(record.get("abstract") or ""),
                "source_url": str(source_url),
                "published_at": str(published_at),
                "classification": "public",
                "rights_status": "unknown; review source and record terms",
                "terms_url": SOURCE_TERMS[source],
            })
    return normalized


def render_cited_context(query: str, records: list[dict]) -> dict:
    """Format citation-linked retrieved records for deliberate user transfer to an AI."""
    citations = []
    context_records = []
    for index, record in enumerate(records, start=1):
        citation = record["citation"]
        citations.append({
            "id": f"[{index}]",
            **citation,
            "rights_status": record["rights_status"],
            "terms_url": record["terms_url"],
        })
        context_records.append({
            "citation_id": f"[{index}]",
            "abstract": record["abstract"],
        })
    return {
        "query": query,
        "instruction": (
            "Use only these records as evidence, distinguish source facts from inference, "
            "and cite claims with the supplied citation IDs. If evidence is insufficient, say so."
        ),
        "records": context_records,
        "citations": citations,
        "automatic_provider_transfer": False,
    }


def load_jsonl_records(path: str | Path, *, classification: str) -> list[dict]:
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"classification must be one of {sorted(CLASSIFICATIONS)}")
    records = []
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on line {line_number}: {error.msg}") from error
            if not isinstance(record, dict):
                raise ValueError(f"line {line_number} must contain a JSON object")
            record["classification"] = classification
            records.append(normalize_record(record))
    return records
