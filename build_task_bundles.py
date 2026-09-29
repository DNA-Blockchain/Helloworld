#!/usr/bin/env python3
# ============================================================================
#  SPDX-License-Identifier: UPL-1.0
#
#  Copyright (c) 2026 Chase Allen Ringquist
#
#  This file is part of an operating system, software, and network Work
#  conceived and authored by Chase Allen Ringquist. The Author retains
#  copyright and authorship. Use of this file is licensed as follows.
#
#  ----------------------------------------------------------------------------
#  The Universal Permissive License (UPL), Version 1.0
#
#  Subject to the condition set forth below, permission is hereby granted to
#  any person obtaining a copy of this software, associated documentation
#  and/or data (collectively the "Software"), free of charge and under any
#  and all copyright rights in the Software, and any and all patent rights
#  owned or freely licensable by each licensor hereunder covering either
#  (i) the unmodified Software as contributed to or provided by such
#  licensor, or (ii) the Larger Works (as defined below), to deal in both
#
#  (a) the Software, and
#
#  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
#  if one is included with the Software (each a "Larger Work" to which the
#  Software is contributed by such licensors),
#
#  without restriction, including without limitation the rights to copy,
#  create derivative works of, display, perform, and distribute the Software
#  and make, use, sell, offer for sale, import, export, have made, and have
#  sold the Software and the Larger Work(s), and to sublicense the foregoing
#  rights on either these or other terms.
#
#  This license is subject to the following condition:
#
#  The above copyright notice and either this complete permission notice or
#  at a minimum a reference to the UPL must be included in all copies or
#  substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#  ----------------------------------------------------------------------------
#
#  Do not remove or alter this notice or any record of origin.
#  See NOTICE.md in the project root for authorship and ownership terms.
#
#  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
#            Bixby, OK, United States
# ============================================================================

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
    OUTPUT.SHA256  SHA-256 of the module's output for <INPUT> under CPython

The kernel embeds these files and runs each bundle at boot, and requires its
ring-3 MicroPython output to match OUTPUT.SHA256 byte for byte. Generating
them from the host modules keeps one source of truth.

Usage:
    python build_task_bundles.py          # (re)write every bundle
    python build_task_bundles.py --check  # exit 1 if any bundle is stale
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "os" / "tasks"
OUTPUT_DIGEST = "OUTPUT.SHA256"
# Characters the sample writes as \u surrogate-pair escapes (the Mathematical
# Alphanumeric Symbols block); every other character is raw UTF-8.
ESCAPED_IN_SAMPLE = re.compile("[\U0001d400-\U0001d7ff]")


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


def _surrogate_pair(match: re.Match) -> str:
    code = ord(match.group()) - 0x10000
    return "\\u%04x\\u%04x" % (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF))


def sample_bytes(request: dict) -> bytes:
    """The input as UTF-8 JSON (as research_fetch.py writes it), with the
    ESCAPED_IN_SAMPLE characters as surrogate-pair escapes, so the boot check
    covers both ways a character outside the BMP can reach the kernel."""
    text = json.dumps(request, indent=2, ensure_ascii=False)
    return (ESCAPED_IN_SAMPLE.sub(_surrogate_pair, text) + "\n").encode("utf-8")


def reference_output(bundle: Bundle, sample: bytes) -> bytes:
    """What the module writes for `sample` under CPython, through the same
    main() the kernel runs."""
    module = importlib.import_module(bundle.module.removesuffix(".py"))
    with tempfile.TemporaryDirectory() as scratch:
        source = Path(scratch) / bundle.input_name
        output = Path(scratch) / bundle.output_name
        source.write_bytes(sample)
        with contextlib.redirect_stdout(io.StringIO()):
            module.main(["task", str(source), "--output", str(output)])
        return output.read_bytes()


def build(bundle: Bundle) -> dict[str, bytes]:
    entry = _lf((ROOT / bundle.module).read_bytes())
    sample = sample_bytes(bundle.input_request())
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
        OUTPUT_DIGEST: (hashlib.sha256(reference_output(bundle, sample)).hexdigest() + "\n").encode("ascii"),
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
