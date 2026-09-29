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

"""Research provenance events for explicit peer-network sharing: hash-only
events, plus confirmed publication of public bibliographic records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PROVENANCE_SCHEMA_VERSION = 1
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_RE = re.compile(r"^[a-z0-9_.-]{1,64}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_EVENT_RE = re.compile(r"^[0-9a-f]{32}$")
_PUBLIC_SOURCES = frozenset({
    "pubmed",
    "clinicaltrials.gov",
    "nih_reporter",
    "europe_pmc",
    "clinvar",
    "dbsnp",
    "ensembl",
    "gnomad",
})


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_public_provenance(
    query: str,
    records: list[dict],
    sources: Iterable[str],
    answer: str,
    model: str = "local-model-unspecified",
) -> dict:
    """Create a provenance envelope without persisting query, records, or answer."""
    if not query.strip():
        raise ValueError("query cannot be empty")
    source_names = sorted(set(sources))
    if not source_names or any(
        not _SOURCE_RE.fullmatch(source) or source not in _PUBLIC_SOURCES
        for source in source_names
    ):
        raise ValueError("provenance requires valid source names")
    if len(records) > 1000:
        raise ValueError("provenance supports at most 1000 records")
    if not isinstance(answer, str):
        raise ValueError("answer must be text")
    if not isinstance(model, str) or not _MODEL_RE.fullmatch(model):
        raise ValueError("provenance requires a valid local model identifier")
    event = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "event_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "public",
        "sources": source_names,
        "backend": "ollama-local",
        "model": model,
        "record_count": len(records),
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "records_sha256": _canonical_hash(records),
        "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
    }
    validate_public_provenance(event)
    return event


def create_public_data_hash_event(
    *,
    data_sha256: str,
    data_kind: str,
    classification: str,
    confirm_hash_publication: bool = False,
) -> dict:
    if classification != "public":
        raise PermissionError("only data classified public may publish a hash")
    if confirm_hash_publication is not True:
        raise PermissionError("explicit confirmation is required before publishing a data hash")
    if not isinstance(data_sha256, str) or not _HASH_RE.fullmatch(data_sha256):
        raise ValueError("data hash must be a lowercase SHA-256 digest")
    if data_kind not in {"dataset", "biological_sequence", "research_file"}:
        raise ValueError("data kind must be dataset, biological_sequence, or research_file")
    event = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "event_type": "public_data_hash",
        "event_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "public",
        "data_kind": data_kind,
        "data_sha256": data_sha256,
    }
    validate_public_provenance(event)
    return event


MAX_PUBLISHED_RECORDS = 20
MAX_PUBLISHED_EVENT_BYTES = 32 * 1024
_PUBLISHED_RECORD_FIELDS = {
    "source": 32,
    "external_id": 64,
    "title": 300,
    "source_url": 300,
    "published_at": 32,
    "record_sha256": 64,
}


_ANCHOR_SOURCES = {"blockstream.info", "mempool.space"}


def _validate_time_anchor(anchor: object) -> None:
    """An optional "not before" anchor: the Bitcoin tip block when the event
    was created (external_chain_bridge.fetch_bitcoin_anchor)."""
    if not isinstance(anchor, dict) or set(anchor) != {"chain", "height", "block_hash", "source"}:
        raise ValueError("time anchor must hold chain, height, block_hash and source")
    if anchor["chain"] != "bitcoin" or anchor["source"] not in _ANCHOR_SOURCES:
        raise ValueError("time anchor must be a Bitcoin block from a known public explorer")
    if type(anchor["height"]) is not int or not 0 < anchor["height"] < 100_000_000:
        raise ValueError("time anchor has an invalid block height")
    if not isinstance(anchor["block_hash"], str) or not _HASH_RE.fullmatch(anchor["block_hash"]):
        raise ValueError("time anchor has an invalid block hash")


def _require_timestamp(value: object, kind: str) -> None:
    try:
        timestamp = datetime.fromisoformat(value)   # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{kind} event has an invalid timestamp") from error
    if timestamp.tzinfo is None:
        raise ValueError(f"{kind} event timestamp must include a timezone")


def _check_fields(event: dict, expected: set[str], kind: str) -> None:
    """Exact field set, plus the optional time_anchor (events published before
    anchors existed have none)."""
    if set(event) - {"time_anchor"} != expected:
        raise ValueError(f"{kind} event contains unsupported fields")
    if "time_anchor" in event:
        _validate_time_anchor(event["time_anchor"])


def create_public_research_records_event(
    ranking: dict, *, confirm_publication: bool = False, time_anchor: dict | None = None
) -> dict:
    """Full bibliographic records from a research_analysis ranking, for the
    node chain. The chain is append-only, so publication needs explicit
    confirmation. Abstracts are never included: their reuse rights are
    unknown, and a chain entry cannot be withdrawn. `time_anchor` (optional)
    records the current Bitcoin block, proving the event is no older."""
    if confirm_publication is not True:
        raise PermissionError("explicit confirmation is required before publishing records to the chain")
    if not isinstance(ranking, dict) or ranking.get("schema") != "research-ranking.v1":
        raise ValueError("input must be a research-ranking.v1 result")
    records = [
        {field: str(entry.get(field) or "")[:limit] for field, limit in _PUBLISHED_RECORD_FIELDS.items()}
        for entry in ranking.get("ranked", [])[:MAX_PUBLISHED_RECORDS]
    ]
    event = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "event_type": "public_research_records",
        "event_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "public",
        "query": str(ranking.get("query") or "")[:200],
        "sources": sorted({record["source"] for record in records}),
        "record_count": len(records),
        "records": records,
        "ranking_sha256": ranking.get("all_records_sha256"),
    }
    if time_anchor is not None:
        event["time_anchor"] = time_anchor
    validate_public_provenance(event)
    return event


def _validate_public_research_records(event: dict) -> None:
    expected = {
        "schema_version", "event_type", "event_id", "created_at", "classification",
        "query", "sources", "record_count", "records", "ranking_sha256",
    }
    _check_fields(event, expected, "research records")
    if event["schema_version"] != PROVENANCE_SCHEMA_VERSION:
        raise ValueError("unsupported research records event schema version")
    if event["classification"] != "public":
        raise ValueError("only public research records may be queued")
    if not isinstance(event["event_id"], str) or not _EVENT_RE.fullmatch(event["event_id"]):
        raise ValueError("research records event has an invalid event ID")
    try:
        timestamp = datetime.fromisoformat(event["created_at"])
    except (TypeError, ValueError) as error:
        raise ValueError("research records event has an invalid timestamp") from error
    if timestamp.tzinfo is None:
        raise ValueError("research records event timestamp must include a timezone")
    if not isinstance(event["query"], str) or len(event["query"]) > 200:
        raise ValueError("research records event has an invalid query")
    if not isinstance(event["ranking_sha256"], str) or not _HASH_RE.fullmatch(event["ranking_sha256"]):
        raise ValueError("research records event has an invalid ranking hash")
    records = event["records"]
    if (
        not isinstance(records, list)
        or not 1 <= len(records) <= MAX_PUBLISHED_RECORDS
        or event["record_count"] != len(records)
    ):
        raise ValueError("research records event must hold 1-20 records matching record_count")
    for record in records:
        if not isinstance(record, dict) or set(record) != set(_PUBLISHED_RECORD_FIELDS):
            raise ValueError("published research record has unsupported fields")
        for field, limit in _PUBLISHED_RECORD_FIELDS.items():
            if not isinstance(record[field], str) or len(record[field]) > limit:
                raise ValueError(f"published research record has an invalid {field}")
        if record["source"] not in _PUBLIC_SOURCES:
            raise ValueError("published research record is not from an allowed public source")
        if not record["external_id"] or not record["title"]:
            raise ValueError("published research record requires an ID and title")
        if not _HASH_RE.fullmatch(record["record_sha256"]):
            raise ValueError("published research record has an invalid hash")
    if event["sources"] != sorted({record["source"] for record in records}):
        raise ValueError("research records event sources do not match its records")
    size = len(json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if size > MAX_PUBLISHED_EVENT_BYTES:
        raise ValueError("research records event exceeds the 32-KiB block payload limit")


# ------------------------------------------------------- variant classifications
# What a public variant database reports about a variant, republished with
# attribution. The classification is ClinVar's and its submitters', never this
# project's, and it describes a variant's reported significance, not a
# treatment. Every record carries the URL of the source record so a reader can
# check the claim where it was made.
_VARIANT_DATABASES = {
    "clinvar": {
        "url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/{uid}/",
        "asserted_by": "ClinVar (NCBI) and its submitters, not this project",
    },
}
_VCV_RE = re.compile(r"^VCV[0-9]{9}$")
_UID_RE = re.compile(r"^[0-9]{1,12}$")
# ClinVar's classification wording, checked by shape rather than by a fixed
# list: the vocabulary changes over time, and rejecting a new term would be
# worse than carrying it verbatim beside the source URL that states it.
_SIGNIFICANCE_RE = re.compile(r"^[A-Za-z][A-Za-z ,/()'‐-―-]{0,119}$")
MAX_VARIANT_RECORDS = 20
MAX_VARIANT_CONDITIONS = 6
_VARIANT_RECORD_FIELDS = {
    "uid", "accession", "gene", "title", "variant_type", "significance",
    "review_status", "last_evaluated", "conditions", "source_url", "record_sha256",
}


def variant_record_hash(record: dict) -> str:
    """The hash published with a variant record: its reported content, so a
    reader can confirm the row was not altered after publication."""
    return _canonical_hash({
        key: record[key] for key in sorted(_VARIANT_RECORD_FIELDS - {"record_sha256"})
    })


def create_public_variant_classification_event(
    records: list[dict], *, database: str = "clinvar", confirm_publication: bool = False,
    time_anchor: dict | None = None,
) -> dict:
    """Republish a public variant database's own classifications, attributed.
    Only public metadata is carried: the variant's reported significance, its
    review status, the conditions named and a link to the source record."""
    if confirm_publication is not True:
        raise PermissionError(
            "explicit confirmation is required before publishing variant classifications to the chain"
        )
    if database not in _VARIANT_DATABASES:
        raise ValueError(f"database must be one of {sorted(_VARIANT_DATABASES)}")
    event = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "event_type": "public_variant_classification",
        "event_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "public",
        "database": database,
        "asserted_by": _VARIANT_DATABASES[database]["asserted_by"],
        "record_count": len(records),
        "records": [
            {
                "uid": str(record["uid"]),
                "accession": record["accession"],
                "gene": record["gene"],
                "title": str(record["title"])[:300],
                "variant_type": str(record.get("variant_type") or "")[:80],
                "significance": record["significance"],
                "review_status": str(record.get("review_status") or "")[:120],
                "last_evaluated": str(record.get("last_evaluated") or "")[:32],
                "conditions": sorted(set(record.get("conditions") or []))[:MAX_VARIANT_CONDITIONS],
                "source_url": record["source_url"],
                "record_sha256": variant_record_hash({**record, "uid": str(record["uid"])}),
            }
            for record in records
        ],
    }
    if time_anchor is not None:
        event["time_anchor"] = time_anchor
    validate_public_provenance(event)
    return event


def _validate_public_variant_classification(event: dict) -> None:
    expected = {
        "schema_version", "event_type", "event_id", "created_at", "classification",
        "database", "asserted_by", "record_count", "records",
    }
    _check_fields(event, expected, "variant classification")
    if event["schema_version"] != PROVENANCE_SCHEMA_VERSION or event["classification"] != "public":
        raise ValueError("variant classification event must be a public schema-1 event")
    if not isinstance(event["event_id"], str) or not _EVENT_RE.fullmatch(event["event_id"]):
        raise ValueError("variant classification event has an invalid event ID")
    _require_timestamp(event["created_at"], "variant classification")
    database = event["database"]
    if database not in _VARIANT_DATABASES:
        raise ValueError("variant classification event names an unknown database")
    if event["asserted_by"] != _VARIANT_DATABASES[database]["asserted_by"]:
        raise ValueError("variant classification event must attribute the classification to its database")
    records = event["records"]
    if (
        not isinstance(records, list)
        or not 1 <= len(records) <= MAX_VARIANT_RECORDS
        or event["record_count"] != len(records)
    ):
        raise ValueError(f"variant classification event must hold 1-{MAX_VARIANT_RECORDS} records "
                         "matching record_count")
    seen = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _VARIANT_RECORD_FIELDS:
            raise ValueError("published variant record has unsupported fields")
        if not isinstance(record["uid"], str) or not _UID_RE.fullmatch(record["uid"]):
            raise ValueError("published variant record has an invalid database UID")
        if not isinstance(record["accession"], str) or not _VCV_RE.fullmatch(record["accession"]):
            raise ValueError("published variant record has an invalid accession")
        if not isinstance(record["gene"], str) or not _GENE_RE.fullmatch(record["gene"]):
            raise ValueError("published variant record has an invalid gene symbol")
        if not isinstance(record["title"], str) or not 0 < len(record["title"]) <= 300:
            raise ValueError("published variant record has an invalid title")
        if not isinstance(record["significance"], str) or not _SIGNIFICANCE_RE.fullmatch(
            record["significance"]
        ):
            raise ValueError("published variant record has an invalid reported significance")
        for field, limit in (("variant_type", 80), ("review_status", 120), ("last_evaluated", 32)):
            if not isinstance(record[field], str) or len(record[field]) > limit:
                raise ValueError(f"published variant record has an invalid {field}")
        conditions = record["conditions"]
        if (
            not isinstance(conditions, list)
            or len(conditions) > MAX_VARIANT_CONDITIONS
            or conditions != sorted(set(conditions))
            or any(not isinstance(c, str) or not 0 < len(c) <= 120 for c in conditions)
        ):
            raise ValueError("published variant record has invalid conditions")
        expected_url = _VARIANT_DATABASES[database]["url"].format(uid=record["uid"])
        if record["source_url"] != expected_url:
            raise ValueError("published variant record's source URL does not match its database record")
        if record["record_sha256"] != variant_record_hash(record):
            raise ValueError("published variant record's hash does not match its content")
        if record["accession"] in seen:
            raise ValueError("variant classification event lists an accession twice")
        seen.add(record["accession"])
    size = len(json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if size > MAX_PUBLISHED_EVENT_BYTES:
        raise ValueError("variant classification event exceeds the 32-KiB block payload limit")


# ------------------------------------------------------------------ CRISPR
# Which published records mention CRISPR work, and which genes they name.
# These are keyword tags over a record's own published title: they say what
# the title mentions, never that the research supports an edit or a
# treatment. The method is recorded so a reader knows how a tag was derived.
CRISPR_TAG_METHOD = "title-keywords-v2"
# Older events keep their own method value and must still validate, since the
# chain is append-only and a published event cannot be re-tagged in place.
CRISPR_TAG_METHODS = {"title-keywords-v1", CRISPR_TAG_METHOD}
CRISPR_TAGS = {
    "crispr",           # CRISPR/Cas named at all
    "cas9",             # a specific nuclease
    "base_editing",     # base editors
    "prime_editing",    # prime editors
    "guide_rna",        # guide/sgRNA design or screening
    "knockout",         # gene knockout or silencing
    "screen",           # CRISPR screens
    "delivery",         # delivery vehicles
    "gene_therapy",     # gene therapy named without CRISPR
    # Added in v2. These describe regulation of an existing gene rather than a
    # change to its sequence, which is where hormone and expression research
    # sits: hormones do not alter DNA bases, they change what is transcribed.
    "hormone_signalling",   # oestrogen/androgen receptor signalling, endocrine therapy
    "methylation",          # DNA methylation and other epigenetic marks
    "expression",           # transcription, RNA-seq, up/downregulation
}
_GENE_RE = re.compile(r"^[A-Z][A-Z0-9-]{1,14}$")
MAX_TAGGED_GENES = 8
_CRISPR_RECORD_FIELDS = {"source", "external_id", "record_sha256", "tags", "genes"}


def create_public_crispr_relevance_event(
    records: list[dict], *, confirm_publication: bool = False, time_anchor: dict | None = None
) -> dict:
    """CRISPR keyword tags and gene symbols for already-published records,
    so the chain shows which research is CRISPR-related and about which
    gene. Tags describe the title's wording, not clinical relevance."""
    if confirm_publication is not True:
        raise PermissionError("explicit confirmation is required before publishing CRISPR tags to the chain")
    event = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "event_type": "public_crispr_relevance",
        "event_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "public",
        "method": CRISPR_TAG_METHOD,
        "record_count": len(records),
        "records": [
            {
                "source": record["source"],
                "external_id": record["external_id"],
                "record_sha256": record["record_sha256"],
                "tags": sorted(set(record["tags"])),
                "genes": sorted(set(record.get("genes") or [])),
            }
            for record in records
        ],
    }
    if time_anchor is not None:
        event["time_anchor"] = time_anchor
    validate_public_provenance(event)
    return event


