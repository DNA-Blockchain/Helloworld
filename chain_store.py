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
chain_store.py — real append-only chain with previous_hash linkage.

Scope, honestly: this is a single node's own local chain — each block
points to the previous block's hash, and verify_chain() walks the whole
thing checking every link, same pattern as the project's earlier
reconstruct_maxwell_chain.py. What this does NOT do: multi-node consensus
or fork resolution (deciding whose chain "wins" when two nodes disagree).
That's a real, separate piece of work — this gives each node an honest,
tamper-evident local ledger of what IT has mined and verified, not a
Byzantine-fault-tolerant shared chain.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field

import live_store
from atomic_io import replace_with_retry

GENESIS_PREV_HASH = "0" * 64


@dataclass
class ChainBlock:
    index: int
    previous_hash: str
    payload: dict
    timestamp: float = field(default_factory=time.time)
    block_hash: str = ""

    def compute_hash(self) -> str:
        material = json.dumps(
            {
                "index": self.index,
                "previous_hash": self.previous_hash,
                "payload": self.payload,
                "timestamp": self.timestamp,
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "previous_hash": self.previous_hash,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "block_hash": self.block_hash,
        }


class ChainStore:
    """Append-only, persisted, tamper-evident local chain."""

    def __init__(self, store_path: str | None = None):
        self.store_path = store_path
        self.blocks: list[ChainBlock] = []
        self._load()

    def _load(self) -> None:
        if self.store_path and os.path.exists(self.store_path):
            try:
                with open(self.store_path) as f:
                    data = json.load(f)
                self.blocks = [ChainBlock(**b) for b in data.get("blocks", [])]
            except Exception:
                self.blocks = []

    def _save(self) -> None:
        if not self.store_path:
            return
        tmp = f"{self.store_path}.tmp"
        with open(tmp, "w") as f:
            json.dump({"blocks": [b.to_dict() for b in self.blocks]}, f, indent=2)
        replace_with_retry(tmp, self.store_path)

    def tip_hash(self) -> str:
        return self.blocks[-1].block_hash if self.blocks else GENESIS_PREV_HASH

    def append(self, payload: dict) -> ChainBlock:
        block = ChainBlock(
            index=len(self.blocks),
            previous_hash=self.tip_hash(),
            payload=payload,
        )
        block.block_hash = block.compute_hash()
        self.blocks.append(block)
        self._save()
        live_store.emit("chain", live_store.source_from_path(self.store_path), "block", block.to_dict())
        return block

    def verify_chain(self) -> tuple[bool, str]:
        """Real verification: recompute every block's hash and check every
        previous_hash link, in order."""
        expected_prev = GENESIS_PREV_HASH
        for b in self.blocks:
            if b.previous_hash != expected_prev:
                return False, f"block #{b.index}: previous_hash mismatch"
            recomputed = b.compute_hash()
            if recomputed != b.block_hash:
                return False, f"block #{b.index}: stored hash does not match recomputed hash (tampered)"
            expected_prev = b.block_hash
        return True, f"{len(self.blocks)} blocks verified, chain intact"


def _run_self_tests() -> None:
    import tempfile

    print("=" * 70)
    print("chain_store.py — real verification")
    print("=" * 70)
    failures = []

    def check(label, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        if not cond:
            failures.append(label)

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "chain.json")
        chain = ChainStore(store_path=path)

        check("genesis tip_hash is the sentinel", chain.tip_hash() == GENESIS_PREV_HASH)

        b1 = chain.append({"note": "first real block"})
        b2 = chain.append({"note": "second real block"})
        b3 = chain.append({"note": "third real block"})

        check("block #1 links to genesis", b1.previous_hash == GENESIS_PREV_HASH)
        check("block #2 links to block #1's real hash", b2.previous_hash == b1.block_hash)
        check("block #3 links to block #2's real hash", b3.previous_hash == b2.block_hash)

        ok, msg = chain.verify_chain()
        check(f"full chain verifies: {msg}", ok)

        # Reload from disk and re-verify
        chain2 = ChainStore(store_path=path)
        check("reloaded chain has same length", len(chain2.blocks) == 3)
        ok2, msg2 = chain2.verify_chain()
        check(f"reloaded chain verifies: {msg2}", ok2)

        # Real tamper test
        chain2.blocks[1].payload["note"] = "TAMPERED"
        ok3, msg3 = chain2.verify_chain()
        check(f"tampering is detected: {msg3}", not ok3)

    print("\n" + "=" * 70)
    if failures:
        print(f"RESULT: {len(failures)} FAILED: {failures}")
        raise SystemExit(1)
    print("RESULT: all checks PASSED.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_tests()
