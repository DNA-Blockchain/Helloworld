"""Explicit, privacy-gated sharing of metadata for local FASTA imports."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from audit_trail import AuditTrail
from dna_shell import _analyze_fasta

if TYPE_CHECKING:
    from network_node import NetworkNode


async def publish_public_fasta_summary(
    node: NetworkNode,
    manifest_path: str | Path,
    *,
    confirm_public_metadata_sharing: bool = False,
    audit_path: str | Path = "dna_shell_data/audit.jsonl",
) -> dict[str, str | int]:
    """Gossip a minimal summary for a verified public FASTA dataset.

    This sends to every peer configured on ``node``. It never sends the
    sequence, FASTA headers, source-file hash, or research-enricher data.
    """
    if confirm_public_metadata_sharing is not True:
        raise PermissionError("explicit confirmation is required before sharing dataset metadata")
    if not node.peers:
        raise ValueError("no peers are configured; dataset metadata was not published")

    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("format") != "FASTA":
        raise ValueError("unsupported FASTA dataset manifest")
    if manifest.get("classification") != "public":
        raise PermissionError("only datasets classified public may be shared")
    if manifest.get("sharing_status") != "local_only":
        raise ValueError("dataset manifest has an unsupported sharing status")

    stored_name = manifest.get("stored_file")
    if not isinstance(stored_name, str) or Path(stored_name).name != stored_name:
        raise ValueError("manifest contains an invalid stored filename")
    dataset_path = manifest_file.parent / stored_name
    report = _analyze_fasta(dataset_path)
    if not report["valid"] or report["sha256"] != manifest.get("sha256"):
        raise ValueError("stored FASTA failed validation or its local integrity check")
    if (
        report["sequence_count"] != manifest.get("sequence_count")
        or report["total_bases"] != manifest.get("total_bases")
    ):
        raise ValueError("stored FASTA metadata does not match its manifest")

    dataset_id = manifest.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError("manifest has no dataset identifier")
    try:
        parsed_dataset_id = uuid.UUID(dataset_id)
        if str(parsed_dataset_id) != dataset_id or parsed_dataset_id.version != 4:
            raise ValueError("dataset identifier is not a canonical random-ID format")
    except ValueError as error:
        raise ValueError("manifest has an invalid dataset identifier") from error
    summary = {
        "dataset_id": dataset_id,
        "format": "FASTA",
        "classification": "public",
        "dataset_sha256": report["sha256"],
    }
    await node.mine_and_gossip(
        extra={"public_dataset_summary": summary},
        run_enrichers=False,
    )

    audit_file = Path(audit_path)
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    AuditTrail(str(audit_file)).log(
        module="dataset_sharing",
        action="public_dataset_summary_broadcast_requested",
        node_id=f"node-{node.node_id}",
        details={
            "dataset_id": dataset_id,
            "configured_peer_count": len(node.peers),
            "record_count": report["sequence_count"],
            "base_count": report["total_bases"],
        },
    )
    return summary
