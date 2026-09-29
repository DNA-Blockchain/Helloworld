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
token_ledger.py
================
A real, persisted balance ledger tracking per-node credits earned for
real contributions (mining a block, running a network-analysis pass,
etc.) — not a cryptocurrency, not tradable, not backed by anything.
"Token" here means the same thing DAS/MOS scores mean elsewhere in
this project: a locally-computed number reflecting real activity,
useful for ranking/rewarding participation within THIS node's own
view of the network. No consensus, no other node has to agree with
your balances.

Every balance change is itself an append-only, ordered transaction
record (not just a mutated number) — so `history()` can show exactly
why a balance is what it is, and re-deriving the current balance from
the transaction log always matches what's stored.

Usage
-----
    from token_ledger import TokenLedger

    ledger = TokenLedger(store_path="token_ledger.json", audit=audit)
    ledger.credit("node-a", 1.5, reason="mine_block")
    ledger.balance("node-a")      # 1.5
    ledger.history("node-a")      # [{"amount": 1.5, "reason": "mine_block", ...}]
"""

from __future__ import annotations
import json
import os
import time

import live_store
from atomic_io import replace_with_retry


class TokenLedger:
    def __init__(self, store_path: str | None = None, audit=None):
        self.store_path = store_path
        self.audit = audit
        self.transactions: list[dict] = []

        if store_path and os.path.exists(store_path):
            with open(store_path, "r", encoding="utf-8") as f:
                self.transactions = json.load(f)

    def _save(self):
        if not self.store_path:
            return
        tmp_path = self.store_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.transactions, f, indent=2)
        replace_with_retry(tmp_path, self.store_path)

    def credit(self, node_id: str, amount: float, reason: str) -> dict:
        """amount may be negative (a debit) -- there's no floor at zero
        enforced here, same as a real ledger: a negative balance is a
        fact to look at, not an error to hide."""
        tx = {"timestamp": time.time(), "node_id": node_id, "amount": amount, "reason": reason}
        self.transactions.append(tx)
        self._save()
        live_store.emit("ledger", node_id, "credit", tx)

        if self.audit is not None:
            self.audit.log(
                module="token_ledger", action="credit", node_id=node_id,
                details={"amount": amount, "reason": reason, "new_balance": self.balance(node_id)},
            )
        return tx

    def balance(self, node_id: str) -> float:
        return round(sum(tx["amount"] for tx in self.transactions if tx["node_id"] == node_id), 6)

    def history(self, node_id: str | None = None) -> list[dict]:
        if node_id is None:
            return list(self.transactions)
        return [tx for tx in self.transactions if tx["node_id"] == node_id]

    def all_balances(self) -> dict[str, float]:
        node_ids = {tx["node_id"] for tx in self.transactions}
        return {nid: self.balance(nid) for nid in node_ids}

    # ---- award/leaderboard: positive-only contribution points ----
    # Additive convenience for reward-style callers (e.g. a token demo that
    # grants points for peer-verified blocks). award() is just credit()
    # restricted to positive amounts and recorded through the SAME
    # transaction log, so balance()/history()/all_balances()/audit all keep
    # working unchanged. NOT a currency -- same "local score" meaning as
    # DAS/MOS elsewhere in this project.
    def award(self, node_id: str, amount: int, reason: str) -> float:
        """Grant a positive number of contribution points and return the
        node's NEW balance. Refuses <= 0 (use credit() directly if you
        genuinely need a debit)."""
        if amount <= 0:
            raise ValueError("award() requires a positive amount")
        self.credit(node_id, amount, reason)
        return self.balance(node_id)

    def leaderboard(self) -> list[tuple[str, float]]:
        """All known nodes sorted by balance, highest first."""
        return sorted(self.all_balances().items(), key=lambda kv: -kv[1])


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ledger.json")
        ledger = TokenLedger(store_path=path)

        ledger.credit("node-a", 1.0, reason="mine_block")
        ledger.credit("node-a", 0.5, reason="network_analysis")
        ledger.credit("node-b", 2.0, reason="mine_block")

        print(f"node-a balance: {ledger.balance('node-a')} (expected 1.5)")
        print(f"node-b balance: {ledger.balance('node-b')} (expected 2.0)")
        print(f"node-a history: {ledger.history('node-a')}")
        print(f"all balances: {ledger.all_balances()}")

        print("\n=== Reload from disk: balances survive a restart ===")
        ledger2 = TokenLedger(store_path=path)
        print(f"node-a balance after reload: {ledger2.balance('node-a')} (expected 1.5)")

        print("\n=== Debit (negative credit) ===")
        ledger2.credit("node-a", -0.25, reason="correction")
        print(f"node-a balance after debit: {ledger2.balance('node-a')} (expected 1.25)")