def _validate_public_crispr_relevance(event: dict) -> None:
    expected = {
        "schema_version", "event_type", "event_id", "created_at", "classification",
        "method", "record_count", "records",
    }
    _check_fields(event, expected, "CRISPR relevance")
    if event["schema_version"] != PROVENANCE_SCHEMA_VERSION or event["classification"] != "public":
        raise ValueError("CRISPR relevance event must be a public schema-1 event")
    if not isinstance(event["event_id"], str) or not _EVENT_RE.fullmatch(event["event_id"]):
        raise ValueError("CRISPR relevance event has an invalid event ID")
    _require_timestamp(event["created_at"], "CRISPR relevance")
    if event["method"] not in CRISPR_TAG_METHODS:
        raise ValueError("CRISPR relevance event has an unknown tagging method")
    records = event["records"]
    if (
        not isinstance(records, list)
        or not 1 <= len(records) <= MAX_PUBLISHED_RECORDS
        or event["record_count"] != len(records)
    ):
        raise ValueError("CRISPR relevance event must hold 1-20 records matching record_count")
    keys = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _CRISPR_RECORD_FIELDS:
            raise ValueError("tagged record has unsupported fields")
        for field in ("source", "external_id"):
            if not isinstance(record[field], str) or not 0 < len(record[field]) <= _PUBLISHED_RECORD_FIELDS[field]:
                raise ValueError(f"tagged record has an invalid {field}")
        if record["source"] not in _PUBLIC_SOURCES:
            raise ValueError("tagged record is not from an allowed public source")
        if not isinstance(record["record_sha256"], str) or not _HASH_RE.fullmatch(record["record_sha256"]):
            raise ValueError("tagged record has an invalid record hash")
        tags, genes = record["tags"], record["genes"]
        if not isinstance(tags, list) or not tags or set(tags) - CRISPR_TAGS or tags != sorted(set(tags)):
            raise ValueError("tagged record must list known CRISPR tags, sorted and unique")
        if (
            not isinstance(genes, list)
            or len(genes) > MAX_TAGGED_GENES
            or genes != sorted(set(genes))
            or any(not isinstance(gene, str) or not _GENE_RE.fullmatch(gene) for gene in genes)
        ):
            raise ValueError("tagged record has invalid gene symbols")
        keys.add((record["source"], record["external_id"]))
    if len(keys) != len(records):
        raise ValueError("CRISPR relevance event lists a record twice")


