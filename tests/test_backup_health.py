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
Tests for backup_health — alerts and test restores. Pins: a healthy set
raises nothing, each failure mode raises its alert, the weekly test
restore really restores and checks (and fails on a tampered backup),
the off-site copy is test-restored from S3 when configured, and the
supervisor's daily report picks the alerts up.
"""
import datetime as dt
import json
import sqlite3

import pytest

import backup
import backup_health
from offsite_s3 import S3Offsite
from test_offsite_s3 import CONFIG, FakeS3

PASS = "correct horse battery staple"
HOUR = 3600


@pytest.fixture
def healthy(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "dna_state.json").write_text(json.dumps({"strand_hex": "ab" * 16}))
    (root / "system_audit.jsonl").write_text('{"a": 1}\n')
    con = sqlite3.connect(root / "live_store.db")
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    monkeypatch.setenv(backup.PASSPHRASE_ENV, PASS)
    bs = backup.BackupSet(tmp_path / "backups")
    bs.run(PASS, root=root)
    assert backup_health.test_restore(bs, PASS)["ok"]
    return bs


def _check(bs, **kw):
    return backup_health.check(bs.dest, check_task=False, **kw)


def test_healthy_set_has_no_alerts(healthy):
    assert _check(healthy) == []


def test_test_restore_really_checks_everything(healthy):
    result = backup_health.test_restore_history(healthy.dest)[-1]
    assert result["ok"] and result["files"] == 3
    assert result["sqlite_ok"] == 1 and result["json_ok"] == 2
    assert result["offsite"] == {"ok": True, "skipped": "off-site not configured"}
    assert [p.name for p in healthy.dest.iterdir() if p.name.startswith("restore-test-")] == []   # cleaned up


def test_tampered_backup_fails_test_restore_and_alerts(healthy):
    vid = healthy.entries()[-1]["vault_id"]
    path = healthy.vault.directory / f"{vid}.dvault"
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))
    result = backup_health.test_restore(healthy, PASS)
    assert not result["ok"] and "InvalidTag" in result["error"]
    assert any("last test restore FAILED" in a for a in _check(healthy))


def test_no_backups_alerts(tmp_path, monkeypatch):
    monkeypatch.setenv(backup.PASSPHRASE_ENV, PASS)
    assert any("no backups found" in a for a in backup_health.check(tmp_path / "empty", check_task=False))


def test_old_backup_alerts(healthy):
    later = dt.datetime.now().timestamp() + 40 * HOUR
    assert any("newest backup is" in a for a in _check(healthy, now=later))


def test_stale_test_restore_alerts_and_is_due(healthy):
    later = dt.datetime.now().timestamp() + 9 * 24 * HOUR
    alerts = _check(healthy, now=later, max_age_hours=24 * 30)
    assert alerts == ["no successful test restore in the last 8 days"]
    assert backup_health.test_restore_due(healthy.dest, now=later)
    assert not backup_health.test_restore_due(healthy.dest)


def test_missing_passphrase_alerts(healthy, monkeypatch):
    monkeypatch.delenv(backup.PASSPHRASE_ENV)
    assert any("passphrase unavailable" in a for a in _check(healthy))


def test_offsite_pending_and_failed_sync_alert(healthy, monkeypatch):
    s3 = FakeS3()
    S3Offsite.save_config(healthy.dest, **CONFIG)
    monkeypatch.setattr("offsite_s3.cli_runner", s3)
    later = dt.datetime.now().timestamp() + 40 * HOUR
    assert any("not yet confirmed in S3" in a for a in _check(healthy, now=later, max_age_hours=36))

    s3.offline = True
    backup.offsite_sync(healthy.dest)
    assert any("last off-site sync had errors" in a for a in _check(healthy))
    s3.offline = False
    backup.offsite_sync(healthy.dest)
    assert not any("S3" in a or "off-site" in a for a in _check(healthy))


def test_test_restore_includes_offsite_copy(healthy, monkeypatch):
    s3 = FakeS3()
    S3Offsite.save_config(healthy.dest, **CONFIG)
    monkeypatch.setattr("offsite_s3.cli_runner", s3)
    backup.offsite_sync(healthy.dest)
    result = backup_health.test_restore(healthy, PASS)
    assert result["ok"] and result["offsite"]["ok"]
    assert result["offsite"]["vault_id"] == healthy.entries()[-1]["vault_id"]

    key = next(k for k in s3.objects if k.endswith(".dvault"))
    s3.objects[key] = s3.objects[key][:-10]   # the S3 copy got damaged
    result = backup_health.test_restore(healthy, PASS)
    assert not result["ok"] and not result["offsite"]["ok"]


def test_run_scheduled_notifies_only_on_alerts(healthy, monkeypatch):
    sent = []
    monkeypatch.setattr("node_supervisor.notify", lambda title, body: sent.append(body))
    out = backup_health.run_scheduled(healthy.dest, PASS)
    assert out["alerts"] == [] and out["test_restore"] is None and sent == []   # restore not due yet

    monkeypatch.delenv(backup.PASSPHRASE_ENV)
    backup_health.run_scheduled(healthy.dest, PASS)
    assert len(sent) == 1 and "passphrase" in sent[0]


def test_supervisor_daily_report_includes_backup_alerts(healthy, monkeypatch):
    import node_supervisor
    monkeypatch.setattr(backup, "DEFAULT_DEST", healthy.dest)
    sup = node_supervisor.Supervisor.__new__(node_supervisor.Supervisor)
    assert sup.backup_alerts() == [] or all("task" in a for a in sup.backup_alerts())
    monkeypatch.delenv(backup.PASSPHRASE_ENV)
    assert any("passphrase unavailable" in a for a in sup.backup_alerts())


def test_supervisor_silent_before_backups_exist():
    import node_supervisor
    sup = node_supervisor.Supervisor.__new__(node_supervisor.Supervisor)
    assert sup.backup_alerts() == []   # conftest points DEFAULT_DEST at a folder that doesn't exist


def test_cli_check_exit_codes(healthy, capsys, monkeypatch):
    monkeypatch.setattr(backup_health, "_scheduled_task_problem", lambda: None)
    assert backup_health.main(["--dest", str(healthy.dest), "check"]) == 0
    assert "No alerts" in capsys.readouterr().out
    monkeypatch.delenv(backup.PASSPHRASE_ENV)
    assert backup_health.main(["--dest", str(healthy.dest), "check"]) == 1
    assert "[ALERT]" in capsys.readouterr().out
