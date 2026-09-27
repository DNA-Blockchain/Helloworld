"""replace_with_retry: rides out a brief lock (the "Access is denied"
seen from status.json in the first unattended run), still gives up on a
lasting one."""
import os

import pytest

import atomic_io


def test_retries_through_a_brief_lock(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("new")
    dst.write_text("old")
    real_replace, calls = os.replace, []

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(5, "Access is denied")
        real_replace(a, b)

    monkeypatch.setattr(atomic_io.os, "replace", flaky)
    atomic_io.replace_with_retry(str(src), str(dst), first_delay=0.001)
    assert dst.read_text() == "new" and len(calls) == 3


def test_gives_up_on_a_lasting_lock(tmp_path, monkeypatch):
    def locked(a, b):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(atomic_io.os, "replace", locked)
    with pytest.raises(PermissionError):
        atomic_io.replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"), attempts=3, first_delay=0.001)