# --------------------------------------------------------------- model runs
# A remission_core.py run's provenance: which published records it was linked
# to, and what the computational model reported. Sequences, mutation
# positions and base changes are genomic data and never appear here; only
# the run's hash and counts do.
MODEL_RUN_SCHEMA = "remission-model.v1"
# Exactly the values remission_core.py reports; it is the source of truth.
MODELED_STATUSES = {"MODELED_REFERENCE_MATCH", "MODELED_DIFFERENCE_REVIEW"}
LONGITUDINAL_TRENDS = {
    "NO_FOLLOW_UP_DATA", "ORIGINAL_MUTATION_DETECTED",
    "FOLLOW_UP_MATCHES_REFERENCE", "FOLLOW_UP_DIFFERS_REVIEW",
}
CLINICAL_STATUSES = {"NOT_CLINICALLY_CONFIRMED", "CLINICALLY_CONFIRMED_REMISSION"}
GUIDE_DESIGN_METHOD = "spcas9-pam-scan-gc-heuristic-v1"
MODEL_RUN_DISCLAIMER = (
    "Computational model only. Not a biological CRISPR intervention, not guide-RNA validation, "
    "and not a treatment recommendation. A modeled reference match is not clinical remission."
)
_MODEL_RUN_RECORD_FIELDS = {"source", "external_id", "record_sha256"}
_GUIDE_FIELDS = {"method", "sequence_sha256", "candidate_count", "top_score"}

