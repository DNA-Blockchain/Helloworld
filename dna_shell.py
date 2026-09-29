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

"""Local-first command shell for DNA-style binary files and audit records."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from audit_trail import AuditTrail
from dna_binary_codec import decode_from_dna, encode_to_dna
from encrypted_data_vault import EncryptedDataVault
from local_ai_retrieval import LocalResearchAssistant
from research_provenance import (
    ResearchProvenanceQueue,
    create_public_data_hash_event,
    create_public_provenance,
)
from research_sessions import DEFAULT_SESSION_STORE, ResearchSessionStore
from research_catalog import (
    DEFAULT_CATALOG,
    ResearchCatalog,
    load_jsonl_records,
    render_cited_context,
    search_public_sources,
)

DEFAULT_AUDIT = Path("dna_shell_data") / "audit.jsonl"
DEFAULT_DATASETS = Path("dna_shell_data") / "datasets"
DEFAULT_ENCRYPTED_VAULT = Path("dna_shell_data") / "encrypted_vault"
CANONICAL_BASES = frozenset("ACGT")
AMBIGUOUS_BASES = frozenset("RYSWKMBDHVN")
VALID_FASTA_SYMBOLS = CANONICAL_BASES | AMBIGUOUS_BASES | frozenset("U-.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Encode/decode files with the A/C/G/T binary format and inspect local audit records."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("encode", "decode"):
        command = commands.add_parser(name, help=f"{name} a file locally")
        command.add_argument("input", type=Path, help="source file")
        command.add_argument("output", type=Path, help="destination file")
        command.add_argument(
            "--force", action="store_true", help="replace the destination if it already exists"
        )
        command.add_argument("--audit", type=Path, default=DEFAULT_AUDIT, help="local JSONL audit path")

    audit = commands.add_parser("audit", help="print local audit records")
    audit.add_argument("--audit", type=Path, default=DEFAULT_AUDIT, help="local JSONL audit path")

    verify = commands.add_parser("verify", help="verify the local audit hash chain")
    verify.add_argument("--audit", type=Path, default=DEFAULT_AUDIT, help="local JSONL audit path")

    for name, description in (
        ("inspect-fasta", "summarize a nucleotide FASTA file without importing it"),
        ("validate-fasta", "validate a nucleotide FASTA file without importing it"),
        ("import-fasta", "validate and copy a FASTA dataset into local storage"),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument("input", type=Path, help="source FASTA file")
        command.add_argument("--audit", type=Path, default=DEFAULT_AUDIT, help="local JSONL audit path")
        if name == "import-fasta":
            command.add_argument(
                "--classification", choices=("private", "restricted", "public"),
                default="private",
                help="data access class; private by default, EDU/Gov access is not assumed public",
            )
            command.add_argument(
                "--data-dir", type=Path, default=DEFAULT_DATASETS,
                help=f"local dataset directory (default: {DEFAULT_DATASETS})",
            )

    vault_store = commands.add_parser(
        "data-vault-store", help="encrypt and store a local research or biological data file"
    )
    vault_store.add_argument("input", type=Path)
    vault_store.add_argument(
        "--classification", choices=("private", "restricted", "public"), default="private"
    )
    vault_store.add_argument("--source-label", default="local")
    vault_store.add_argument("--vault-dir", type=Path, default=DEFAULT_ENCRYPTED_VAULT)

    vault_list = commands.add_parser(
        "data-vault-list", help="list opaque IDs for locally encrypted data files"
    )
    vault_list.add_argument("--vault-dir", type=Path, default=DEFAULT_ENCRYPTED_VAULT)

    vault_inspect = commands.add_parser(
        "data-vault-inspect", help="verify/decrypt metadata and hash for one encrypted data file"
    )
    vault_inspect.add_argument("vault_id")
    vault_inspect.add_argument("--vault-dir", type=Path, default=DEFAULT_ENCRYPTED_VAULT)

    vault_restore = commands.add_parser(
        "data-vault-restore", help="decrypt one locally encrypted file to a new destination"
    )
    vault_restore.add_argument("vault_id")
    vault_restore.add_argument("output", type=Path)
    vault_restore.add_argument("--vault-dir", type=Path, default=DEFAULT_ENCRYPTED_VAULT)

    vault_publish = commands.add_parser(
        "data-vault-publish-hash",
        help="queue a confirmed public dataset hash for explicit peer publication",
    )
    vault_publish.add_argument("vault_id")
    vault_publish.add_argument(
        "--data-kind",
        choices=("dataset", "biological_sequence", "research_file"),
        default="dataset",
    )
    vault_publish.add_argument("--vault-dir", type=Path, default=DEFAULT_ENCRYPTED_VAULT)
    vault_publish.add_argument(
        "--outbox", type=Path,
        default=Path("dna_shell_data") / "research_provenance_outbox",
    )
    vault_publish.add_argument(
        "--confirm-public-hash-publication", action="store_true",
        help="confirm that this public file hash may be shared with connected peers",
    )

    search = commands.add_parser(
        "research-search", help="search public research APIs and save cited records locally"
    )
    search.add_argument("query", help="search terms sent to selected public API providers")
    search.add_argument(
        "--sources", default="pubmed,clinicaltrials.gov,nih_reporter,europe_pmc",
        help="comma-separated source names",
    )
    search.add_argument("--max-results", type=int, default=10)
    search.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    search.add_argument(
        "--confirm-public-query", action="store_true",
        help="confirm that these search terms may be sent to the selected public APIs",
    )

    research_ask = commands.add_parser(
        "research-ask",
        help="search selected public sources, update the local catalog, then ask a local Ollama model",
    )
    research_ask.add_argument("query", help="query disclosed to selected public research APIs")
    research_ask.add_argument(
        "--sources", default="pubmed,clinicaltrials.gov,nih_reporter,europe_pmc",
        help="comma-separated sources; Ensembl expects a gene symbol, gnomAD a variant ID",
    )
    research_ask.add_argument("--max-results", type=int, default=10)
    research_ask.add_argument("--limit", type=int, default=5)
    research_ask.add_argument("--model", required=True, help="locally installed Ollama model name")
    research_ask.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    research_ask.add_argument(
        "--ollama-url", default="http://127.0.0.1:11434",
        help="local Ollama URL; only numeric loopback IPs are accepted",
    )
    research_ask.add_argument(
        "--confirm-public-query", action="store_true",
        help="confirm that the query may be sent to the selected public APIs",
    )
    research_ask.add_argument(
        "--publish-provenance", action="store_true",
        help="queue hashes and public source provenance for explicit peer-network publication",
    )
    research_ask.add_argument(
        "--provenance-outbox", type=Path,
        default=Path("dna_shell_data") / "research_provenance_outbox",
    )
    research_ask.add_argument(
        "--save-session", action="store_true",
        help="save this query, local model answer, and citations in a local-only session history",
    )
    research_ask.add_argument(
        "--session-store", type=Path, default=DEFAULT_SESSION_STORE,
        help="local SQLite history path used with --save-session",
    )

    history = commands.add_parser(
        "research-history", help="list locally saved research session IDs and summaries"
    )
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--session-store", type=Path, default=DEFAULT_SESSION_STORE)

    recall = commands.add_parser(
        "research-recall", help="recall a locally saved research session with its citations"
    )
    recall.add_argument("session_id")
    recall.add_argument("--session-store", type=Path, default=DEFAULT_SESSION_STORE)

    forget = commands.add_parser(
        "research-forget", help="remove a saved research session from the local session database"
    )
    forget.add_argument("session_id")
    forget.add_argument("--session-store", type=Path, default=DEFAULT_SESSION_STORE)

    import_records = commands.add_parser(
        "catalog-import-jsonl", help="import authorized local research records into the catalog"
    )
    import_records.add_argument("input", type=Path, help="JSONL with source, external_id, title, and source_url")
    import_records.add_argument(
        "--classification", choices=("private", "restricted", "public"), default="private",
        help="access class for all imported records (default: private)",
    )
    import_records.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)

    context = commands.add_parser(
        "catalog-context", help="retrieve citation-linked context locally for any AI service"
    )
    context.add_argument("query")
    context.add_argument("--limit", type=int, default=5)
    context.add_argument(
        "--classification", choices=("public", "restricted", "private"), default="public"
    )
    context.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    context.add_argument(
        "--confirm-local-sensitive-context", action="store_true",
        help="confirm restricted/private context is for local display only; no provider call is made",
    )

    ask = commands.add_parser(
        "catalog-ask", help="answer a catalog question with a local Ollama model"
    )
    ask.add_argument("query")
    ask.add_argument("--model", required=True, help="locally installed Ollama model name")
    ask.add_argument("--limit", type=int, default=5)
    ask.add_argument(
        "--classification", choices=("public", "restricted", "private"), default="public"
    )
    ask.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    ask.add_argument(
        "--ollama-url", default="http://127.0.0.1:11434",
        help="local Ollama URL; only numeric loopback IPs are accepted",
    )
    ask.add_argument(
        "--confirm-local-sensitive-context", action="store_true",
        help="confirm restricted/private records may be sent to the configured local model",
    )

    status = commands.add_parser("catalog-status", help="count local catalog records by classification")
    status.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    return parser


def _analyze_fasta(path: Path) -> dict:
    """Stream a FASTA file and return validation/provenance metadata, never sequence data."""
    digest = hashlib.sha256()
    report = {
        "format": "FASTA",
        "valid": True,
        "sequence_count": 0,
        "total_bases": 0,
        "canonical_base_counts": {base: 0 for base in "ACGT"},
        "ambiguous_base_counts": {},
        "rna_u_count": 0,
        "gap_count": 0,
        "invalid_symbol_counts": {},
        "errors": [],
        "input_bytes": 0,
    }
    current_record_bases = 0
    saw_header = False

    def fail(message: str) -> None:
        report["valid"] = False
        if len(report["errors"]) < 20:
            report["errors"].append(message)

    def finish_record(line_number: int) -> None:
        nonlocal current_record_bases
        if saw_header and current_record_bases == 0:
            fail(f"record before line {line_number} contains no sequence")
        current_record_bases = 0

    try:
        with path.open("rb") as fasta:
            for line_number, raw_line in enumerate(fasta, start=1):
                digest.update(raw_line)
                report["input_bytes"] += len(raw_line)
                line = raw_line.rstrip(b"\r\n")

                if line.startswith(b">"):
                    finish_record(line_number)
                    saw_header = True
                    report["sequence_count"] += 1
                    try:
                        header = line[1:].decode("utf-8").strip()
                    except UnicodeDecodeError:
                        fail(f"line {line_number}: FASTA header is not valid UTF-8")
                        header = "invalid"
                    if not header:
                        fail(f"line {line_number}: FASTA header is empty")
                    continue

                try:
                    text = line.decode("ascii")
                except UnicodeDecodeError:
                    fail(f"line {line_number}: sequence line contains non-ASCII data")
                    text = line.decode("ascii", errors="replace")

                symbols = [symbol.upper() for symbol in text if not symbol.isspace()]
                if not symbols:
                    continue
                if not saw_header:
                    fail(f"line {line_number}: sequence data appears before the first FASTA header")
                    continue

                for symbol in symbols:
                    report["total_bases"] += 1
                    current_record_bases += 1
                    if symbol not in VALID_FASTA_SYMBOLS:
                        report["invalid_symbol_counts"][symbol] = (
                            report["invalid_symbol_counts"].get(symbol, 0) + 1
                        )
                        fail(f"line {line_number}: invalid nucleotide symbol {symbol!r}")
                    elif symbol in CANONICAL_BASES:
                        report["canonical_base_counts"][symbol] += 1
                    elif symbol in AMBIGUOUS_BASES:
                        report["ambiguous_base_counts"][symbol] = (
                            report["ambiguous_base_counts"].get(symbol, 0) + 1
                        )
                    elif symbol == "U":
                        report["rna_u_count"] += 1
                    else:
                        report["gap_count"] += 1

        if report["sequence_count"]:
            finish_record(line_number + 1)
        else:
            fail("file contains no FASTA records")
    except UnicodeError as error:
        fail(f"could not read FASTA text: {error}")

    report["sha256"] = digest.hexdigest()
    report["ambiguous_base_count"] = sum(report["ambiguous_base_counts"].values())
    return report


def _print_fasta_report(report: dict) -> None:
    print(
        f"FASTA: {'valid' if report['valid'] else 'INVALID'}; "
        f"records={report['sequence_count']}; bases={report['total_bases']}; "
        f"SHA-256={report['sha256']}"
    )
    print(f"Canonical bases: {report['canonical_base_counts']}")
    print(
        f"Ambiguous bases: {report['ambiguous_base_counts']} "
        f"(total {report['ambiguous_base_count']}); "
        f"RNA U={report['rna_u_count']}; gaps={report['gap_count']}"
    )
    if report["invalid_symbol_counts"]:
        print(f"Invalid symbols: {report['invalid_symbol_counts']}")
    for error in report["errors"]:
        print(f"ERROR: {error}")
    if len(report["errors"]) == 20:
        print("ERROR: additional errors omitted")


def _audit_fasta(args: argparse.Namespace, action: str, report: dict, **extra: str) -> None:
    details = {
        "format": report["format"],
        "input_bytes": report["input_bytes"],
        "sequence_count": report["sequence_count"],
        "total_bases": report["total_bases"],
        "ambiguous_base_count": report["ambiguous_base_count"],
        "rna_u_count": report["rna_u_count"],
        "gap_count": report["gap_count"],
        "invalid_symbol_count": sum(report["invalid_symbol_counts"].values()),
        "valid": report["valid"],
        **extra,
    }
    _audit_at(args.audit).log(
        module="dna_shell",
        action=action,
        node_id="local",
        details=details,
    )


def _import_fasta(args: argparse.Namespace, report: dict) -> int:
    data_dir: Path = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = data_dir / f"{report['sha256']}.fasta"
    manifest_path = data_dir / f"{report['sha256']}.json"
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".fasta-import-", suffix=".tmp", dir=data_dir, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            with args.input.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    temporary.write(chunk)

        copied_report = _analyze_fasta(temporary_path)
        if copied_report["sha256"] != report["sha256"]:
            raise OSError("source changed while it was being imported; no dataset was stored")
        if not copied_report["valid"]:
            _print_fasta_report(copied_report)
            _audit_fasta(args, "dataset_import_rejected", copied_report)
            return 1

        if dataset_path.exists():
            if _analyze_fasta(dataset_path)["sha256"] != report["sha256"]:
                raise OSError(f"existing content-addressed dataset is corrupted: {dataset_path}")
            temporary_path.unlink()
            temporary_path = None
        else:
            try:
                os.rename(temporary_path, dataset_path)
                temporary_path = None
            except FileExistsError:
                if _analyze_fasta(dataset_path)["sha256"] != report["sha256"]:
                    raise OSError(f"existing content-addressed dataset is corrupted: {dataset_path}")

        manifest = {
            "schema_version": 1,
            "dataset_id": str(uuid.uuid4()),
            "format": "FASTA",
            "sha256": report["sha256"],
            "classification": args.classification,
            "sharing_status": "local_only",
            "input_bytes": report["input_bytes"],
            "sequence_count": report["sequence_count"],
            "total_bases": report["total_bases"],
            "canonical_base_counts": report["canonical_base_counts"],
            "ambiguous_base_counts": report["ambiguous_base_counts"],
            "rna_u_count": report["rna_u_count"],
            "gap_count": report["gap_count"],
            "imported_at": time.time(),
            "stored_file": dataset_path.name,
        }
        manifest_temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix=".manifest-", suffix=".tmp",
                dir=data_dir, delete=False,
            ) as temporary_manifest:
                manifest_temp_path = Path(temporary_manifest.name)
                temporary_manifest.write(json.dumps(manifest, indent=2) + "\n")
            os.replace(manifest_temp_path, manifest_path)
        finally:
            if manifest_temp_path is not None:
                manifest_temp_path.unlink(missing_ok=True)
        _audit_fasta(
            args,
            "dataset_imported",
            report,
            dataset_id=manifest["dataset_id"],
            classification=manifest["classification"],
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    print(f"Imported locally to {dataset_path}")
    print(f"Manifest: {manifest_path}")
    print(f"Classification: {manifest['classification']} (network sharing disabled)")
    print("No sequence contents, record names, or source-file hash were added to the audit log.")
    return 0


def _audit_at(path: Path) -> AuditTrail:
    path.parent.mkdir(parents=True, exist_ok=True)
    return AuditTrail(str(path))


def _transform(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    source: Path = args.input
    destination: Path = args.output
    if source.resolve() == destination.resolve():
        parser.error("input and output must be different files")
    if destination.exists() and not args.force:
        parser.error(f"output already exists: {destination} (use --force to replace it)")

    source_bytes = source.read_bytes()
    if args.command == "encode":
        output_bytes = encode_to_dna(source_bytes).encode("ascii")
        action = "file_encoded"
        details = {
            "input_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "input_bytes": len(source_bytes),
            "encoded_bases": len(output_bytes),
            "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
        }
    else:
        sequence = source_bytes.decode("ascii")
        output_bytes = decode_from_dna(sequence)
        action = "file_decoded"
        details = {
            "input_bases": len(sequence),
            "input_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "output_bytes": len(output_bytes),
            "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
        }

    destination.write_bytes(output_bytes)
    _audit_at(args.audit).log(
        module="dna_shell",
        action=action,
        node_id="local",
        details=details,
    )
    print(f"{args.command} complete: {len(source_bytes)} input bytes -> {len(output_bytes)} output bytes")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in ("encode", "decode"):
        return _transform(args, parser)

    if args.command in ("inspect-fasta", "validate-fasta", "import-fasta"):
        report = _analyze_fasta(args.input)
        _print_fasta_report(report)
        if args.command == "inspect-fasta":
            _audit_fasta(args, "dataset_inspected", report)
            return 0
        if args.command == "validate-fasta":
            _audit_fasta(args, "dataset_validated", report)
            return 0 if report["valid"] else 1
        if not report["valid"]:
            _audit_fasta(args, "dataset_import_rejected", report)
            return 1
        return _import_fasta(args, report)

    if args.command == "data-vault-store":
        passphrase = getpass.getpass("Vault passphrase (minimum 12 characters): ")
        confirmation = getpass.getpass("Confirm vault passphrase: ")
        if passphrase != confirmation:
            parser.error("vault passphrases do not match")
        result = EncryptedDataVault(args.vault_dir).store_file(
            args.input,
            passphrase=passphrase,
            classification=args.classification,
            source_label=args.source_label,
        )
        print(json.dumps(result, indent=2))
        print("Encrypted locally; the original source file was not modified.")
        return 0

    if args.command == "data-vault-list":
        ids = EncryptedDataVault(args.vault_dir).list_ids()
        print(json.dumps({
            "storage": "local-encrypted",
            "count": len(ids),
            "vault_ids": ids,
        }, indent=2))
        return 0

    if args.command == "data-vault-inspect":
        passphrase = getpass.getpass("Vault passphrase: ")
        result = EncryptedDataVault(args.vault_dir).inspect(
            args.vault_id, passphrase=passphrase
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "data-vault-restore":
        passphrase = getpass.getpass("Vault passphrase: ")
        result = EncryptedDataVault(args.vault_dir).restore_file(
            args.vault_id, args.output, passphrase=passphrase
        )
        print(json.dumps(result, indent=2))
        print("Restore created a local plaintext file; secure its permissions and storage.")
        return 0

    if args.command == "data-vault-publish-hash":
        if not args.confirm_public_hash_publication:
            parser.error(
                "publishing a dataset hash can enable linkage; pass "
                "--confirm-public-hash-publication only for authorized public data"
            )
        passphrase = getpass.getpass("Vault passphrase: ")
        metadata = EncryptedDataVault(args.vault_dir).inspect(
            args.vault_id, passphrase=passphrase
        )
        if metadata["classification"] != "public":
            parser.error("only files classified public may publish a hash")
        event = create_public_data_hash_event(
            data_sha256=metadata["content_sha256"],
            data_kind=args.data_kind,
            classification=metadata["classification"],
            confirm_hash_publication=True,
        )
        queue_path = ResearchProvenanceQueue(args.outbox).enqueue(event)
        print(json.dumps({
            "queued": True,
            "event_id": event["event_id"],
            "data_kind": event["data_kind"],
            "data_sha256": event["data_sha256"],
            "outbox_path": str(queue_path),
            "on_chain": False,
        }, indent=2))
        return 0

    if args.command == "research-search":
        if not args.confirm_public_query:
            parser.error(
                "public API searches disclose query terms to providers; pass --confirm-public-query"
            )
        sources = [source.strip() for source in args.sources.split(",") if source.strip()]
        records = search_public_sources(
            args.query, sources=sources, max_results=args.max_results
        )
        catalog = ResearchCatalog(args.catalog)
        imported = catalog.add_records(records)
        print(
            f"Received {len(records)} cited records from {len(sources)} source(s); "
            f"saved {imported} record(s) to {args.catalog}"
        )
        if not records:
            print(
                "No records returned. Existing connectors suppress some request errors, "
                "so this can mean no matches or a network/provider failure."
            )
        print("Rights remain unknown unless verified in source terms and record metadata.")
        return 0

    if args.command == "research-ask":
        if not args.confirm_public_query:
            parser.error(
                "public API searches disclose query terms to providers; pass --confirm-public-query"
            )
        sources = [source.strip() for source in args.sources.split(",") if source.strip()]
        fetched = search_public_sources(
            args.query, sources=sources, max_results=args.max_results
        )
        catalog = ResearchCatalog(args.catalog)
        catalog.add_records(fetched)
        assistant = LocalResearchAssistant(catalog, endpoint=args.ollama_url)
        result = assistant.answer(
            args.query, model=args.model, classification="public", limit=args.limit
        )
        if not fetched:
            result["search_notice"] = (
                "No new records were returned. Some existing public connectors "
                "suppress request failures, so this may mean no matches or a provider/network issue."
            )
        provenance = None
        if args.publish_provenance:
            retrieved = catalog.retrieve(args.query, classification="public", limit=args.limit)
            provenance = create_public_provenance(
                args.query, retrieved, sources, result["answer"], model=args.model
            )
            queue_path = ResearchProvenanceQueue(args.provenance_outbox).enqueue(provenance)
        result["records_fetched"] = len(fetched)
        if args.save_session:
            saved_session = ResearchSessionStore(args.session_store).save(
                query=args.query,
                answer=result["answer"],
                model=args.model,
                sources=sources,
                citations=result["citations"],
                records_fetched=len(fetched),
            )
            result["saved_session_id"] = saved_session["session_id"]
            result["session_storage"] = "local-only"
        if provenance is not None:
            result["provenance_queued"] = True
            result["provenance_event_id"] = provenance["event_id"]
            result["provenance_queue_path"] = str(queue_path)
            result["on_chain"] = False
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "catalog-import-jsonl":
        records = load_jsonl_records(args.input, classification=args.classification)
        imported = ResearchCatalog(args.catalog).add_records(records)
        print(f"Imported {imported} local record(s) as {args.classification} into {args.catalog}")
        print("No public API or AI provider was contacted.")
        return 0

    if args.command == "research-history":
        sessions = ResearchSessionStore(args.session_store).list(limit=args.limit)
        print(json.dumps({
            "storage": "local-only",
            "sessions": sessions,
        }, indent=2))
        return 0

    if args.command == "research-recall":
        session = ResearchSessionStore(args.session_store).get(args.session_id)
        print(json.dumps(session, indent=2))
        return 0

    if args.command == "research-forget":
        ResearchSessionStore(args.session_store).forget(args.session_id)
        print(f"Removed research session {args.session_id} from {args.session_store}")
        print("This removes the database row but does not securely erase filesystem or backup copies.")
        return 0

    if args.command == "catalog-context":
        if args.classification != "public" and not args.confirm_local_sensitive_context:
            parser.error(
                "private/restricted retrieval requires --confirm-local-sensitive-context"
            )
        catalog = ResearchCatalog(args.catalog)
        records = catalog.retrieve(
            args.query, classification=args.classification, limit=args.limit
        )
        print(json.dumps(render_cited_context(args.query, records), indent=2))
        return 0

    if args.command == "catalog-ask":
        if args.classification != "public" and not args.confirm_local_sensitive_context:
            parser.error(
                "private/restricted retrieval requires --confirm-local-sensitive-context"
            )
        assistant = LocalResearchAssistant(
            ResearchCatalog(args.catalog), endpoint=args.ollama_url
        )
        result = assistant.answer(
            args.query,
            model=args.model,
            classification=args.classification,
            limit=args.limit,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "catalog-status":
        catalog = ResearchCatalog(args.catalog)
        counts = {classification: catalog.count(classification=classification)
                  for classification in ("public", "restricted", "private")}
        print(json.dumps({"total": sum(counts.values()), "by_classification": counts}, indent=2))
        return 0

    audit = AuditTrail(str(args.audit))
    if args.command == "audit":
        for entry in audit.read_all():
            print(json.dumps(entry, sort_keys=True))
        return 0

    valid, bad_entries = audit.verify_chain()
    invalid_label = "entry" if len(bad_entries) == 1 else "entries"
    print(f"audit chain: {'valid' if valid else 'INVALID'} ({len(bad_entries)} invalid {invalid_label})")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
