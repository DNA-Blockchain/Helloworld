"""
Tests for backup.py — encrypted backups of the project's state. Pins:
what is and isn't collected (keys never), a full backup -> verify ->
restore round trip with byte-for-byte hash checks, a live WAL database
copied consistently, no plaintext left behind, tamper and wrong-passphrase
failures, restore never writing over existing files, pruning, and the
DPAPI passphrase store.
"""
import datetime as dt
import json
import os
import sqlite3
from pathlib import Path

import pytest

import backup

PASS = "correct horse battery staple"


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "autonomous" / "node-0" / "keys").mkdir(parents=True)
    (root / "autonomous" / "archive" / "2026-09-01").mkdir(parents=True)
    (root / "dna_state.json").write_text(json.dumps({"strand_hex": "ab" * 16}))
    (root / "system_audit.jsonl").write_text('{"a": 1}\n')
    (root / "chain_node-0.json").write_text('{"blocks": []}')
    (root / "autonomous" / "node-0" / "status.json").write_text('{"up": true}')
    (root / "autonomous" / "archive" / "2026-09-01" / "chain.json").write_text("[]")
    (root / "autonomous" / "node-0" / "keys" / "node-0.ed25519.pem").write_text("PRIVATE KEY")
    (root / "signing.pem").write_text("PRIVATE KEY")
    (root / "notes.txt").write_text("not project state")
    (root / "research_store.json.tmp").write_text("partial write")
    return root


def _live_db(root: Path, rows: int = 20) -> sqlite3.Connection:
    """A WAL database with uncheckpointed writes, still open -- like a running node."""
    con = sqlite3.connect(root / "live_store.db", isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY, data TEXT)")
    for i in range(rows):
        con.execute("INSERT INTO events (data) VALUES (?)", (f"row-{i}",))
    return con


def test_collect_includes_state_and_never_keys(project):
    got = {p.as_posix() for p in backup.collect(project)}
    assert {"dna_state.json", "system_audit.jsonl", "chain_node-0.json",
            "autonomous/node-0/status.json", "autonomous/archive/2026-09-01/chain.json"} <= got
    assert not any("keys/" in p or p.endswith(".pem") for p in got)
    assert "notes.txt" not in got and "research_store.json.tmp" not in got


def test_round_trip_backup_verify_restore(project, tmp_path):
    con = _live_db(project)
    bs = backup.BackupSet(tmp_path / "backups")
    entry = bs.run(PASS, root=project)
    con.close()
    assert entry["verified"] and entry["file_count"] == 6

    assert bs.verify("latest", PASS)["classification"] == "private"
    out = tmp_path / "restored"
    result = bs.restore("latest", out, PASS)
    assert result["file_count"] == 6
    assert json.loads((out / "dna_state.json").read_text()) == {"strand_hex": "ab" * 16}
    assert (out / "autonomous" / "node-0" / "status.json").exists()
    assert not (out / "autonomous" / "node-0" / "keys").exists()

    restored = sqlite3.connect(out / "live_store.db")   # WAL rows made it in, as one file
    assert restored.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 20
    assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    restored.close()


def test_nothing_readable_left_on_disk(project, tmp_path):
    bs = backup.BackupSet(tmp_path / "backups")
    bs.run(PASS, root=project)
    assert list((tmp_path / "backups" / ".staging").iterdir()) == []   # plaintext zip removed
    everything = b"".join(p.read_bytes() for p in (tmp_path / "backups").rglob("*") if p.is_file())
    for secret in (b"strand_hex", b"dna_state.json", b"status.json"):
        assert secret not in everything   # contents and file names are all inside the ciphertext


def test_wrong_passphrase_and_tampering_fail(project, tmp_path):
    bs = backup.BackupSet(tmp_path / "backups")
    vid = bs.run(PASS, root=project)["vault_id"]
    with pytest.raises(Exception):
        bs.verify(vid, "not the passphrase at all")
    path = tmp_path / "backups" / "vault" / f"{vid}.dvault"
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))
    with pytest.raises(Exception):
        bs.verify(vid, PASS)


def test_restore_never_overwrites(project, tmp_path):
    bs = backup.BackupSet(tmp_path / "backups")
    bs.run(PASS, root=project)
    target = tmp_path / "busy"
    target.mkdir()
    (target / "keep.txt").write_text("mine")
    with pytest.raises(FileExistsError):
        bs.restore("latest", target, PASS)
    assert (target / "keep.txt").read_text() == "mine"


def test_prune_keeps_minimum_and_drops_old(project, tmp_path):
    bs = backup.BackupSet(tmp_path / "backups")
    ids = [bs.run(PASS, root=project)["vault_id"] for _ in range(4)]
    rows = bs.entries()
    old = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc).isoformat()
    for r in rows[:3]:
        r["created_at"] = old
    bs._write_index(rows)
    removed = bs.prune(keep_days=30, keep_min=2)
    assert removed == ids[:2]   # 3 are old, but the newest 2 are always kept
    assert [e["vault_id"] for e in bs.entries()] == ids[2:]
    assert not (tmp_path / "backups" / "vault" / f"{ids[0]}.dvault").exists()


def test_index_has_no_file_names(project, tmp_path):
    bs = backup.BackupSet(tmp_path / "backups")
    bs.run(PASS, root=project)
    text = (tmp_path / "backups" / "index.jsonl").read_text()
    assert "dna_state" not in text and "autonomous" not in text


def test_passphrase_from_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(backup.PASSPHRASE_ENV, "from-the-environment")
    assert backup.load_passphrase(tmp_path / "missing.dpapi") == "from-the-environment"
    monkeypatch.delenv(backup.PASSPHRASE_ENV)
    with pytest.raises(LookupError):
        backup.load_passphrase(tmp_path / "missing.dpapi")


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_dpapi_round_trip(monkeypatch, tmp_path):
    monkeypatch.delenv(backup.PASSPHRASE_ENV, raising=False)
    path = backup.save_passphrase(PASS, tmp_path / "k.dpapi")
    assert PASS.encode() not in path.read_bytes()
    assert backup.load_passphrase(path) == PASS
    with pytest.raises(ValueError):
        backup.save_passphrase("short", tmp_path / "k2.dpapi")