# Where a sequence came from, which decides whether it may be published.
# public_reference: already public in a named database, under an accession
#   (e.g. NCBI RefSeq BRCA1 NM_007294.4). Publishing it discloses nothing new.
# synthetic: made up for a demo or test; describes no person.
# Anything from or derived from a person's sample is neither. A genome
# identifies its owner and their relatives for life, the chain is
# append-only and replicated to every node, and consent cannot be withdrawn
# from it, so this module has no origin value that permits publishing one.
SEQUENCE_ORIGINS = {"public_reference", "synthetic"}
MAX_PUBLISHED_SEQUENCE_BASES = 2000
_BASES_RE = re.compile(r"^[ACGT]+$")
_SEQUENCE_FIELDS = {"origin", "accession", "source", "label", "bases", "base_count", "sequence_sha256"}


def create_public_sequence_event(
    *,
    origin: str,
    bases: str,
    label: str,
    accession: str | None = None,
    source: str | None = None,
    confirm_publication: bool = False,
    time_anchor: dict | None = None,
) -> dict:
    """Publish a DNA sequence itself on the chain. Only a public reference
    sequence (named accession in a public database) or a synthetic one may be
    published; a sequence from a person's sample must not be, and is
    refused. See SEQUENCE_ORIGINS."""
    if confirm_publication is not True:
        raise PermissionError("explicit confirmation is required before publishing a sequence to the chain")
    if origin not in SEQUENCE_ORIGINS:
        raise PermissionError(
            "only public_reference or synthetic sequences may be published; a sequence from a person's "
            "sample cannot be put on an append-only public chain"
        )
    sequence = {
        "origin": origin,
        "accession": accession,
        "source": source,
        "label": label[:200],
        "bases": bases.upper(),
        "base_count": len(bases),
        "sequence_sha256": hashlib.sha256(bases.upper().encode("utf-8")).hexdigest(),
    }
    event = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "event_type": "public_sequence_record",
        "event_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "public",
        "sequence": sequence,
    }
    if time_anchor is not None:
        event["time_anchor"] = time_anchor
    validate_public_provenance(event)
    return event


