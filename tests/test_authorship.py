"""Authorship is recorded once, at the repository level (NOTICE.md, LICENSE, PRIVACY.md) and per release
(the code manifest and its fingerprint on the chain), not in a header on every file."""
import importlib.util
import json
import subprocess
import time
from pathlib import Path

import pytest

import rabbit
from rabbitsoft import contracts
from tests.test_rabbitsoft import make_os

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("code_fingerprint", ROOT / "scripts" / "code_fingerprint.py")
code_fingerprint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(code_fingerprint)


def test_authorship_lives_at_the_repository_level():
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    assert "Chase Allen Ringquist" in notice and "code manifest" in notice and "applies to every" in notice
    assert "UPL" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    privacy = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")
    assert "encrypted on the device" in privacy and "public and permanent" in privacy
    marker = "SPDX-License-" + "Identifier: UPL-1.0"                           # split so this file doesn't match
    tracked = subprocess.run(["git", "grep", "-l", marker], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    assert tracked == [], f"per-file headers are back in: {tracked}"


def _repo(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@example.org")
    git("config", "user.name", "t")
    git("config", "core.autocrlf", "false")
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / "a.py").write_bytes(b"print('a')\n")
    git("add", ".")
    git("commit", "-q", "-m", "one")
    return git


def test_the_code_manifest_covers_every_file_and_detects_any_change(tmp_path):
    git = _repo(tmp_path)
    first = code_fingerprint.manifest(tmp_path, "HEAD")
    assert first["version"] == "1.2.3" and first["file_count"] == 2 and first["author"] == "Chase Allen Ringquist"
    assert first["files"]["a.py"] == __import__("hashlib").sha256(b"print('a')\n").hexdigest()
    assert code_fingerprint.manifest(tmp_path, "HEAD") == first                 # deterministic
    (tmp_path / "a.py").write_bytes(b"print('a')\r\n")                          # an unstaged edit doesn't count
    assert code_fingerprint.manifest(tmp_path, "HEAD")["fingerprint"] == first["fingerprint"]
    git("commit", "-q", "-am", "two")
    assert code_fingerprint.manifest(tmp_path, "HEAD")["fingerprint"] != first["fingerprint"]
    assert code_fingerprint.manifest(tmp_path, first["commit"])["fingerprint"] == first["fingerprint"]


def test_a_release_fingerprint_goes_on_the_chain_only_after_a_yes(tmp_path, capsys):
    from audit_trail import AuditTrail
    from research_provenance import ResearchProvenanceQueue, validate_public_provenance

    paths = make_os(tmp_path, time.time())
    outbox = ResearchProvenanceQueue(paths.autonomous / "research-outbox")
    assert rabbit.publish_code_fingerprint("HEAD", paths, ask=lambda q: "no") == 0 and outbox.peek() is None
    assert "nothing was published" in capsys.readouterr().out
    assert rabbit.publish_code_fingerprint("HEAD", paths, ask=lambda q: "yes") == 0
    event, _ = outbox.peek()
    validate_public_provenance(event)
    assert not contracts.errors(event, "node-api-v1", "dataHashEvent")
    expected = code_fingerprint.manifest(ROOT, "HEAD")["fingerprint"]
    assert event["data_kind"] == "code_release" and event["data_sha256"] == expected
    entry = [e for e in AuditTrail(str(paths.audit)).read_all() if e["action"] == "code_fingerprint_queued"][-1]
    assert entry["details"]["fingerprint"] == expected
    assert rabbit.publish_code_fingerprint("no-such-tag", paths, ask=lambda q: "yes") == 1


def test_every_release_attaches_its_code_manifest():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "code_fingerprint.py --commit HEAD" in workflow and '"$MANIFEST"' in workflow
    assert "Code fingerprint" in workflow


@pytest.mark.parametrize("name", ["NOTICE.md", "PRIVACY.md", "README.md", "deploy/github/profile/README.md"])
def test_no_phone_number_is_published(name):
    assert "845-0940" not in (ROOT / name).read_text(encoding="utf-8")


def test_the_public_profile_page_names_the_current_version():
    """The page at github.com/DNA-Blockchain is the first thing the public reads, so a release must not
    leave its version behind (it said 0.9.0 two releases on)."""
    page = (ROOT / "deploy" / "github" / "profile" / "README.md").read_text(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert f"| Version | {version} " in page, f"the profile page doesn't name version {version}"
    assert "Therealsickonechase" not in page and "endpoints.huggingface.cloud" not in page
