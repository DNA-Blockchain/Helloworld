#!/usr/bin/env python3
"""Starts N Alpine VMs (default 3) as a fully meshed swarm: every node peers
with every other, shares work, and cross-checks the DNA twin's analyses.

  swarm.py [--nodes N] [--round S] [--duration S] [--mem 384M]

Logs go to $NOS_LINUX_BUILD/logs/node-N.log. Without --duration it runs until
Ctrl-C, then stops every VM.
"""
from __future__ import annotations

import argparse
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run  # noqa: E402  (linux/run.py, beside this file)

LIVE = re.compile(r"swarm round|took over|!!")                              # printed while it runs
SUMMARY = re.compile(r"swarm verdicts|  round |chain verify|NOS-NODE-EXIT")  # printed after --duration


def peers_for(node: int, nodes: int) -> str:
    return ",".join(f"localhost:{9600 + j}" for j in range(1, nodes + 1) if j != node)


def node_args(node: int, args: argparse.Namespace) -> argparse.Namespace:
    return run.parser().parse_args(["--id", str(node), "--peers", peers_for(node, args.nodes), "--tofu",
                                    "--swarm", "--round", str(args.round), "--duration", str(args.duration),
                                    "--mem", args.mem])


def follow(logs: list[Path]) -> None:
    """Print matching lines as they're written to any log, like tail -f | grep, until interrupted."""
    files = [open(log, encoding="utf-8", errors="replace") for log in logs]
    partial = [""] * len(files)
    try:
        while True:
            quiet = True
            for i, f in enumerate(files):
                chunk = f.readline()
                while chunk:
                    quiet = False
                    partial[i] += chunk
                    if partial[i].endswith("\n"):
                        if LIVE.search(partial[i]):
                            print(partial[i], end="", flush=True)
                        partial[i] = ""
                    chunk = f.readline()
            if quiet:
                time.sleep(0.5)
    finally:
        for f in files:
            f.close()


def summary(log: Path) -> list[str]:
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    return [line for line in text.splitlines() if SUMMARY.search(line)]


def _interrupt(*_) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--nodes", type=int, default=3, help="number of VMs (default 3)")
    p.add_argument("--round", type=int, default=20, help="work-sharing round length in seconds (default 20)")
    p.add_argument("--duration", type=int, default=0, help="run S seconds, then print each node's summary")
    p.add_argument("--mem", default="384M", help="memory per VM (default 384M)")
    args = p.parse_args(argv)

    build = run.build_dir()
    problem = run.missing_image(build)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    kvm = run.kvm_usable()
    (build / "logs").mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, _interrupt)      # kill stops the VMs too, like Ctrl-C

    vms: list[subprocess.Popen] = []
    logs: list[Path] = []
    try:
        for i in range(1, args.nodes + 1):
            log = build / "logs" / f"node-{i}.log"
            with open(log, "w", encoding="utf-8") as out:
                if not kvm:
                    out.write("(no KVM access: using slow emulation)\n")
                    out.flush()
                vms.append(subprocess.Popen(run.qemu_command(node_args(i, args), build, kvm),
                                            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT))
            logs.append(log)
            print(f"node {i}: port {9600 + i}, log {log}", flush=True)

        if args.duration == 0:
            print("swarm running; Ctrl-C stops every VM. Verdicts as they happen:", flush=True)
            follow(logs)
        for vm in vms:
            vm.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        for vm in vms:
            if vm.poll() is None:
                vm.terminate()
        for vm in vms:
            try:
                vm.wait(timeout=10)
            except subprocess.TimeoutExpired:
                vm.kill()

    for i, log in enumerate(logs, start=1):
        print(f"== node {i}")
        for line in summary(log):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
