#!/usr/bin/env python3
"""Boots the image from build.py in QEMU, with its console in this terminal.

  run.py [--id N] [--port P] [--peers host:port,...] [--tofu]
         [--duration S] [--mem 512M] [--ram-only] [--swarm] [--round S]

The node's port is forwarded from the host, so localhost:P reaches it. Its
data lives in $NOS_LINUX_BUILD/node-data/node-N unless --ram-only is given.
Leave the console with Ctrl-A then X.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def build_dir() -> Path:
    return Path(os.environ.get("NOS_LINUX_BUILD") or Path.home() / ".cache" / "network-os-linux")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--id", type=int, default=1, help="node id (default 1)")
    p.add_argument("--port", type=int, help="node port, forwarded from the host (default 9600+id)")
    p.add_argument("--peers", default="", help="other nodes, host:port,...; localhost means the host")
    p.add_argument("--tofu", action="store_true", help="trust new peers on first contact")
    p.add_argument("--duration", type=int, default=0, help="run S seconds, then power off (0: until stopped)")
    p.add_argument("--mem", default="512M", help="VM memory (default 512M)")
    p.add_argument("--ram-only", action="store_true", help="don't keep node data; new keys every boot")
    p.add_argument("--swarm", action="store_true", help="work sharing with swarm-verified twin analyses")
    p.add_argument("--round", type=int, default=30, help="work-sharing round length with --swarm (default 30)")
    return p


def guest_peers(peers: str) -> str:
    """Peers on the host are reached from inside the VM through 10.0.2.2."""
    return re.sub(r"(localhost|127\.0\.0\.1):", "10.0.2.2:", peers)


def kvm_usable() -> bool:
    return os.access("/dev/kvm", os.R_OK | os.W_OK)


def qemu_command(args: argparse.Namespace, build: Path, kvm: bool) -> list[str]:
    """The qemu-system-x86_64 command line for one node. Creates its data folder unless --ram-only."""
    port = args.port or 9600 + args.id
    append = f"console=ttyS0 quiet nos.id={args.id} nos.port={port} nos.duration={args.duration}"
    if args.peers:
        append += f" nos.peers={guest_peers(args.peers)}"
    if args.tofu:
        append += " nos.tofu=1"
    if args.swarm:
        append += f" nos.swarm=1 nos.round={args.round}"

    accel = ["-machine", "q35,accel=kvm", "-cpu", "host"] if kvm else ["-machine", "q35"]
    cmd = ["qemu-system-x86_64", *accel,
           "-kernel", str(build / "vmlinuz"), "-initrd", str(build / "initramfs.gz"), "-append", append,
           "-m", args.mem, "-smp", "2", "-nographic", "-no-reboot",
           "-netdev", f"user,id=n0,hostfwd=tcp::{port}-:{port}", "-device", "virtio-net-pci,netdev=n0"]
    if not args.ram_only:
        data = build / "node-data" / f"node-{args.id}"
        data.mkdir(parents=True, exist_ok=True)
        cmd += ["-virtfs", f"local,path={data},mount_tag=nosdata,security_model=none,id=d0"]
    return cmd


def missing_image(build: Path) -> str | None:
    for name in ("vmlinuz", "initramfs.gz"):
        if not (build / name).is_file():
            return f"no {build / name}; run linux/build.py first"
    return None


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    build = build_dir()
    problem = missing_image(build)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    kvm = kvm_usable()
    if not kvm:
        print("(no KVM access: using slow emulation)", file=sys.stderr)
    cmd = qemu_command(args, build, kvm)
    sys.stdout.flush()
    os.execvp(cmd[0], cmd)      # QEMU takes over this terminal, as the shell script's exec did


if __name__ == "__main__":
    sys.exit(main())
