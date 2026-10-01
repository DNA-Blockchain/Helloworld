import subprocess
import sys
import time

from rabbitsoft import integrity, toolchain
from rabbitsoft.assistant import Session
from tests.test_rabbitsoft import FakeAI, make_os, wait_for


def rows(here: set[str], wsl: set[str] | None):
    return toolchain.survey(here=here, wsl=wsl)


EVERYTHING = {c for t in toolchain.TOOLS for c in t.commands}


def test_tools_are_found_by_any_of_their_commands():
    survey = rows({"python", "clang"}, {"python3", "gcc"})
    by_key = {r["tool"].key: r for r in survey}
    assert by_key["python"]["here"] and by_key["python"]["wsl"]
    assert by_key["cc"]["here"] and by_key["cc"]["wsl"]                 # clang here, gcc in WSL
    assert not by_key["qemu"]["here"] and by_key["qemu"]["wsl"] is False
    assert all(r["wsl"] is None for r in rows({"git"}, None))            # no WSL: not asked


def test_missing_tools_say_how_to_get_them():
    text = "\n".join(toolchain.describe(rows(EVERYTHING - {"qemu-system-x86_64"}, EVERYTHING - {"jq"}),
                                        windows=True, winget=True))
    assert "QEMU: Windows no, WSL yes (for booting the RabbitSoftware OS image" in text
    assert 'To add QEMU on Windows: say "install qemu".' in text
    assert "To add jq (JSON tool) in WSL, run in Ubuntu: sudo apt install -y jq" in text
    off = "\n".join(toolchain.describe(rows(EVERYTHING - {"cmake"}, None), windows=True, winget=False))
    assert "To add CMake on Windows: winget install -e --id Kitware.CMake." in off
    assert "App execution aliases" in off
    assert toolchain.describe(rows(EVERYTHING, EVERYTHING), windows=True, winget=True)[-1] == "Everything is here."


def test_wsl_is_asked_once_for_every_command(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(toolchain.shutil, "which", lambda name: "wsl.exe" if name == "wsl.exe" else None)
    seen = []

    def run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="python3\ngcc\nqemu-system-x86_64\n")

    assert toolchain.found_in_wsl(run) == {"python3", "gcc", "qemu-system-x86_64"}
    assert len(seen) == 1 and seen[0][:3] == ["wsl.exe", "--exec", "sh"]


def test_names_people_use_find_the_tool():
    assert toolchain.tool_named("C++").key == "cc" and toolchain.tool_named("cargo").key == "rust"
    assert toolchain.tool_named("QEMU").key == "qemu" and toolchain.tool_named("abstracts") is None


def test_the_integrity_report_lists_missing_tools_without_failing(tmp_path):
    check = integrity.tools(make_os(tmp_path, time.time()),
                            survey=lambda: rows(EVERYTHING - {"jq"}, EVERYTHING - {"java"}))
    assert check.status == integrity.OK and check.lines[0] == "9 of 10 tools on this computer, 9 of 10 in WSL."
    assert any(l.startswith("To add jq") for l in check.lines) and any("openjdk" in l for l in check.lines)


def test_a_windows_tool_is_installed_only_after_a_yes(tmp_path, monkeypatch):
    from audit_trail import AuditTrail

    monkeypatch.setattr(sys, "platform", "win32")
    paths = make_os(tmp_path, time.time())
    installed = []
    s = Session(paths, ai=FakeAI(), tool_survey=lambda: rows(EVERYTHING - {"cmake"}, None), winget=True,
                install_command=lambda tool: installed.append(tool.key) or [sys.executable, "-c", "print('ok')"])
    assert "To add CMake on Windows" in s.handle("what tools are missing").text
    assert s.handle("install python").text == "Python 3 is already on this computer."
    ask = s.handle("install cmake")
    assert ask.confirm and "Kitware.CMake" in ask.text and installed == []
    assert s.handle("yes").text.startswith("Started installing CMake.") and installed == ["cmake"]
    assert wait_for(lambda: s.jobs.items[0].finished is not None)
    assert "CMake is installed." in s.handle("what's running").text
    entry = [e for e in AuditTrail(str(paths.audit)).read_all() if e["action"] == "tool_install_started"][-1]
    assert entry["details"]["package"] == "Kitware.CMake"


def test_without_winget_or_on_linux_it_tells_you_the_command(tmp_path, monkeypatch):
    survey = lambda: rows(EVERYTHING - {"jq"}, None)
    monkeypatch.setattr(sys, "platform", "win32")
    off = Session(make_os(tmp_path, time.time()), ai=FakeAI(), tool_survey=survey, winget=False)
    assert "winget install -e --id jqlang.jq" in off.handle("install jq").text
    monkeypatch.setattr(sys, "platform", "linux")
    linux = Session(make_os(tmp_path / "l", time.time()), ai=FakeAI(), tool_survey=survey, winget=False)
    reply = linux.handle("install jq")
    assert "sudo apt install -y jq" in reply.text and not reply.confirm
