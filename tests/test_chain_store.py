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
Tests for chain_store — the single-node append-only, tamper-evident chain.
Pins genesis linkage, previous_hash chaining, whole-chain verification,
persistence across reload, and detection of both payload tampering and a
broken link.
"""
import os

from chain_store import ChainStore, ChainBlock, GENESIS_PREV_HASH


def test_genesis_tip_is_sentinel(tmp_path):
    chain = ChainStore(store_path=os.path.join(str(tmp_path), "c.json"))
    assert chain.tip_hash() == GENESIS_PREV_HASH


def test_blocks_link_to_previous_hash(tmp_path):
    chain = ChainStore(store_path=os.path.join(str(tmp_path), "c.json"))
    b1 = chain.append({"note": "one"})
    b2 = chain.append({"note": "two"})
    assert b1.previous_hash == GENESIS_PREV_HASH
    assert b2.previous_hash == b1.block_hash
    assert chain.tip_hash() == b2.block_hash
    assert b1.index == 0 and b2.index == 1


def test_verify_chain_ok_when_intact(tmp_path):
    chain = ChainStore(store_path=os.path.join(str(tmp_path), "c.json"))
    for i in range(4):
        chain.append({"n": i})
    ok, msg = chain.verify_chain()
    assert ok is True
    assert "4 blocks verified" in msg


def test_persistence_across_reload(tmp_path):
    path = os.path.join(str(tmp_path), "c.json")
    chain = ChainStore(store_path=path)
    chain.append({"a": 1})
    chain.append({"b": 2})

    reloaded = ChainStore(store_path=path)
    assert len(reloaded.blocks) == 2
    ok, _ = reloaded.verify_chain()
    assert ok is True
    # reloaded blocks preserve their real hashes/links
    assert reloaded.blocks[1].previous_hash == reloaded.blocks[0].block_hash


def test_payload_tampering_is_detected(tmp_path):
    chain = ChainStore(store_path=os.path.join(str(tmp_path), "c.json"))
    chain.append({"note": "real"})
    chain.append({"note": "also real"})
    chain.blocks[0].payload["note"] = "TAMPERED"
    ok, msg = chain.verify_chain()
    assert ok is False
    assert "tampered" in msg.lower()


def test_broken_link_is_detected(tmp_path):
    chain = ChainStore(store_path=os.path.join(str(tmp_path), "c.json"))
    chain.append({"n": 0})
    chain.append({"n": 1})
    # break the linkage without touching payload/hash
    chain.blocks[1].previous_hash = "f" * 64
    ok, msg = chain.verify_chain()
    assert ok is False
    assert "previous_hash mismatch" in msg


def test_empty_chain_verifies_trivially(tmp_path):
    chain = ChainStore(store_path=os.path.join(str(tmp_path), "c.json"))
    ok, msg = chain.verify_chain()
    assert ok is True
    assert "0 blocks verified" in msg
