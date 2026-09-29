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

import os

from network_os import PeerInfo
from peer_history_store import save_peer_history, load_peer_history, merge_loaded_history_into_node


class FakeNode:
    def __init__(self, peers=None):
        self.peers = peers or {}


def test_save_and_load_roundtrip(tmp_path):
    path = os.path.join(str(tmp_path), "history.json")
    history = [("1.2.3.4", 9001, 100.0), ("1.2.3.4", 9002, 200.0)]
    peer = PeerInfo(node_id="peer-1", host="1.2.3.4", port=9002, last_seen=200.0, address_history=history)
    node = FakeNode(peers={"peer-1": peer})

    save_peer_history(node, path)
    loaded = load_peer_history(path)

    assert "peer-1" in loaded
    assert loaded["peer-1"]["last_seen"] == 200.0
    assert loaded["peer-1"]["address_history"] == [["1.2.3.4", 9001, 100.0], ["1.2.3.4", 9002, 200.0]]


def test_load_missing_file_returns_empty_dict(tmp_path):
    path = os.path.join(str(tmp_path), "does_not_exist.json")
    assert load_peer_history(path) == {}


def test_merge_restores_peer_not_currently_connected(tmp_path):
    path = os.path.join(str(tmp_path), "history.json")
    history = [("1.2.3.4", 9001, 100.0)]
    peer = PeerInfo(node_id="peer-1", host="1.2.3.4", port=9001, last_seen=100.0, address_history=history)
    save_peer_history(FakeNode(peers={"peer-1": peer}), path)

    fresh_node = FakeNode(peers={})
    restored = merge_loaded_history_into_node(fresh_node, path)

    assert restored == 1
    assert "peer-1" in fresh_node.peers
    assert fresh_node.peers["peer-1"].address_history == [["1.2.3.4", 9001, 100.0]]


def test_merge_does_not_restore_session_key_or_signing_pub(tmp_path):
    """Security boundary: restoring crypto session state from disk would
    mean trusting a peer without re-verifying their signature."""
    path = os.path.join(str(tmp_path), "history.json")
    history = [("1.2.3.4", 9001, 100.0)]
    peer = PeerInfo(node_id="peer-1", host="1.2.3.4", port=9001, last_seen=100.0, address_history=history)
    save_peer_history(FakeNode(peers={"peer-1": peer}), path)

    fresh_node = FakeNode(peers={})
    merge_loaded_history_into_node(fresh_node, path)

    assert fresh_node.peers["peer-1"].signing_pub is None
    assert fresh_node.peers["peer-1"].session_key is None
    assert fresh_node.peers["peer-1"].writer is None


def test_merge_does_not_overwrite_an_already_connected_peer(tmp_path):
    path = os.path.join(str(tmp_path), "history.json")
    old_history = [("1.2.3.4", 9001, 100.0)]
    old_peer = PeerInfo(node_id="peer-1", host="1.2.3.4", port=9001, last_seen=100.0, address_history=old_history)
    save_peer_history(FakeNode(peers={"peer-1": old_peer}), path)

    live_peer = PeerInfo(node_id="peer-1", host="5.6.7.8", port=9999, last_seen=999.0,
                          address_history=[("5.6.7.8", 9999, 999.0)], signing_pub="real-key")
    node_with_live_peer = FakeNode(peers={"peer-1": live_peer})

    restored = merge_loaded_history_into_node(node_with_live_peer, path)

    assert restored == 0
    assert node_with_live_peer.peers["peer-1"].signing_pub == "real-key"
