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

import pytest

from token_ledger import TokenLedger


def test_credit_and_balance():
    ledger = TokenLedger()
    ledger.credit("node-a", 1.0, reason="mine_block")
    ledger.credit("node-a", 0.5, reason="analysis")
    assert ledger.balance("node-a") == 1.5


def test_balances_are_per_node():
    ledger = TokenLedger()
    ledger.credit("node-a", 1.0, reason="mine_block")
    ledger.credit("node-b", 2.0, reason="mine_block")
    assert ledger.balance("node-a") == 1.0
    assert ledger.balance("node-b") == 2.0


def test_negative_credit_is_a_debit():
    ledger = TokenLedger()
    ledger.credit("node-a", 1.0, reason="mine_block")
    ledger.credit("node-a", -0.25, reason="correction")
    assert ledger.balance("node-a") == 0.75


def test_history_returns_only_that_node():
    ledger = TokenLedger()
    ledger.credit("node-a", 1.0, reason="mine_block")
    ledger.credit("node-b", 2.0, reason="mine_block")
    history = ledger.history("node-a")
    assert len(history) == 1
    assert history[0]["node_id"] == "node-a"


def test_persistence_across_reload(tmp_path):
    path = os.path.join(str(tmp_path), "ledger.json")
    TokenLedger(store_path=path).credit("node-a", 1.5, reason="mine_block")
    reloaded = TokenLedger(store_path=path)
    assert reloaded.balance("node-a") == 1.5


# -- award() / leaderboard() (positive-only contribution points) --

def test_award_adds_points_via_the_transaction_log():
    ledger = TokenLedger()
    ledger.award("node-a", 1, reason="peer verified block")
    ledger.award("node-a", 3, reason="research-linked block verified")
    assert ledger.balance("node-a") == 4
    # award records through the same log history()/all_balances() read
    assert len(ledger.history("node-a")) == 2


def test_award_returns_new_balance():
    ledger = TokenLedger()
    assert ledger.award("node-a", 2, reason="x") == 2
    assert ledger.award("node-a", 3, reason="y") == 5


def test_award_rejects_non_positive():
    ledger = TokenLedger()
    with pytest.raises(ValueError):
        ledger.award("node-a", 0, reason="zero")
    with pytest.raises(ValueError):
        ledger.award("node-a", -2, reason="negative")


def test_leaderboard_sorted_descending():
    ledger = TokenLedger()
    ledger.award("node-a", 2, reason="x")
    ledger.award("node-b", 5, reason="y")
    ledger.award("node-c", 1, reason="z")
    board = ledger.leaderboard()
    assert [n for n, _ in board] == ["node-b", "node-a", "node-c"]
    assert board[0] == ("node-b", 5)
