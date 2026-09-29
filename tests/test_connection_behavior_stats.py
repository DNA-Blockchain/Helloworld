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

import time

from network_os import PeerInfo
from connection_behavior_stats import connection_behavior_for_peer


def _peer_with_history(history):
    return PeerInfo(node_id="test-peer", host="127.0.0.1", port=9999, address_history=history)


def test_no_history_returns_zeroed_stats():
    peer = _peer_with_history([])
    stats = connection_behavior_for_peer(peer)
    assert stats == {"conn_reconnect_count": 0, "conn_unique_addresses": 0, "conn_uptime_seconds": 0}


def test_single_connection_has_zero_reconnects():
    now = time.time()
    peer = _peer_with_history([("1.2.3.4", 9001, now)])
    stats = connection_behavior_for_peer(peer)
    assert stats["conn_reconnect_count"] == 0
    assert stats["conn_unique_addresses"] == 1


def test_three_connections_from_different_addresses():
    now = time.time()
    history = [
        ("1.2.3.4", 9001, now),
        ("1.2.3.4", 9002, now + 1),
        ("1.2.3.4", 9003, now + 2),
    ]
    peer = _peer_with_history(history)
    stats = connection_behavior_for_peer(peer)
    assert stats["conn_reconnect_count"] == 2
    assert stats["conn_unique_addresses"] == 3
    assert stats["conn_avg_seconds_between_reconnects"] == 1.0


def test_repeated_connections_from_same_address_still_count_as_reconnects():
    """address_history entries are only appended when the address
    actually changes (see network_os.py's _dispatch), so every entry
    here is by definition a distinct address -- but conn_unique_addresses
    should still correctly dedupe if the same address appears twice
    non-consecutively."""
    now = time.time()
    history = [
        ("1.2.3.4", 9001, now),
        ("1.2.3.4", 9002, now + 1),
        ("1.2.3.4", 9001, now + 2),  # back to the first address
    ]
    peer = _peer_with_history(history)
    stats = connection_behavior_for_peer(peer)
    assert stats["conn_reconnect_count"] == 2
    assert stats["conn_unique_addresses"] == 2  # only 2 distinct (host, port) pairs
