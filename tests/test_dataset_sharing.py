import asyncio
import hashlib
import json

import pytest

import dna_shell
from audit_trail import AuditTrail
from dataset_sharing import publish_public_fasta_summary


class StubNode:
    node_id = 5
    peers = [("trusted-peer", 9601)]

    def __init__(self):
        self.calls = []

    async def mine_and_gossip(self, extra=None, run_enrichers=True):
        self.calls.append({"extra": extra, "run_enrichers": run_enrichers})


def _import_dataset(tmp_path, classification):
    source = tmp_path / "source.fasta"
    source.write_bytes(b">sensitive-record-name\nACGTNN\n")
    data_dir = tmp_path / "datasets"
    audit = tmp_path / "import-audit.jsonl"
    assert dna_shell.main([
        "import-fasta", str(source), "--classification", classification,
        "--data-dir", str(data_dir), "--audit", str(audit),
    ]) == 0
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return data_dir / f"{digest}.json", source.read_bytes()


def test_public_summary_requires_explicit_confirmation(tmp_path):
    manifest_path, _ = _import_dataset(tmp_path, "public")
    node = StubNode()

    with pytest.raises(PermissionError, match="explicit confirmation"):
        asyncio.run(publish_public_fasta_summary(node, manifest_path))
    assert node.calls == []


def test_public_summary_requires_configured_peers(tmp_path):
    manifest_path, _ = _import_dataset(tmp_path, "public")
    node = StubNode()
    node.peers = []

    with pytest.raises(ValueError, match="no peers are configured"):
        asyncio.run(publish_public_fasta_summary(
            node, manifest_path, confirm_public_metadata_sharing=True
        ))
    assert node.calls == []


@pytest.mark.parametrize("classification", ["private", "restricted"])
def test_private_and_restricted_datasets_never_gossip(tmp_path, classification):
    manifest_path, _ = _import_dataset(tmp_path, classification)
    node = StubNode()

    with pytest.raises(PermissionError, match="only datasets classified public"):
        asyncio.run(publish_public_fasta_summary(
            node, manifest_path, confirm_public_metadata_sharing=True
        ))
    assert node.calls == []


def test_explicit_public_share_gossips_only_minimal_metadata(tmp_path):
    manifest_path, source_bytes = _import_dataset(tmp_path, "public")
    node = StubNode()
    audit_path = tmp_path / "share-audit.jsonl"

    summary = asyncio.run(publish_public_fasta_summary(
        node, manifest_path, confirm_public_metadata_sharing=True, audit_path=audit_path
    ))

    assert summary == {
        "dataset_id": json.loads(manifest_path.read_text(encoding="utf-8"))["dataset_id"],
        "format": "FASTA",
        "classification": "public",
        "dataset_sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    assert node.calls == [{
        "extra": {"public_dataset_summary": summary},
        "run_enrichers": False,
    }]
    serialized = json.dumps(node.calls)
    assert source_bytes.decode() not in serialized
    assert summary["dataset_sha256"] in serialized
    entries = AuditTrail(str(audit_path)).read_all()
    assert entries[0]["action"] == "public_dataset_summary_broadcast_requested"
    assert entries[0]["details"]["dataset_id"] == summary["dataset_id"]
    assert entries[0]["details"]["configured_peer_count"] == 1
    assert hashlib.sha256(source_bytes).hexdigest() not in json.dumps(entries)


def test_public_share_checks_local_file_integrity(tmp_path):
    manifest_path, _ = _import_dataset(tmp_path, "public")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (manifest_path.parent / manifest["stored_file"]).write_text(
        ">tampered\nTTTT\n", encoding="ascii"
    )
    node = StubNode()

    with pytest.raises(ValueError, match="integrity check"):
        asyncio.run(publish_public_fasta_summary(
            node, manifest_path, confirm_public_metadata_sharing=True
        ))
    assert node.calls == []
