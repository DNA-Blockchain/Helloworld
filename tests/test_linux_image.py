"""The Alpine image scripts in linux/. The command-building tests run anywhere;
the boot test runs only on the Linux/WSL side after `sudo python3 linux/build.py`."""
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINUX = os.path.join(ROOT, "linux")
SH = shutil.which("sh")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"nos_linux_{name}", os.path.join(LINUX, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, LINUX)                       # swarm.py imports run.py beside it
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(LINUX)
    return module


run = _load("run")
swarm = _load("swarm")
build = _load("build")


@pytest.mark.parametrize("script", ["build.py", "run.py", "swarm.py", "init"])
def test_scripts_have_lf_endings(script):
    with open(os.path.join(LINUX, script), "rb") as f:
        assert b"\r\n" not in f.read(), f"{script} has CRLF endings and won't run in Linux"


@pytest.mark.skipif(SH is None, reason="needs a POSIX shell")
def test_init_parses():
    subprocess.run([SH, "-n", os.path.join(LINUX, "init")], check=True)


def test_qemu_command_for_a_swarm_node(tmp_path):
    args = run.parser().parse_args(["--id", "2", "--peers", "localhost:9601,127.0.0.1:9603,lab:9700",
                                    "--tofu", "--swarm", "--round", "15", "--duration", "70", "--mem", "384M"])
    cmd = run.qemu_command(args, tmp_path, kvm=True)
    append = cmd[cmd.index("-append") + 1]
    assert append == ("console=ttyS0 quiet nos.id=2 nos.port=9602 nos.duration=70 "
                      "nos.peers=10.0.2.2:9601,10.0.2.2:9603,lab:9700 nos.tofu=1 nos.swarm=1 nos.round=15")
    assert cmd[:5] == ["qemu-system-x86_64", "-machine", "q35,accel=kvm", "-cpu", "host"]
    assert "user,id=n0,hostfwd=tcp::9602-:9602" in cmd
    assert cmd[cmd.index("-m") + 1] == "384M"
    assert f"local,path={tmp_path / 'node-data' / 'node-2'},mount_tag=nosdata,security_model=none,id=d0" in cmd
    assert (tmp_path / "node-data" / "node-2").is_dir()


def test_qemu_command_defaults_without_kvm_or_saved_data(tmp_path):
    cmd = run.qemu_command(run.parser().parse_args(["--ram-only", "--port", "19609"]), tmp_path, kvm=False)
    assert cmd[1:3] == ["-machine", "q35"] and "-cpu" not in cmd
    assert cmd[cmd.index("-append") + 1] == "console=ttyS0 quiet nos.id=1 nos.port=19609 nos.duration=0"
    assert "-virtfs" not in cmd and not (tmp_path / "node-data").exists()


def test_unknown_option_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_:
        run.parser().parse_args(["--bogus"])
    assert exit_.value.code == 2


def test_missing_image_is_reported(tmp_path):
    assert run.missing_image(tmp_path) == f"no {tmp_path / 'vmlinuz'}; run linux/build.py first"


def test_swarm_nodes_are_fully_meshed():
    assert swarm.peers_for(1, 3) == "localhost:9602,localhost:9603"
    assert swarm.peers_for(2, 3) == "localhost:9601,localhost:9603"
    args = swarm.node_args(3, swarm.argparse.Namespace(nodes=3, round=15, duration=70, mem="384M"))
    assert (args.id, args.peers, args.tofu, args.swarm, args.round, args.duration, args.mem) == \
        (3, "localhost:9601,localhost:9602", True, True, 15, 70, "384M")


def test_swarm_summary_keeps_only_verdict_lines(tmp_path):
    log = tmp_path / "node-1.log"
    log.write_text("boot noise\nchain verify: 5 blocks verified, chain intact (OK)\n"
                   "swarm verdicts (last 1 rounds): {'ACCEPTED': 1}\n  round 7: ACCEPTED synthetic:1\n"
                   "mined block #3\nNOS-NODE-EXIT=0\n")
    assert swarm.summary(log) == ["chain verify: 5 blocks verified, chain intact (OK)",
                                  "swarm verdicts (last 1 rounds): {'ACCEPTED': 1}",
                                  "  round 7: ACCEPTED synthetic:1", "NOS-NODE-EXIT=0"]
    assert swarm.summary(tmp_path / "missing.log") == []


def test_image_gets_the_node_and_what_it_imports():
    modules = build.node_modules(Path(ROOT))
    assert "run_node_cli" in modules and "swarm_analysis" in modules
    assert "swarm_explain" not in modules          # runs on the host, not in the VM
    assert all(os.path.exists(os.path.join(ROOT, f"{m}.py")) for m in modules)


def test_published_checksum_is_enforced(tmp_path):
    f = tmp_path / "alpine.tar.gz"
    f.write_bytes(b"alpine")
    build.check_sha256(f, f"{hashlib.sha256(b'alpine').hexdigest()}  alpine.tar.gz")
    with pytest.raises(SystemExit, match="does not match"):
        build.check_sha256(f, f"{hashlib.sha256(b'tampered').hexdigest()}  alpine.tar.gz")


BUILD = run.build_dir()
image_built = all((BUILD / f).exists() for f in ("vmlinuz", "initramfs.gz"))


@pytest.mark.skipif(
    not image_built or shutil.which("qemu-system-x86_64") is None,
    reason="Linux image not built (sudo python3 linux/build.py) or QEMU missing",
)
def test_node_boots_mines_and_verifies_in_the_vm():
    proc = subprocess.run(
        [sys.executable, os.path.join(LINUX, "run.py"), "--id", "9", "--port", "19609",
         "--duration", "4", "--ram-only"],
        capture_output=True, text=True, timeout=240,
    )
    out = proc.stdout + proc.stderr
    assert "REAL NETWORK NODE  id=9  bind=0.0.0.0:19609" in out, out
    assert "mined block #1" in out, out
    assert "chain intact (OK)" in out, out
    assert "NOS-NODE-EXIT=0" in out, out
