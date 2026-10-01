import hashlib
from pathlib import Path

import pytest

import recovery_index


def test_scan_indexes_explicit_roots_and_finds_duplicate_hashes(tmp_path):
    first = tmp_path / "disk-a"
    second = tmp_path / "disk-b"
    first.mkdir()
    second.mkdir()
    payload = b"recovered research notes\n"
    (first / "research-notes.txt").write_bytes(payload)
    (second / "old-copy.txt").write_bytes(payload)
    index = tmp_path / "catalog.sqlite3"

    result = recovery_index.scan_roots([first, second], index)

    assert result["complete"]
    assert result["indexed"] == 2
    assert recovery_index.search("research-notes", index)[0]["sha256"] == hashlib.sha256(
        payload
    ).hexdigest()
    duplicates = recovery_index.duplicates(index)
    assert duplicates[0]["copies"] == 2
    assert {Path(path).name for path in duplicates[0]["paths"]} == {
        "research-notes.txt",
        "old-copy.txt",
    }


def test_scan_skips_credentials_and_symlinks(tmp_path):
    root = tmp_path / "disk"
    (root / "secrets").mkdir(parents=True)
    (root / ".ssh").mkdir()
    (root / "notes.txt").write_text("keep")
    (root / "secrets" / "token.txt").write_text("private")
    (root / ".ssh" / "config").write_text("private")
    (root / ".env").write_text("PRIVATE=value")
    (root / ".env.staging").write_text("PRIVATE=value")
    (root / "signing.pem").write_text("PRIVATE KEY")
    try:
        (root / "linked.txt").symlink_to(root / "notes.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    index = tmp_path / "catalog.sqlite3"

    result = recovery_index.scan_roots([root], index)

    assert result["complete"]
    assert result["indexed"] == 1
    assert result["skipped_sensitive_or_linked"] == 6


def test_scan_does_not_remove_indexed_records_when_drive_is_offline(tmp_path):
    root = tmp_path / "removable"
    root.mkdir()
    (root / "project.rs").write_text("fn main() {}")
    index = tmp_path / "catalog.sqlite3"
    recovery_index.scan_roots([root], index)
    (root / "project.rs").unlink()

    result = recovery_index.search("project.rs", index)
    assert len(result) == 1
    assert not result[0]["path_exists"]


def test_invalid_roots_and_queries_fail_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        recovery_index.scan_roots([tmp_path / "missing"], tmp_path / "index.sqlite3")
    with pytest.raises(ValueError):
        recovery_index.search(" ")


def test_scan_skips_its_own_database_when_database_is_inside_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.py").write_text("print('work')")
    index = root / "recovery.sqlite3"

    result = recovery_index.scan_roots([root], index)

    assert result["indexed"] == 1
    assert len(recovery_index.search("source.py", index)) == 1