def _validate_public_sequence_record(event: dict) -> None:
    expected = {"schema_version", "event_type", "event_id", "created_at", "classification", "sequence"}
    _check_fields(event, expected, "sequence record")
    if event["schema_version"] != PROVENANCE_SCHEMA_VERSION or event["classification"] != "public":
        raise ValueError("sequence record event must be a public schema-1 event")
    if not isinstance(event["event_id"], str) or not _EVENT_RE.fullmatch(event["event_id"]):
        raise ValueError("sequence record event has an invalid event ID")
    _require_timestamp(event["created_at"], "sequence record")
    sequence = event["sequence"]
    if not isinstance(sequence, dict) or set(sequence) != _SEQUENCE_FIELDS:
        raise ValueError("published sequence has unsupported fields")
    if sequence["origin"] not in SEQUENCE_ORIGINS:
        raise ValueError(
            "a published sequence must be public_reference or synthetic; a sequence from a person's "
            "sample must not be published"
        )
    bases = sequence["bases"]
    if not isinstance(bases, str) or not _BASES_RE.fullmatch(bases):
        raise ValueError("published sequence must be non-empty ACGT bases")
    if len(bases) > MAX_PUBLISHED_SEQUENCE_BASES:
        raise ValueError(f"published sequence exceeds {MAX_PUBLISHED_SEQUENCE_BASES} bases")
    if sequence["base_count"] != len(bases):
        raise ValueError("published sequence base_count does not match its bases")
    if sequence["sequence_sha256"] != hashlib.sha256(bases.encode("utf-8")).hexdigest():
        raise ValueError("published sequence hash does not match its bases")
    if not isinstance(sequence["label"], str) or not 0 < len(sequence["label"]) <= 200:
        raise ValueError("published sequence has an invalid label")
    if sequence["origin"] == "public_reference":
        if sequence["source"] not in _DATASET_SOURCES:
            raise ValueError("a public reference sequence must name an allowed public database")
        if not isinstance(sequence["accession"], str) or not _ACCESSION_RE.fullmatch(sequence["accession"]):
            raise ValueError("a public reference sequence must carry a valid accession")
    elif sequence["accession"] is not None or sequence["source"] is not None:
        raise ValueError("a synthetic sequence has no accession or public source")


MODEL_STAGE_KINDS = {
    "REFERENCE", "CANCER_SAMPLE", "MUTATION", "CRISPR_EDIT_MODEL", "POST_EDIT",
    "VERIFICATION", "FOLLOW_UP", "ASSESSMENT",
}
MAX_MODEL_STAGES = 60
_STAGE_FIELDS = {"index", "kind", "payload_sha256", "block_hash", "previous_hash"}


def _validate_stage_ledger(stages: object) -> None:
    """remission_core.py's own hash-linked stage ledger, carried onto the node
    chain so the mutation detection, the modeled edit and the verification are
    each provable in order. Stage payloads hold sequences, so only their
    hashes appear here."""
    if not isinstance(stages, list) or not 1 <= len(stages) <= MAX_MODEL_STAGES:
        raise ValueError(f"model run stage ledger must hold 1-{MAX_MODEL_STAGES} stages")
    previous = "0" * 64
    for position, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict) or set(stage) != _STAGE_FIELDS:
            raise ValueError("model run stage has unsupported fields")
        if stage["index"] != position:
            raise ValueError("model run stages must be numbered from 1 in order")
        if stage["kind"] not in MODEL_STAGE_KINDS:
            raise ValueError("model run stage has an unknown kind")
        for field in ("payload_sha256", "block_hash", "previous_hash"):
            if not isinstance(stage[field], str) or not _HASH_RE.fullmatch(stage[field]):
                raise ValueError(f"model run stage has an invalid {field}")
        if stage["previous_hash"] != previous:
            raise ValueError("model run stages are not hash-linked in order")
        previous = stage["block_hash"]
    kinds = [stage["kind"] for stage in stages]
    for required in ("REFERENCE", "CANCER_SAMPLE", "CRISPR_EDIT_MODEL", "POST_EDIT", "VERIFICATION"):
        if required not in kinds:
            raise ValueError(f"model run stage ledger is missing its {required} stage")


def create_public_model_run_event(
    *,
    run_sha256: str,
    modeled_status: str,
    longitudinal_trend: str,
    clinical_status: str,
    mutation_count: int,
    records: list[dict],
    stage_ledger: list[dict],
    sequence_event_ids: list[str] | None = None,
    guide_design: dict | None = None,
    confirm_publication: bool = False,
    time_anchor: dict | None = None,
) -> dict:
    """Provenance for one modeled cancer-to-reference-match run: the run's
    hash, what the model reported, and the published records it was linked
    to. No sequence, position or base change is included."""
    if confirm_publication is not True:
        raise PermissionError("explicit confirmation is required before publishing a model run to the chain")
    event = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "event_type": "public_model_run_record",
        "event_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "public",
        "model_schema": MODEL_RUN_SCHEMA,
        "run_sha256": run_sha256,
        "modeled_status": modeled_status,
        "longitudinal_trend": longitudinal_trend,
        "clinical_status": clinical_status,
        "mutation_count": mutation_count,
        "stage_ledger": [{field: stage[field] for field in sorted(_STAGE_FIELDS)} for stage in stage_ledger],
        "sequence_event_ids": sorted(sequence_event_ids or []),
        "guide_design": dict(guide_design) if guide_design is not None else None,
        "record_count": len(records),
        "records": [{field: record[field] for field in sorted(_MODEL_RUN_RECORD_FIELDS)} for record in records],
        "disclaimer": MODEL_RUN_DISCLAIMER,
    }
    if time_anchor is not None:
        event["time_anchor"] = time_anchor
    validate_public_provenance(event)
    return event


