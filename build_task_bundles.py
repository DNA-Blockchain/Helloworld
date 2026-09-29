#!/usr/bin/env python3
"""
build_task_bundles.py
=====================
Packages host Python modules as Network OS MicroPython task bundles under
os/tasks/<name>/, following os/schemas/task-bundle-v1 and workflow-v1.
Each bundle holds:

    <ENTRY>.PY     byte-for-byte copy of the module (LF endings)
    <INPUT>        the synthetic input the kernel boot check uses
    <TASK>.JSON    task manifest with each file's size and SHA-256
    <FLOW>.JSON    one-block workflow: input -> task -> declared .OUT output

The kernel embeds these files and runs each bundle at boot. Generating them
from the host modules keeps one source of truth.

Usage:
    python build_task_bundles.py          # (re)write every bundle
    python build_task_bundles.py --check  # exit 1 if any bundle is stale
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "os" / "tasks"


@dataclass(frozen=True)
class Bundle:
    name: str
    task_id: str
    module: str
    entrypoint: str
    input_name: str
    input_request: Callable[[], dict]
    task_manifest: str
    workflow_manifest: str
    output_name: str
    memory_bytes: int
    runtime_seconds: int

    @property
    def directory(self) -> Path:
        return TASKS_DIR / self.name


def _remission_input() -> dict:
    from remission_workflow import DEMO_REQUEST

    return DEMO_REQUEST


def _research_input() -> dict:
    from research_fetch import FIXTURE_REQUEST

    return FIXTURE_REQUEST


BUNDLES = (
    Bundle("remission", "remission-model", "remission_core.py", "REMISSION.PY", "SAMPLE.JSON",
           _remission_input, "RMTASK.JSON", "RMFLOW.JSON", "RESULT.OUT", 1048576, 30),
    Bundle("research", "research-analysis", "research_analysis.py", "RESEARCH.PY", "RESEARCH.JSON",
           _research_input, "RSTASK.JSON", "RSFLOW.JSON", "RANKED.OUT", 1048576, 30),
)


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _file_entry(name: str, role: str, data: bytes) -> dict:
    return {"name": name, "role": role, "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build(bundle: Bundle) -> dict[str, bytes]:
    entry = _lf((ROOT / bundle.module).read_bytes())
    sample = (json.dumps(bundle.input_request(), indent=2) + "\n").encode("ascii")
    task = {
        "schemaVersion": "nosfs.task-bundle.v1",
        "taskId": bundle.task_id,
        "runtime": "micropython",
        "entrypoint": bundle.entrypoint,
        "files": [
            _file_entry(bundle.entrypoint, "python", entry),
            _file_entry(bundle.input_name, "json", sample),
        ],
        "capabilities": {"network": {"dns": False, "udpDestinations": [], "tcpDestinations": [], "tlsHosts": []}},
        "limits": {"memoryBytes": bundle.memory_bytes, "runtimeSeconds": bundle.runtime_seconds},
    }
    workflow = {
        "schemaVersion": "nosfs.workflow.v1",
        "workflowId": bundle.task_id,
        "failurePolicy": "stop",
        "blocks": [{
            "blockId": bundle.task_id,
            "taskManifest": bundle.task_manifest,
            "dependsOn": [],
            "inputFiles": [bundle.input_name],
            "outputFiles": [bundle.output_name],
        }],
    }
    return {
        bundle.entrypoint: entry,
        bundle.input_name: sample,
        bundle.task_manifest: (json.dumps(task, separators=(",", ":")) + "\n").encode("ascii"),
        bundle.workflow_manifest: (json.dumps(workflow, separators=(",", ":")) + "\n").encode("ascii"),
    }


def stale_files(bundle: Bundle, files: dict[str, bytes]) -> list[str]:
    return [
        name for name, data in files.items()
        if not (bundle.directory / name).exists() or _lf((bundle.directory / name).read_bytes()) != data
    ]


def main(argv: list[str]) -> int:
    if "--check" in argv:
        stale = [f"{bundle.name}/{name}" for bundle in BUNDLES for name in stale_files(bundle, build(bundle))]
        if stale:
            print("stale bundle files (run build_task_bundles.py): " + ", ".join(stale))
            return 1
        print("task bundles are up to date")
        return 0
    for bundle in BUNDLES:
        bundle.directory.mkdir(parents=True, exist_ok=True)
        for name, data in build(bundle).items():
            (bundle.directory / name).write_bytes(data)
            print(f"wrote {(bundle.directory / name).relative_to(ROOT)} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
