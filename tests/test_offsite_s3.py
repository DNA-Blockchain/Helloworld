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
Tests for offsite_s3 — copying encrypted backups to S3. A fake `aws s3api`
runner mimics S3's behaviour (checksum validation on upload, If-None-Match,
404s), so these run without an AWS account. Pins: only confirmed uploads
count, failures stay pending and retry, existing objects are never
replaced, a corrupted upload is caught, the index carries no file names,
and pull restores missing backups with checksum checks.
"""
import base64
import hashlib
import json
from pathlib import Path

import pytest

import backup
from offsite_s3 import AwsError, S3Offsite, sha256_b64

PASS = "correct horse battery staple"
CONFIG = {"bucket": "test-bucket", "region": "us-east-2", "profile": "nob", "prefix": "network-os/"}


class FakeS3:
    """Just enough of `aws s3api` for put/head/get/list."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.calls: list[list[str]] = []
        self.offline = False
        self.corrupt_next_store = False

    @staticmethod
    def _opt(args, name):
        return args[args.index(name) + 1] if name in args else None

    def __call__(self, args):
        self.calls.append(args)
        if self.offline:
            raise AwsError("Could not connect to the endpoint URL", "EndpointConnectionError")
        op, key = args[1], self._opt(args, "--key")
        if op == "put-object":
            body = Path(self._opt(args, "--body")).read_bytes()
            sent = self._opt(args, "--checksum-sha256")
            if sent != base64.b64encode(hashlib.sha256(body).digest()).decode():
                raise AwsError("BadDigest", "BadDigest")
            if self._opt(args, "--if-none-match") == "*" and key in self.objects:
                raise AwsError("An error occurred (PreconditionFailed)", "PreconditionFailed")
            self.objects[key] = body + (b"!" if self.corrupt_next_store else b"")
            self.corrupt_next_store = False
            return {"ETag": '"x"'}
        if op == "head-object":
            if key not in self.objects:
                raise AwsError("An error occurred (404) when calling the HeadObject operation: Not Found", "404")
            return {"ChecksumSHA256": base64.b64encode(hashlib.sha256(self.objects[key]).digest()).decode()}
        if op == "get-object":
            Path(args[-1]).write_bytes(self.objects[key])
            return {"ChecksumSHA256": base64.b64encode(hashlib.sha256(self.objects[key]).digest()).decode()}
        if op == "list-objects-v2":
            prefix = self._opt(args, "--prefix")
            return {"Contents": [{"Key": k} for k in sorted(self.objects) if k.startswith(prefix)]}
        raise AssertionError(f"unexpected call {args}")


@pytest.fixture
def backups(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "dna_state.json").write_text(json.dumps({"strand_hex": "ab" * 16}))
    bs = backup.BackupSet(tmp_path / "backups")
    ids = [bs.run(PASS, root=root)["vault_id"] for _ in range(2)]
    return bs, ids


def test_sync_uploads_verifies_and_records(backups):
    bs, ids = backups
    s3 = FakeS3()
    off = S3Offsite(bs.dest, CONFIG, runner=s3)
    report = off.sync()
    assert sorted(report["uploaded"]) == sorted(ids) and report["failed"] == {}
    assert report["index_uploaded"] is True and report["still_pending"] == 0
    assert set(s3.objects) == {f"network-os/vault/{i}.dvault" for i in ids} | {"network-os/index.jsonl"}
    assert all("--profile" in c and "nob" in c for c in s3.calls)
    assert off.sync()["uploaded"] == []   # nothing re-sent next time


def test_offline_stays_pending_and_retries(backups):
    bs, ids = backups
    s3 = FakeS3()
    s3.offline = True
    off = S3Offsite(bs.dest, CONFIG, runner=s3)
    report = off.sync()
    assert report["uploaded"] == [] and set(report["failed"]) == set(ids)
    assert report["index_uploaded"] is None and report["still_pending"] == 2
    s3.offline = False
    assert sorted(off.sync()["uploaded"]) == sorted(ids)


def test_existing_backup_is_never_replaced(backups):
    bs, ids = backups
    s3 = FakeS3()
    off = S3Offsite(bs.dest, CONFIG, runner=s3)
    key = f"network-os/vault/{ids[0]}.dvault"
    s3.objects[key] = (bs.vault.directory / f"{ids[0]}.dvault").read_bytes()   # already there from a lost ledger
    assert ids[0] in off.sync()["uploaded"]   # confirmed by checksum, not overwritten
    s3.objects[key] = b"something else entirely"
    (bs.dest / "offsite_s3.jsonl").unlink()
    report = off.sync()
    assert ids[0] in report["failed"] and "checksum mismatch" in report["failed"][ids[0]]
    assert s3.objects[key] == b"something else entirely"   # we reported it, we didn't clobber it


def test_corruption_after_upload_is_caught(backups):
    bs, ids = backups
    s3 = FakeS3()
    s3.corrupt_next_store = True
    off = S3Offsite(bs.dest, CONFIG, runner=s3)
    report = off.sync()
    assert len(report["failed"]) == 1 and len(report["uploaded"]) == 1
    assert report["index_uploaded"] is None   # index waits until every backup is confirmed


def test_uploaded_index_has_no_file_names(backups):
    bs, _ = backups
    s3 = FakeS3()
    S3Offsite(bs.dest, CONFIG, runner=s3).sync()
    everything = b"".join(s3.objects.values())
    assert b"dna_state" not in everything and b"strand_hex" not in everything


def test_pull_restores_missing_backups(backups, tmp_path):
    bs, ids = backups
    s3 = FakeS3()
    S3Offsite(bs.dest, CONFIG, runner=s3).sync()

    fresh = backup.BackupSet(tmp_path / "new-pc")   # a replacement machine with nothing local
    off = S3Offsite(fresh.dest, CONFIG, runner=s3)
    assert sorted(off.pull("all-missing")) == sorted(ids)
    for vid in ids:
        assert fresh.vault.inspect(vid, passphrase=PASS)["classification"] == "private"
    assert off.pull("all-missing") == []


def test_config_round_trip_and_required(tmp_path):
    with pytest.raises(LookupError):
        S3Offsite(tmp_path)
    S3Offsite.save_config(tmp_path, "b", "us-east-2", None, "/x/")
    cfg = S3Offsite.load_config(tmp_path)
    assert cfg == {"bucket": "b", "region": "us-east-2", "profile": None, "prefix": "x/"}


def test_backup_run_syncs_when_configured(backups, monkeypatch):
    bs, ids = backups
    s3 = FakeS3()
    S3Offsite.save_config(bs.dest, **{k: CONFIG[k] for k in ("bucket", "region", "profile", "prefix")})
    monkeypatch.setattr("offsite_s3.cli_runner", s3)
    report = backup.offsite_sync(bs.dest)
    assert sorted(report["uploaded"]) == sorted(ids)


def test_backup_run_skips_offsite_when_unconfigured(backups):
    bs, _ = backups
    assert backup.offsite_sync(bs.dest) is None
