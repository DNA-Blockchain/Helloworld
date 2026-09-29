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
research_ledger.py
==================
Permanent, replicated record of every public research and dataset event
published on the node network.

Node chains hold only the blocks each node mined, and node_supervisor.py
archives them daily and prunes the archive after 30 days. The research
ledger is separate: every node keeps research_ledger_node-N.json (never
archived or pruned), holding a copy of each verified block that carries

  - research_provenance events (public research records, hashes, provenance)
  - public_dataset_summary events (dataset_sharing.py)

Each entry keeps the original signed block, so any reader can re-verify it
against the origin node's pinned key. Entries are appended through
ChainStore, so the ledger file is itself hash-linked and tamper-evident.
Nodes fill it from blocks they mine, blocks they verify, their own current
and archived chains at startup, and peers' ledgers (NetworkNode ledger sync).
"""

from __future__ import annotations

import glob
import json
import os
from typing import Iterable, Optional

from chain_store import ChainStore
from research_provenance import validate_public_provenance

LEDGER_SCHEMA = "research-ledger-entry.v1"


def event_of(block: dict) -> Optional[tuple[str, str, dict]]:
    """(kind, event_id, event) for a block carrying a publishable event,
    or None. Invalid events are ignored rather than stored."""
    provenance = block.get("research_provenance")
    if isinstance(provenance, dict):
        try:
            validate_public_provenance(provenance)
        except ValueError:
            return None
        kind = provenance.get("event_type", "public_research_provenance")
        return kind, provenance["event_id"], provenance
    summary = block.get("public_dataset_summary")
    if isinstance(summary, dict) and isinstance(summary.get("dataset_id"), str):
        if summary.get("classification") != "public":
            return None
        return "public_dataset_summary", summary["dataset_id"], summary
    return None


class ResearchLedger:
    def __init__(self, path: str):
        self.path = path
        self.store = ChainStore(store_path=path)
        self._keys = {
            (entry.payload["origin"], entry.payload["event_id"])
            for entry in self.store.blocks
            if isinstance(entry.payload, dict)
        }

    def __len__(self) -> int:
        return len(self.store.blocks)

    def add_block(self, block: dict) -> bool:
        """Record a verified block if it carries a publishable event that is
        not already in the ledger. Callers must have verified the block's
        signature. Returns whether a new entry was added."""
        found = event_of(block)
        if found is None or not isinstance(block.get("origin"), int):
            return False
        kind, event_id, _ = found
        key = (block["origin"], event_id)
        if key in self._keys:
            return False
        self.store.append({
            "schema": LEDGER_SCHEMA,
            "kind": kind,
            "event_id": event_id,
            "origin": block["origin"],
            "origin_boot_id": block.get("boot_id"),
            "origin_index": block.get("index"),
            "block": block,
        })
        self._keys.add(key)
        return True

    def entries(self, since: int = 0, limit: Optional[int] = None) -> list[dict]:
        selected = self.store.blocks[since:] if limit is None else self.store.blocks[since:since + limit]
        return [entry.payload for entry in selected]

    def verify(self) -> tuple[bool, str]:
        return self.store.verify_chain()


def signed_blocks_in_chain_files(paths: Iterable[str]) -> list[dict]:
    """Signed block payloads from ChainStore files (a node's own current and
    archived chains), oldest file first. Unreadable files are skipped."""
    blocks = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as stream:
                stored = json.load(stream).get("blocks", [])
        except (OSError, ValueError):
            continue
        blocks.extend(b["payload"] for b in stored if isinstance(b, dict) and isinstance(b.get("payload"), dict))
    return blocks


def own_chain_files(node_dir: str, node_id: int) -> list[str]:
    """This node's archived chains (autonomous/archive/<date>/node-N/) and
    its current chain, oldest first."""
    base = os.path.dirname(os.path.abspath(node_dir))
    name = f"chain_node-{node_id}.json"
    archived = sorted(glob.glob(os.path.join(base, "archive", "*", f"node-{node_id}", name)))
    return archived + [os.path.join(node_dir, name)]


def load_all_ledgers(base_dir: str) -> dict[int, ResearchLedger]:
    """Every node's ledger under base_dir (autonomous/), by node id."""
    ledgers = {}
    for path in sorted(glob.glob(os.path.join(base_dir, "node-*", "research_ledger_node-*.json"))):
        name = os.path.basename(path)
        try:
            node_id = int(name[len("research_ledger_node-"):-len(".json")])
        except ValueError:
            continue
        ledgers[node_id] = ResearchLedger(path)
    return ledgers
