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
