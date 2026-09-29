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
ai_gossip.py
================
Periodic real analysis of a NetworkNode's network_ledger. Every
interval_s, this looks at the node's ACTUAL current mos_score() and
ledger contents, derives a real summary statistic from them (not an
LLM call, not fabricated commentary -- a deterministic numeric
summary of real data already on the node), and folds that summary
into the node's own DigitalDNA strand via the "ai_insight" source --
which digital_dna.py's ALLOWED_SOURCES already documents as
"system-generated — derived analysis of already-consented blocks, not
new personal capture". That's exactly what this is: nothing here
reads a new external signal, it only re-derives from data the node
already legitimately holds.

Also credits the node a small amount in the shared TokenLedger for
each analysis pass, same "real activity, locally-scored" pattern as
mining a block.

Usage
-----
    from ai_gossip import AIParticipant

    ai = AIParticipant(node, dna, ledger, interval_s=600, audit=audit)
    await ai.start()
    ...
    await ai.stop()
"""

from __future__ import annotations
import asyncio
import hashlib
import json


class AIParticipant:
    def __init__(self, node, dna, ledger, interval_s: int = 600, audit=None):
        self.node = node
        self.dna = dna
        self.ledger = ledger
        self.interval_s = interval_s
        self.audit = audit
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self):
        while True:
            await asyncio.sleep(self.interval_s)
            self.analyze_once()

    def analyze_once(self) -> dict:
        """Real, synchronous, deterministic analysis pass -- exposed as its
        own method (not just buried in the loop) so it can be called
        directly, e.g. for a one-off manual check or a test."""
        mos = self.node.mos_score()

        # a real, deterministic summary of what's actually in the ledger
        # right now -- not fabricated text, just a canonical digest of
        # real numbers already computed by mos_score()
        summary = {
            "mos": mos["mos"], "quality": mos["quality"],
            "connectivity": mos["connectivity"], "agreement": mos["agreement"],
            "known_peers": mos["known_peers"], "total_blocks_seen": mos["total_blocks_seen"],
        }
        summary_str = json.dumps(summary, sort_keys=True)
        feature_hash = hashlib.sha256(summary_str.encode()).hexdigest()

        confidence = min(1.0, mos["known_peers"] / 5.0) if mos["known_peers"] else 0.3
        event = self.dna.add_live_signal(
            "ai_insight", feature_hash, confidence=confidence, consent_verified=True,
        )

        self.ledger.credit(self.node.node_id, 0.1, reason="network_analysis")

        if self.audit is not None:
            self.audit.log(
                module="ai_gossip", action="analysis", node_id=self.node.node_id,
                details={"summary": summary, "feature_hash": feature_hash},
            )

        return {"summary": summary, "feature_hash": feature_hash, "mutation_event": event}


if __name__ == "__main__":
    import asyncio as _asyncio
    import os
    import sys
    import tempfile

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from digital_dna import DigitalDNA
    from network_os import NetworkNode
    from token_ledger import TokenLedger

    async def _demo():
        with tempfile.TemporaryDirectory() as tmp:
            dna = DigitalDNA(seed_label="ai-gossip-demo", dna_path=os.path.join(tmp, "demo.dna.json"))
            node = NetworkNode(dna, host="127.0.0.1", port=8901)
            await node.start()

            ledger = TokenLedger(store_path=os.path.join(tmp, "ledger.json"))
            ai = AIParticipant(node, dna, ledger, interval_s=600)

            strand_before = dna.as_hex()
            result = ai.analyze_once()
            print(f"Analysis summary: {result['summary']}")
            print(f"Strand changed after analysis: {dna.as_hex() != strand_before}")
            print(f"Live signal recorded with source=ai_insight: "
                  f"{any(b.get('source') == 'ai_insight' for b in dna.audit_trail())}")
            print(f"Node credited: {ledger.balance(node.node_id)} (expected 0.1)")

            await node.stop()

    _asyncio.run(_demo())
