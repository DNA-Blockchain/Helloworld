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
os_live_bridge.py — runs the Rust kernel prototype's QEMU check and
streams what it reports into live_store.py as stream "os", so kernel boots
show up on the same live feed (live_feed.py) as the Python nodes.

The kernel can't run the Python application (see KNOWN_GAPS.md), so this
is the bridge: the host runs `cargo run -- check` (or check-slaac) in os/,
reads the kernel's serial output line by line, and turns each recognised
milestone -- boot, PIT timer, frame allocator, E1000, DHCP, ICMP, IPv6,
HTTP health -- into a live event the moment it prints. When the run ends
it writes one "os" snapshot per mode with pass/fail, every milestone, the
exit code, the duration and the git commit it tested.

It only reads what the kernel prints; a milestone here means "the kernel
said so over serial", the same evidence `cargo run -- check` itself uses.

Timing, honestly: the bridge emits each line as soon as it reads it, but
os/src/main.rs currently buffers the kernel's serial output and prints it
all once the check finishes, so today the milestones arrive together at
the end (their `t` values show this). Printing each line as it is
received in run_integration_check() would make them arrive live with no
change here.

Usage
-----
    python os_live_bridge.py                         # check, into live_store.db
    python os_live_bridge.py --mode check-slaac
    python os_live_bridge.py --db autonomous/live_store.db --audit system_audit.jsonl

Needs cargo and qemu-system-x86_64. If they aren't on PATH, the usual
Windows install locations (~/.cargo/bin, C:\\Program Files\\qemu) are tried.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

import live_store

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OS_DIR = os.path.join(PROJECT_DIR, "os")
MODES = ("check", "check-slaac")

# (milestone name, pattern, ok) -- first match per line wins. `ok=False`
# marks lines that report a failure or a degraded fallback.
MILESTONES: list[tuple[str, re.Pattern, bool]] = [
    (name, re.compile(pattern), ok) for name, pattern, ok in [
        ("booted", r"^Network OS prototype: booted", True),
        ("pit_timer", r"^PIT timer verified: (?P<ticks>\d+) ticks at (?P<ms>\d+) ms", True),
        ("nic_found", r"^network controller: (?P<pci_id>\S+) at (?P<slot>\S+)", True),
        ("e1000", r"^E1000 initialized: MAC (?P<mac>[0-9a-f:]{17})", True),
        ("frame_allocator", r"^Physical frame allocator verified", True),
        ("dhcp", r"^DHCP configured: IPv4 (?P<address>\S+)", True),
        ("ipv4_gateway", r"^IPv4 default gateway: (?P<gateway>\S+)", True),
        ("icmp", r"^ICMP echo reply from (?P<peer>\S+)", True),
        ("slaac", r"^IPv6 SLAAC configured: (?P<address>\S+)", True),
        ("slaac", r"^IPv6 SLAAC unavailable", False),
        ("ipv6_static", r"^IPv6 configured \(static fallback\): (?P<address>\S+)", True),
        ("ipv6_gateway", r"^IPv6 default gateway: (?P<gateway>\S+)", True),
        ("icmpv6", r"^ICMPv6 echo reply from (?P<peer>\S+)", True),
        ("http_health", r"^HTTP health service listening on port (?P<port>\d+)", True),
        ("check_passed", r"check passed\.$", True),
        ("kernel_panic", r"^KERNEL PANIC: (?P<info>.*)", False),
        ("exception", r"^UNHANDLED EXCEPTION OR INTERRUPT", False),
        ("network_failed", r"^Network initialization failed: (?P<error>.*)", False),
        ("qemu_missing", r"^Could not start qemu-system-x86_64", False),
    ]
]


def parse_line(line: str) -> dict | None:
    """One line of kernel/runner output -> a milestone dict, or None."""
    line = line.strip()
    for name, pattern, ok in MILESTONES:
        m = pattern.search(line)
        if m:
            return {"milestone": name, "ok": ok, "line": line,
                    "fields": {k: v for k, v in m.groupdict().items() if v is not None}}
    return None


def _tool_env() -> dict:
    env = dict(os.environ)
    extra = [os.path.join(os.path.expanduser("~"), ".cargo", "bin"), r"C:\Program Files\qemu"]
    missing = [d for d in extra if os.path.isdir(d)]
    if missing and not (shutil.which("cargo") and shutil.which("qemu-system-x86_64")):
        env["PATH"] = os.pathsep.join(missing + [env.get("PATH", "")])
    return env


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_DIR,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def run_check(mode: str = "check", echo=print, timeout_s: float = 600.0,
              command: list[str] | None = None) -> dict:
    """Runs the kernel check, emitting each milestone live; returns the result
    (also saved as the ("os", mode) snapshot). `command` overrides the
    cargo invocation (tests use it)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    started = time.time()
    commit = _git_commit()
    live_store.emit("os", mode, "check_started", {"mode": mode, "commit": commit})

    milestones: list[dict] = []
    cmd = command or ["cargo", "run", "--quiet", "--", mode]
    env = _tool_env()
    # Windows resolves the executable from this process's PATH, not env's
    cmd = [shutil.which(cmd[0], path=env["PATH"]) or cmd[0], *cmd[1:]]
    try:
        proc = subprocess.Popen(cmd, cwd=OS_DIR, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        exit_code, error = None, f"could not start {cmd[0]}: {e}"
    else:
        error = None
        deadline = started + timeout_s
        for line in proc.stdout:
            echo(line.rstrip())
            hit = parse_line(line)
            if hit:
                hit["t"] = round(time.time() - started, 3)
                milestones.append(hit)
                live_store.emit("os", mode, "milestone", hit)
            if time.time() > deadline:
                proc.kill()
                error = f"timed out after {timeout_s:.0f}s"
                break
        exit_code = proc.wait()

    reached = {m["milestone"] for m in milestones if m["ok"]}
    failures = [m for m in milestones if not m["ok"] and m["milestone"] != "slaac"]
    passed = exit_code == 0 and "check_passed" in reached and not failures and error is None
    result = {
        "mode": mode, "passed": passed, "exit_code": exit_code, "error": error,
        "commit": commit, "started_at": started, "duration_s": round(time.time() - started, 3),
        "milestones": milestones, "reached": sorted(reached),
    }
    live_store.emit("os", mode, "check_result",
                    {k: v for k, v in result.items() if k != "milestones"})
    live_store.snapshot("os", mode, result)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the kernel's QEMU check and stream it into live_store.")
    p.add_argument("--mode", choices=MODES, default="check")
    p.add_argument("--db", default=os.environ.get(live_store.ENV_VAR) or os.path.join(PROJECT_DIR, "live_store.db"),
                   help="live_store.py SQLite file (default: $%s or live_store.db)" % live_store.ENV_VAR)
    p.add_argument("--audit", help="also log the result to this audit_trail.py JSONL file")
    p.add_argument("--timeout", type=float, default=600.0, help="seconds, including the cargo build")
    args = p.parse_args(argv)

    live_store.enable(args.db)
    result = run_check(args.mode, timeout_s=args.timeout)
    if args.audit:
        from audit_trail import AuditTrail
        AuditTrail(args.audit).log(module="os_live_bridge", action=f"kernel_{args.mode}", node_id="os",
                                   details={k: result[k] for k in ("passed", "exit_code", "commit",
                                                                   "duration_s", "reached")})
    status = "PASSED" if result["passed"] else "FAILED"
    print(f"\n[os_live_bridge] kernel {args.mode} {status} in {result['duration_s']}s "
          f"({len(result['reached'])} milestones) -> {args.db}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
