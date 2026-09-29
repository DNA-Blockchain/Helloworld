#!/usr/bin/env python3
"""
build_remission_bundle.py
=========================
Packages remission_core.py as a Network OS MicroPython task bundle in
os/tasks/remission/, following os/schemas/task-bundle-v1 and workflow-v1:

    REMISSION.PY   byte-for-byte copy of remission_core.py (LF endings)
    SAMPLE.JSON    synthetic demo input (the kernel passes no argv)
    RMTASK.JSON    task manifest with each file's size and SHA-256
    RMFLOW.JSON    one-block workflow referencing RMTASK.JSON

The kernel can already validate and plan these manifests; it cannot run
MicroPython yet (see os/README.md). Keeping the bundle generated from the
host module means there is one source of truth either way.

Usage:
    python build_remission_bundle.py          # (re)write the bundle
    python build_remission_bundle.py --check  # exit 1 if it is stale
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE_DIR = ROOT / "os" / "tasks" / "remission"
TASK_ID = "remission-model"


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _file_entry(name: str, role: str, data: bytes) -> dict:
    return {"name": name, "role": role, "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build() -> dict[str, bytes]:
    from remission_workflow import DEMO_REQUEST

    entry = _lf((ROOT / "remission_core.py").read_bytes())
    sample = (json.dumps(DEMO_REQUEST, indent=2) + "\n").encode("ascii")
    task = {
        "schemaVersion": "nosfs.task-bundle.v1",
        "taskId": TASK_ID,
        "runtime": "micropython",
        "entrypoint": "REMISSION.PY",
        "files": [
            _file_entry("REMISSION.PY", "python", entry),
            _file_entry("SAMPLE.JSON", "json", sample),
        ],
        "capabilities": {"network": {"dns": False, "udpDestinations": [], "tcpDestinations": [], "tlsHosts": []}},
        "limits": {"memoryBytes": 1048576, "runtimeSeconds": 30},
    }
    workflow = {
        "schemaVersion": "nosfs.workflow.v1",
        "workflowId": "remission-model",
        "failurePolicy": "stop",
        "blocks": [{
            "blockId": "remission-model",
            "taskManifest": "RMTASK.JSON",
            "dependsOn": [],
            "inputFiles": ["SAMPLE.JSON"],
            "outputFiles": ["RESULT.OUT"],
        }],
    }
    return {
        "REMISSION.PY": entry,
        "SAMPLE.JSON": sample,
        "RMTASK.JSON": (json.dumps(task, separators=(",", ":")) + "\n").encode("ascii"),
        "RMFLOW.JSON": (json.dumps(workflow, separators=(",", ":")) + "\n").encode("ascii"),
    }


def stale_files(files: dict[str, bytes]) -> list[str]:
    return [
        name for name, data in files.items()
        if not (BUNDLE_DIR / name).exists() or _lf((BUNDLE_DIR / name).read_bytes()) != data
    ]


def main(argv: list[str]) -> int:
    files = build()
    if "--check" in argv:
        stale = stale_files(files)
        if stale:
            print("stale bundle files (run build_remission_bundle.py): " + ", ".join(stale))
            return 1
        print("remission bundle is up to date")
        return 0
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (BUNDLE_DIR / name).write_bytes(data)
        print("wrote " + str((BUNDLE_DIR / name).relative_to(ROOT)) + " (" + str(len(data)) + " bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
