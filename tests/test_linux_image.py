"""Boots the Alpine image from linux/build.sh in QEMU and checks a node runs
inside it. Skipped unless the image has been built and QEMU is installed, so
it only runs on the Linux/WSL side after `sudo sh linux/build.sh`."""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINUX = os.path.join(ROOT, "linux")
BUILD = os.environ.get("NOS_LINUX_BUILD", os.path.expanduser("~/.cache/network-os-linux"))
SH = shutil.which("sh")


@pytest.mark.skipif(SH is None, reason="needs a POSIX shell")
@pytest.mark.parametrize("script", ["build.sh", "run.sh", "swarm.sh", "init"])
def test_scripts_parse_and_have_lf_endings(script):
    path = os.path.join(LINUX, script)
    with open(path, "rb") as f:
        assert b"\r\n" not in f.read(), f"{script} has CRLF endings and won't run in Linux"
    subprocess.run([SH, "-n", path], check=True)


image_built = all(os.path.exists(os.path.join(BUILD, f)) for f in ("vmlinuz", "initramfs.gz"))


@pytest.mark.skipif(
    not image_built or shutil.which("qemu-system-x86_64") is None,
    reason="Linux image not built (sudo sh linux/build.sh) or QEMU missing",
)
def test_node_boots_mines_and_verifies_in_the_vm():
    proc = subprocess.run(
        [SH, os.path.join(LINUX, "run.sh"), "--id", "9", "--port", "19609",
         "--duration", "4", "--ram-only"],
        capture_output=True, text=True, timeout=240,
    )
    out = proc.stdout + proc.stderr
    assert "REAL NETWORK NODE  id=9  bind=0.0.0.0:19609" in out, out
    assert "mined block #1" in out, out
    assert "chain intact (OK)" in out, out
    assert "NOS-NODE-EXIT=0" in out, out
