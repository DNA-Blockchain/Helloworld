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


def create_public_research_records_event(ranking: dict, *, confirm_publication: bool = False) -> dict:
    """Full bibliographic records from a research_analysis ranking, for the
    node chain. The chain is append-only, so publication needs explicit
    confirmation. Abstracts are never included: their reuse rights are
    unknown, and a chain entry cannot be withdrawn."""
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
    validate_public_provenance(event)
    return event


def _validate_public_research_records(event: dict) -> None:
    expected = {
        "schema_version", "event_type", "event_id", "created_at", "classification",
        "query", "sources", "record_count", "records", "ranking_sha256",
    }
    if set(event) != expected:
        raise ValueError("research records event contains unsupported fields")
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


def validate_public_provenance(event: dict) -> None:
    if isinstance(event, dict) and event.get("event_type") == "public_research_records":
        _validate_public_research_records(event)
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
