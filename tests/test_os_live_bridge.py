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
Tests for os_live_bridge — parsing the kernel's serial output into
milestones and streaming a check run into live_store. A fake command
replays real `cargo run -- check` output, so these run without QEMU.
"""
import os
import sys

import pytest

import live_store
from os_live_bridge import parse_line, run_check

# Captured from a real `cargo run -- check` run (bootloader INFO lines trimmed).
REAL_CHECK_OUTPUT = """\
INFO : Jumping to kernel entry point at VirtAddr(0x10000028460)
Network OS prototype: booted in x86_64 QEMU.
PIT timer verified: 10 ticks at 100 ms.
network controller: 8086:100e at 00:03.0
E1000 initialized: MAC 52:54:00:12:34:56
Physical frame allocator verified: allocate, map, release, reuse.
DHCP configured: IPv4 10.0.2.15/24
IPv4 default gateway: 10.0.2.2
ICMP echo reply from 10.0.2.2
IPv6 SLAAC unavailable: QEMU user networking sent no router advertisement.
IPv6 configured (static fallback): fd00::5054:ff:fe12:3456/64
ICMPv6 echo reply from fd00::2
HTTP health service listening on port 8080
QEMU dual-stack HTTP service check passed.
"""


@pytest.fixture(autouse=True)
def _store(tmp_path):
    live_store.disable()
    yield live_store.enable(os.path.join(str(tmp_path), "live.db"))
    live_store.disable()


def _replay(text: str, exit_code: int = 0) -> list[str]:
    return [sys.executable, "-c", f"import sys; sys.stdout.write({text!r}); sys.exit({exit_code})"]


def test_parse_line_extracts_fields():
    assert parse_line("PIT timer verified: 10 ticks at 100 ms.")["fields"] == {"ticks": "10", "ms": "100"}
    assert parse_line("DHCP configured: IPv4 10.0.2.15/24")["fields"] == {"address": "10.0.2.15/24"}
    assert parse_line("E1000 initialized: MAC 52:54:00:12:34:56")["fields"]["mac"] == "52:54:00:12:34:56"
    assert parse_line("KERNEL PANIC: oops")["ok"] is False
    assert parse_line("INFO : Map framebuffer") is None


def test_real_check_output_passes_and_streams_live(_store):
    result = run_check("check", echo=lambda _: None, command=_replay(REAL_CHECK_OUTPUT))
    assert result["passed"] is True
    assert {"booted", "pit_timer", "frame_allocator", "dhcp", "icmp", "icmpv6",
            "http_health", "check_passed"} <= set(result["reached"])

    events = _store.events_after(0, stream="os")
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "check_started" and kinds[-2:] == ["check_result", "snapshot"]
    milestones = [e["data"]["milestone"] for e in events if e["kind"] == "milestone"]
    assert milestones[:3] == ["booted", "pit_timer", "nic_found"]   # in the order the kernel printed them

    snap = _store.get_snapshot("os", "check")["data"]
    assert snap["passed"] is True and snap["exit_code"] == 0


def test_slaac_fallback_is_not_a_failure_but_panic_is(_store):
    ok = run_check("check", echo=lambda _: None, command=_replay(REAL_CHECK_OUTPUT))
    assert ok["passed"]   # the SLAAC-unavailable line is a documented QEMU fallback

    panicked = REAL_CHECK_OUTPUT.replace("HTTP health", "KERNEL PANIC: page fault\nHTTP health")
    bad = run_check("check", echo=lambda _: None, command=_replay(panicked))
    assert bad["passed"] is False


def test_nonzero_exit_fails_even_with_all_milestones(_store):
    result = run_check("check", echo=lambda _: None, command=_replay(REAL_CHECK_OUTPUT, exit_code=1))
    assert result["passed"] is False and result["exit_code"] == 1


def test_missing_tool_is_reported_not_raised(_store):
    result = run_check("check", echo=lambda _: None, command=["definitely-not-a-real-binary-xyz"])
    assert result["passed"] is False
    assert "could not start" in result["error"]
    assert _store.get_snapshot("os", "check")["data"]["passed"] is False


def test_rejects_unknown_mode():
    with pytest.raises(ValueError):
        run_check("run")
