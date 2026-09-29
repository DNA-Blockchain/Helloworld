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

"""JSON interface for Blockchain-DNA research and explicitly approved code."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
from typing import Any

from growing_research_agent import GrowingResearchAgent

MAX_REQUEST_BYTES = 1_000_000
MAX_CODE_BYTES = 32_000
MAX_OUTPUT_BYTES = 64_000
MAX_EXECUTION_SECONDS = 5
_PYTHON_RUNNER = (
    "import sys; "
    "exec(compile(sys.stdin.buffer.read(), '<Blockchain-DNA snippet>', 'exec'))"
)


class ToolInputError(ValueError):
    """The request does not match a supported tool operation."""


def _required_string(request: dict, key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"'{key}' must be a non-empty string")
    return value.strip()


def interpret_records(records: list[dict]) -> dict:
    """Summarize provenance and identifiers without inferring study outcomes."""
    by_source: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    duplicates: list[dict[str, str]] = []
    missing_provenance: list[dict[str, str]] = []

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ToolInputError(f"records[{index}] must be an object")
        source = _required_string(record, "source")
        identifier = _required_string(record, "id")
        by_source[source] = by_source.get(source, 0) + 1
        key = (source.casefold(), identifier.casefold())
        if key in seen:
            duplicates.append({"source": source, "id": identifier})
        seen.add(key)
        if not record.get("url") and not record.get("source_url"):
            missing_provenance.append({"source": source, "id": identifier})

    return {
        "record_count": len(records),
        "source_counts": dict(sorted(by_source.items(), key=lambda item: item[0].casefold())),
        "duplicate_records": duplicates,
        "records_missing_source_url": missing_provenance,
        "interpretation": (
            "Counts and provenance checks only; this output does not assess "
            "scientific validity, study quality, or causal relationships."
        ),
    }


async def _run_research(condition: str, biomarker: str | None) -> dict:
    agent = GrowingResearchAgent(
        node=None,
        dna=None,
        store_path=os.path.join(os.getcwd(), "research_store.json"),
    )
    key = await agent.seed_topic(condition, biomarker)
    topic = agent.topics[key]
    source_ids = topic.get("all_ids", {})
    return {
        "topic": {"condition": condition, "biomarker": biomarker},
        "retrieved_at": topic["last_checked"],
        "sources": {
            source: {
                "status": topic.get("source_status", {}).get(source, {"status": "unknown"}),
                "record_count": len(ids),
                "ids": ids,
            }
            for source, ids in source_ids.items()
        },
        "new_ids": topic.get("new_ids_last_run", []),
        "related_topics": topic.get("related_topics_found", []),
        "storage": "research_store.json",
        "chain": "not written; this JSON research tool has no network-node connection",
    }


def _read_limited_output(stream, output: bytearray, truncated: list[bool]) -> None:
    while True:
        chunk = stream.read(4096)
        if not chunk:
            return
        remaining = MAX_OUTPUT_BYTES - len(output)
        if remaining > 0:
            output.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated[0] = True


def _execute_python(request: dict, allow_code_execution: bool) -> dict:
    if not allow_code_execution or request.get("user_confirmed") is not True:
        raise ToolInputError(
            "Python execution requires --allow-code-execution and user_confirmed: true"
        )

    code = _required_string(request, "code")
    code_bytes = code.encode("utf-8")
    if len(code_bytes) > MAX_CODE_BYTES:
        raise ToolInputError(f"'code' exceeds the {MAX_CODE_BYTES}-byte limit")

    timeout = request.get("timeout_seconds", MAX_EXECUTION_SECONDS)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 1 <= timeout <= MAX_EXECUTION_SECONDS:
        raise ToolInputError(f"'timeout_seconds' must be between 1 and {MAX_EXECUTION_SECONDS}")

    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
    }
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", "-c", _PYTHON_RUNNER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=tempfile.gettempdir(),
        env=env,
        creationflags=creationflags,
    )
    output = bytearray()
    truncated = [False]
    reader = threading.Thread(
        target=_read_limited_output, args=(process.stdout, output, truncated), daemon=True,
    )
    reader.start()

    try:
        process.stdin.write(code_bytes)
        process.stdin.close()
    except BrokenPipeError:
        pass

    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    reader.join(timeout=1)

    return {
        "status": "timed_out" if timed_out else "completed",
        "exit_code": process.returncode,
        "output": output.decode("utf-8", errors="replace"),
        "output_truncated": truncated[0],
        "execution_boundary": (
            "This is not a security sandbox. Code ran locally with this user's "
            "filesystem and network permissions; only elapsed time and captured "
            "output were limited."
        ),
    }


def execute_request(request: Any, allow_code_execution: bool = False) -> dict:
    if not isinstance(request, dict):
        raise ToolInputError("request must be a JSON object")

    action = _required_string(request, "action")
    if action == "research":
        condition = _required_string(request, "condition")
        biomarker = request.get("biomarker")
        if biomarker is not None and (not isinstance(biomarker, str) or not biomarker.strip()):
            raise ToolInputError("'biomarker' must be a non-empty string or null")
        result = asyncio.run(_run_research(condition, biomarker.strip() if biomarker else None))
        return {"ok": True, "action": action, "result": result}

    if action == "interpret":
        records = request.get("records")
        if not isinstance(records, list) or len(records) > 10_000:
            raise ToolInputError("'records' must be an array of at most 10000 items")
        return {"ok": True, "action": action, "result": interpret_records(records)}

    if action == "execute_python":
        return {
            "ok": True,
            "action": action,
            "result": _execute_python(request, allow_code_execution),
        }

    raise ToolInputError("'action' must be research, interpret, or execute_python")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Blockchain-DNA JSON research and interpreter tool")
    parser.add_argument(
        "--allow-code-execution",
        action="store_true",
        help="allow explicitly confirmed Python to run locally; this is not a security sandbox",
    )
    args = parser.parse_args(argv)

    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ToolInputError(f"JSON request exceeds the {MAX_REQUEST_BYTES}-byte limit")
        request = json.loads(raw)
        response = execute_request(request, allow_code_execution=args.allow_code_execution)
    except (ToolInputError, json.JSONDecodeError) as exc:
        response = {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
        print(json.dumps(response, ensure_ascii=False))
        return 2
    except Exception as exc:
        response = {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
        print(json.dumps(response, ensure_ascii=False))
        return 1

    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