def _validate_public_model_run_record(event: dict) -> None:
    expected = {
        "schema_version", "event_type", "event_id", "created_at", "classification",
        "model_schema", "run_sha256", "modeled_status", "longitudinal_trend", "clinical_status",
        "mutation_count", "stage_ledger", "sequence_event_ids", "guide_design", "record_count",
        "records", "disclaimer",
    }
    _check_fields(event, expected, "model run")
    if event["schema_version"] != PROVENANCE_SCHEMA_VERSION or event["classification"] != "public":
        raise ValueError("model run event must be a public schema-1 event")
    if not isinstance(event["event_id"], str) or not _EVENT_RE.fullmatch(event["event_id"]):
        raise ValueError("model run event has an invalid event ID")
    _require_timestamp(event["created_at"], "model run")
    if event["model_schema"] != MODEL_RUN_SCHEMA:
        raise ValueError("model run event has an unsupported model schema")
    if not isinstance(event["run_sha256"], str) or not _HASH_RE.fullmatch(event["run_sha256"]):
        raise ValueError("model run event has an invalid run hash")
    if event["modeled_status"] not in MODELED_STATUSES:
        raise ValueError("model run event has an unknown modeled status")
    if event["longitudinal_trend"] not in LONGITUDINAL_TRENDS:
        raise ValueError("model run event has an unknown longitudinal trend")
    if event["clinical_status"] not in CLINICAL_STATUSES:
        raise ValueError("model run event has an unknown clinical status")
    if type(event["mutation_count"]) is not int or not 0 <= event["mutation_count"] <= 100_000:
        raise ValueError("model run event has an invalid mutation count")
    if event["disclaimer"] != MODEL_RUN_DISCLAIMER:
        raise ValueError("model run event must carry the model-only disclaimer verbatim")
    _validate_stage_ledger(event["stage_ledger"])
    ids = event["sequence_event_ids"]
    if (
        not isinstance(ids, list)
        or len(ids) > 4
        or ids != sorted(set(ids))
        or any(not isinstance(i, str) or not _EVENT_RE.fullmatch(i) for i in ids)
    ):
        raise ValueError("model run event has invalid sequence event IDs")
    guide = event["guide_design"]
    if guide is not None:
        if not isinstance(guide, dict) or set(guide) != _GUIDE_FIELDS:
            raise ValueError("model run event guide design has unsupported fields")
        if guide["method"] != GUIDE_DESIGN_METHOD:
            raise ValueError("model run event guide design has an unknown method")
        if not isinstance(guide["sequence_sha256"], str) or not _HASH_RE.fullmatch(guide["sequence_sha256"]):
            raise ValueError("model run event guide design has an invalid sequence hash")
        if type(guide["candidate_count"]) is not int or not 0 <= guide["candidate_count"] <= 1000:
            raise ValueError("model run event guide design has an invalid candidate count")
        if type(guide["top_score"]) is not int or not 0 <= guide["top_score"] <= 1000:
            raise ValueError("model run event guide design top score must be an integer in 0-1000")
    records = event["records"]
    if (
        not isinstance(records, list)
        or len(records) > MAX_PUBLISHED_RECORDS
        or event["record_count"] != len(records)
    ):
        raise ValueError("model run event must hold at most 20 records matching record_count")
    keys = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _MODEL_RUN_RECORD_FIELDS:
            raise ValueError("linked model run record has unsupported fields")
        for field in ("source", "external_id"):
            if not isinstance(record[field], str) or not 0 < len(record[field]) <= _PUBLISHED_RECORD_FIELDS[field]:
                raise ValueError(f"linked model run record has an invalid {field}")
        if record["source"] not in _PUBLIC_SOURCES:
            raise ValueError("linked model run record is not from an allowed public source")
        if not isinstance(record["record_sha256"], str) or not _HASH_RE.fullmatch(record["record_sha256"]):
            raise ValueError("linked model run record has an invalid record hash")
        keys.add((record["source"], record["external_id"]))
    if len(keys) != len(records):
        raise ValueError("model run event lists a record twice")


# Why a published record was corrected. The chain is append-only, so a
# correction is a new event naming the event and records it supersedes.
CORRECTION_REASONS = {
    # The kernel's MicroPython ran without Unicode strings, so text above
    # U+00FF was cut to one byte before ranking and hashing.
    "kernel-text-decoding",
}
_CORRECTION_RECORD_FIELDS = {"source", "external_id", "title", "record_sha256", "published_record_sha256"}


def create_public_research_correction_event(
    *,
    corrects_event_id: str,
    reason: str,
    records: list[dict],
    confirm_publication: bool = False,
    time_anchor: dict | None = None,
) -> dict:
    """Corrected titles and record hashes for records of an earlier
    public_research_records event. Each record names the hash it replaces
    (published_record_sha256), so the correction is checkable against the
    original event."""
    if confirm_publication is not True:
        raise PermissionError("explicit confirmation is required before publishing a correction to the chain")
    event = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "event_type": "public_research_correction",
        "event_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "public",
        "corrects_event_id": corrects_event_id,
        "reason": reason,
        "record_count": len(records),
        "records": [{field: record.get(field) for field in sorted(_CORRECTION_RECORD_FIELDS)} for record in records],
    }
    if time_anchor is not None:
        event["time_anchor"] = time_anchor
    validate_public_provenance(event)
    return event


