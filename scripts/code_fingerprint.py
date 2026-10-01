"""The code manifest of a RabbitSoftware release: who authored it, under which license, and the SHA-256 of
every file in the repository at that commit, plus one fingerprint over all of them.

The manifest is attached to each GitHub release (.github/workflows/release.yml), and the owner can record
its fingerprint on the RabbitSoftware chain (`rabbit publish-code-fingerprint vX.Y.Z`). Together they show
that a copy of the code is the one the author released, so authorship needs no header in every file.

Files are hashed as git stores them at the commit, so the result is the same on Windows, Linux and macOS
whatever their line-ending settings.

    python scripts/code_fingerprint.py                       # the current commit (HEAD)
    python scripts/code_fingerprint.py --commit v0.9.0 --out manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTHOR = "Chase Allen Ringquist"
LICENSE = "UPL-1.0"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def file_hashes(root: Path, commit: str) -> dict[str, str]:
    """SHA-256 of every file at the commit, read from git's own objects (one streaming git process)."""
    paths = sorted(p for p in _git(root, "ls-tree", "-r", "--name-only", commit).split("\n") if p)
    process = subprocess.Popen(["git", "cat-file", "--batch"], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    hashes = {}
    for path in paths:
        process.stdin.write(f"{commit}:{path}\n".encode())
        process.stdin.flush()
        header = process.stdout.readline().split()
        size = int(header[2])
        content = process.stdout.read(size)
        process.stdout.read(1)                          # the newline after each object
        hashes[path] = hashlib.sha256(content).hexdigest()
    process.stdin.close()
    process.wait()
    return hashes


def manifest(root: Path = ROOT, commit: str = "HEAD") -> dict:
    full = _git(root, "rev-parse", f"{commit}^{{commit}}").strip()
    try:
        version = _git(root, "show", f"{full}:VERSION").strip()
    except subprocess.CalledProcessError:
        version = "0.0.0"
    files = file_hashes(root, full)
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"schema": "rabbitsoft-code.v1", "project": "RabbitSoftware", "version": version, "commit": full,
            "author": AUTHOR, "license": LICENSE, "file_count": len(files), "fingerprint": fingerprint,
            "files": files}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    p.add_argument("--commit", default="HEAD", help="a tag, branch or commit (default HEAD)")
    p.add_argument("--out", type=Path, help="write the manifest here")
    args = p.parse_args(argv)
    result = manifest(ROOT, args.commit)
    if args.out:
        args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"RabbitSoftware {result['version']} at {result['commit'][:12]}: {result['file_count']} files, "
          f"fingerprint {result['fingerprint']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
