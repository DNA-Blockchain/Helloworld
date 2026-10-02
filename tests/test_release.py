import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import rabbit
from rabbitsoft import __version__
from rabbitsoft import update as upd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import release_notes  # noqa: E402


def test_one_version_everywhere():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    assert (ROOT / "VERSION").read_text().strip() == __version__
    result = subprocess.run([sys.executable, str(ROOT / "rabbit.py"), "--version"], capture_output=True, text=True)
    assert result.stdout.strip() == f"RabbitSoftware.inc {__version__}"


def test_the_changelog_has_notes_for_this_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in changelog
    notes = release_notes.section(changelog, __version__)
    assert notes and "## [" not in notes                                 # only this version's section
    # Any Keep a Changelog heading: a patch release has only "Fixed".
    assert re.search(r"^### (Added|Changed|Deprecated|Removed|Fixed|Security)$", notes, re.M)
    assert release_notes.section(changelog, "99.0.0") is None
    assert release_notes.main(["v" + __version__]) == 0 and release_notes.main(["99.0.0"]) == 1


def test_the_release_workflow_checks_the_tag_and_uses_the_changelog():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert 'tags: ["v*.*.*"]' in workflow and "contents: write" in workflow
    assert "doesn't match VERSION" in workflow and "release_notes.py" in workflow and "pytest" in workflow


def test_versions_compare_as_numbers():
    assert upd.parse("v0.10.0") > upd.parse("0.9.9") and upd.parse("1.0.0") == upd.parse("v1.0.0")
    assert upd.parse("garbage") < upd.parse("0.0.1")


def _fetch(tag):
    if tag is None:
        def missing(url):
            raise upd.HTTPError(url, 404, "Not Found", None, None)
        return missing
    return lambda url: json.dumps({"tag_name": tag}).encode()


def test_update_only_when_a_newer_release_exists(tmp_path):
    assert upd.check(tmp_path, "0.9.0", _fetch(None))["action"] == "none"
    assert "the latest release" in upd.check(tmp_path, "0.9.0", _fetch("v0.9.0"))["message"]
    newer = upd.check(tmp_path, "0.9.0", _fetch("v0.10.0"))
    assert newer["action"] == "install" and newer["tag"] == "v0.10.0" and "keeps your chains" in newer["message"]
    (tmp_path / ".git").mkdir()
    assert upd.check(tmp_path, "0.9.0", _fetch("v1.0.0"))["action"] == "git"


def test_rabbit_update_asks_and_reinstalls_into_the_same_folder(tmp_path, capsys):
    ran = []
    assert rabbit.update(tmp_path, ask=lambda q: "no", run=ran.append, fetch=_fetch("v9.0.0")) == 0
    assert ran == [] and "OK, not now." in capsys.readouterr().out
    rabbit.update(tmp_path, ask=lambda q: "yes", run=lambda cmd: ran.append(cmd) or 0, fetch=_fetch("v9.0.0"))
    command = " ".join(ran[0])
    assert "v9.0.0/install." in command and str(tmp_path) in command
    assert "irm" in upd.installer_command(tmp_path, "v9.0.0", "win32")[-1]
    assert "| RABBIT_HOME=" in upd.installer_command(tmp_path, "v9.0.0", "linux")[-1]


@pytest.mark.parametrize("script", ["install.ps1", "install.sh"])
def test_installers_take_the_latest_release_unless_asked_for_dev(script):
    text = (ROOT / script).read_text(encoding="utf-8")
    assert "releases/latest" in text and "archive/refs/tags/" in text
    assert "RABBIT_CHANNEL" in text and "RABBIT_DRY_RUN" in text
    assert "No release is published yet" in text