def _validate_public_research_correction(event: dict) -> None:
    expected = {
        "schema_version", "event_type", "event_id", "created_at", "classification",
        "corrects_event_id", "reason", "record_count", "records",
    }
    _check_fields(event, expected, "research correction")
    if event["schema_version"] != PROVENANCE_SCHEMA_VERSION or event["classification"] != "public":
        raise ValueError("research correction event must be a public schema-1 event")
    for field in ("event_id", "corrects_event_id"):
        if not isinstance(event[field], str) or not _EVENT_RE.fullmatch(event[field]):
            raise ValueError(f"research correction event has an invalid {field}")
    if event["corrects_event_id"] == event["event_id"]:
        raise ValueError("a research correction cannot correct itself")
    try:
        timestamp = datetime.fromisoformat(event["created_at"])
    except (TypeError, ValueError) as error:
        raise ValueError("research correction event has an invalid timestamp") from error
    if timestamp.tzinfo is None:
        raise ValueError("research correction event timestamp must include a timezone")
    if event["reason"] not in CORRECTION_REASONS:
        raise ValueError("research correction event has an unknown reason")
    records = event["records"]
    if (
        not isinstance(records, list)
        or not 1 <= len(records) <= MAX_PUBLISHED_RECORDS
        or event["record_count"] != len(records)
    ):
        raise ValueError("research correction event must hold 1-20 records matching record_count")
    keys = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _CORRECTION_RECORD_FIELDS:
            raise ValueError("corrected research record has unsupported fields")
        for field in ("source", "external_id", "title"):
            limit = _PUBLISHED_RECORD_FIELDS[field]
            if not isinstance(record[field], str) or not 0 < len(record[field]) <= limit:
                raise ValueError(f"corrected research record has an invalid {field}")
        if record["source"] not in _PUBLIC_SOURCES:
            raise ValueError("corrected research record is not from an allowed public source")
        for field in ("record_sha256", "published_record_sha256"):
            if not isinstance(record[field], str) or not _HASH_RE.fullmatch(record[field]):
                raise ValueError(f"corrected research record has an invalid {field}")
        if record["record_sha256"] == record["published_record_sha256"]:
            raise ValueError("corrected research record must change its hash")
        keys.add((record["source"], record["external_id"]))
    if len(keys) != len(records):
        raise ValueError("research correction event lists a record twice")
    size = len(json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if size > MAX_PUBLISHED_EVENT_BYTES:
        raise ValueError("research correction event exceeds the 32-KiB block payload limit")


# Public reference-sequence databases a dataset record may point to. Only
# metadata, a hash and the public link are published, never the sequence.
_DATASET_SOURCES = {"ncbi_nuccore": "https://www.ncbi.nlm.nih.gov/nuccore/"}
_ACCESSION_RE = re.compile(r"^[A-Z]{1,2}_?[0-9]{5,9}\.[0-9]{1,3}$")


def create_public_dataset_record_event(
    *,
    dataset_id: str,
    accession: str,
    title: str,
    sequence_count: int,
    total_bases: int,
    dataset_sha256: str,
    source: str = "ncbi_nuccore",
    confirm_publication: bool = False,
    time_anchor: dict | None = None,
) -> dict:
    """Metadata for a public reference dataset (e.g. an NCBI RefSeq FASTA)
    so anyone can pull it from its public source and verify it by hash.
    The sequence itself never goes on the chain."""
    if confirm_publication is not True:
        raise PermissionError("explicit confirmation is required before publishing a dataset record")
    event = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "event_type": "public_dataset_record",
        "event_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "classification": "public",
        "dataset_id": dataset_id,
        "format": "FASTA",
        "source": source,
        "accession": accession,
        "title": title[:200],
        "source_url": _DATASET_SOURCES.get(source, "") + accession,
        "sequence_count": sequence_count,
        "total_bases": total_bases,
        "dataset_sha256": dataset_sha256,
    }
    if time_anchor is not None:
        event["time_anchor"] = time_anchor
    validate_public_provenance(event)
    return event


def _validate_public_dataset_record(event: dict) -> None:
    expected = {
        "schema_version", "event_type", "event_id", "created_at", "classification", "dataset_id",
        "format", "source", "accession", "title", "source_url", "sequence_count", "total_bases",
        "dataset_sha256",
    }
    _check_fields(event, expected, "dataset record")
    if event["schema_version"] != PROVENANCE_SCHEMA_VERSION:
        raise ValueError("unsupported dataset record event schema version")
    if event["classification"] != "public" or event["format"] != "FASTA":
        raise ValueError("only public FASTA dataset records may be queued")
    if not isinstance(event["event_id"], str) or not _EVENT_RE.fullmatch(event["event_id"]):
        raise ValueError("dataset record event has an invalid event ID")
    try:
        timestamp = datetime.fromisoformat(event["created_at"])
        dataset_id = uuid.UUID(event["dataset_id"])
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError("dataset record event has an invalid timestamp or dataset ID") from error
    if timestamp.tzinfo is None:
        raise ValueError("dataset record event timestamp must include a timezone")
    if str(dataset_id) != event["dataset_id"] or dataset_id.version != 4:
        raise ValueError("dataset record event dataset ID must be a canonical random ID")
    if event["source"] not in _DATASET_SOURCES:
        raise ValueError("dataset record event source is not an allowed public database")
    if not isinstance(event["accession"], str) or not _ACCESSION_RE.fullmatch(event["accession"]):
        raise ValueError("dataset record event has an invalid accession")
    if event["source_url"] != _DATASET_SOURCES[event["source"]] + event["accession"]:
        raise ValueError("dataset record event source URL does not match its accession")
    if not isinstance(event["title"], str) or not 0 < len(event["title"]) <= 200:
        raise ValueError("dataset record event has an invalid title")
    for field, limit in (("sequence_count", 100_000), ("total_bases", 10_000_000_000)):
        if type(event[field]) is not int or not 0 < event[field] <= limit:
            raise ValueError(f"dataset record event has an invalid {field}")
    if not isinstance(event["dataset_sha256"], str) or not _HASH_RE.fullmatch(event["dataset_sha256"]):
        raise ValueError("dataset record event has an invalid SHA-256 digest")


def validate_public_provenance(event: dict) -> None:
    if isinstance(event, dict) and event.get("event_type") == "public_research_records":
        _validate_public_research_records(event)
        return
    if isinstance(event, dict) and event.get("event_type") == "public_dataset_record":
        _validate_public_dataset_record(event)
        return
    if isinstance(event, dict) and event.get("event_type") == "public_research_correction":
        _validate_public_research_correction(event)
        return
    if isinstance(event, dict) and event.get("event_type") == "public_crispr_relevance":
        _validate_public_crispr_relevance(event)
        return
    if isinstance(event, dict) and event.get("event_type") == "public_variant_classification":
        _validate_public_variant_classification(event)
        return
    if isinstance(event, dict) and event.get("event_type") == "public_model_run_record":
        _validate_public_model_run_record(event)
        return
    if isinstance(event, dict) and event.get("event_type") == "public_sequence_record":
        _validate_public_sequence_record(event)
        return
    if isinstance(event, dict) and event.get("event_type") == "public_data_hash":
        expected_hash_fields = {
            "schema_version",
            "event_type",
            "event_id",
            "created_at",
            "classification",
            "data_kind",
            "data_sha256",
        }
        if set(event) != expected_hash_fields:
            raise ValueError("data hash event contains unsupported fields")
        if event["schema_version"] != PROVENANCE_SCHEMA_VERSION:
            raise ValueError("unsupported data hash event schema version")
        if event["classification"] != "public":
            raise ValueError("only public data hashes may be queued")
        if event["data_kind"] not in {"dataset", "biological_sequence", "research_file"}:
            raise ValueError("data hash event has an invalid data kind")
        if not isinstance(event["data_sha256"], str) or not _HASH_RE.fullmatch(
            event["data_sha256"]
        ):
            raise ValueError("data hash event has an invalid SHA-256 digest")
        if not isinstance(event["event_id"], str) or not _EVENT_RE.fullmatch(event["event_id"]):
            raise ValueError("data hash event has an invalid event ID")
        try:
            timestamp = datetime.fromisoformat(event["created_at"])
        except (TypeError, ValueError) as error:
            raise ValueError("data hash event has an invalid timestamp") from error
        if timestamp.tzinfo is None:
            raise ValueError("data hash event timestamp must include a timezone")
        return

    expected = {
        "schema_version",
        "event_id",
        "created_at",
        "classification",
        "sources",
        "backend",
        "model",
        "record_count",
        "query_sha256",
        "records_sha256",
        "answer_sha256",
    }
    if not isinstance(event, dict) or set(event) != expected:
        raise ValueError("provenance event contains unsupported fields")
    if event["schema_version"] != PROVENANCE_SCHEMA_VERSION:
        raise ValueError("unsupported provenance schema version")
    if event["classification"] != "public":
        raise ValueError("only public research provenance may be queued")
    if event["backend"] != "ollama-local":
        raise ValueError("only local Ollama provenance may be queued")
    if not isinstance(event["model"], str) or not _MODEL_RE.fullmatch(event["model"]):
        raise ValueError("provenance event has an invalid model identifier")
    if not isinstance(event["event_id"], str) or not _EVENT_RE.fullmatch(event["event_id"]):
        raise ValueError("provenance event has an invalid event ID")
    try:
        timestamp = datetime.fromisoformat(event["created_at"])
    except (TypeError, ValueError) as error:
        raise ValueError("provenance event has an invalid timestamp") from error
    if timestamp.tzinfo is None:
        raise ValueError("provenance timestamp must include a timezone")
    if type(event["record_count"]) is not int or not 0 <= event["record_count"] <= 1000:
        raise ValueError("provenance event has an invalid record count")
    sources = event["sources"]
    if (
        not isinstance(sources, list)
        or not sources
        or any(
            not isinstance(source, str)
            or not _SOURCE_RE.fullmatch(source)
            or source not in _PUBLIC_SOURCES
            for source in sources
        )
        or sources != sorted(set(sources))
    ):
        raise ValueError("provenance event has invalid source names")
    for key in ("query_sha256", "records_sha256", "answer_sha256"):
        if not isinstance(event[key], str) or not _HASH_RE.fullmatch(event[key]):
            raise ValueError(f"provenance event has an invalid {key}")


class ResearchProvenanceQueue:
    """Small file-backed outbox of validated public events: hashes,
    provenance, or confirmed public bibliographic records."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def enqueue(self, event: dict) -> Path:
        validate_public_provenance(event)
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{event['event_id']}.json"
        temporary = self.directory / f".{event['event_id']}.tmp"
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(event, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        return destination

    def peek(self) -> tuple[dict, Path] | None:
        if not self.directory.exists():
            return None
        for path in sorted(self.directory.glob("*.json")):
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"cannot read provenance queue entry {path}: {error}") from error
            validate_public_provenance(event)
            if path.name != f"{event['event_id']}.json":
                raise ValueError(f"provenance queue filename does not match event ID: {path}")
            return event, path
        return None

    def acknowledge(self, path: str | Path, event_id: str) -> None:
        validate_event_id = isinstance(event_id, str) and bool(_EVENT_RE.fullmatch(event_id))
        queue_path = Path(path)
        if (
            not validate_event_id
            or queue_path.parent != self.directory
            or queue_path.name != f"{event_id}.json"
        ):
            raise ValueError("invalid provenance queue acknowledgement")
        queue_path.unlink()

    def reject_invalid(self) -> list[Path]:
        """Move entries that cannot be read or validated into rejected/ so a
        bad entry never blocks the queue. Returns the new locations."""
        moved = []
        if not self.directory.exists():
            return moved
        for path in sorted(self.directory.glob("*.json")):
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
                validate_public_provenance(event)
                if path.name != f"{event['event_id']}.json":
                    raise ValueError("filename does not match event ID")
            except (OSError, ValueError, KeyError, TypeError):
                rejected = self.directory / "rejected"
                rejected.mkdir(exist_ok=True)
                destination = rejected / path.name
                os.replace(path, destination)
                moved.append(destination)
        return moved
