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
research_timestamps.py
======================
OpenTimestamps proofs that each published research and dataset event
existed by a point in time. Combined with an event's Bitcoin time anchor
("created after block N"), this brackets when the event came to be.

For every event in the research ledgers this computes

    digest = SHA-256( canonical JSON of the event )

(the event is the `research_provenance` object of the event's block in
research_viewer's /api/export; canonical JSON is UTF-8 with sorted keys and
no whitespace: json.dumps(event, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)), and submits only that digest, behind a random nonce,
to public OpenTimestamps calendar servers. The event itself never leaves
this PC. The calendars' reply is stored as a standard .ots proof in
autonomous/timestamps/<event_id>.ots. It is "pending" at first; once a
calendar commits it to a Bitcoin block (usually within a few hours),
`upgrade` fetches the completed proof. Anyone can then verify it with the
standard `ots verify` tool or at opentimestamps.org.

Usage:
    python research_timestamps.py stamp     # submit digests of events without a proof
    python research_timestamps.py upgrade   # complete pending proofs from the calendars
    python research_timestamps.py status    # list proofs and whether they are in Bitcoin yet
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from opentimestamps.calendar import RemoteCalendar
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpAppend, OpSHA256
from opentimestamps.core.serialize import BytesDeserializationContext, BytesSerializationContext
from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

from research_ledger import load_all_ledgers

ROOT = Path(__file__).resolve().parent
DEFAULT_CALENDARS = (
    "https://a.pool.opentimestamps.org",
    "https://b.pool.opentimestamps.org",
    "https://a.pool.eternitywall.com",
)
DEFAULT_PROOF_DIR = ROOT / "autonomous" / "timestamps"


def event_payload(entry: dict) -> dict:
    """The published event inside a ledger entry's block."""
    block = entry["block"]
    return block.get("research_provenance") or block.get("public_dataset_summary")


def event_digest(event: dict) -> bytes:
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def ledger_events(base_dir: str) -> dict[str, dict]:
    """event_id -> event, across every node's ledger."""
    events = {}
    for ledger in load_all_ledgers(base_dir).values():
        for entry in ledger.entries():
            events.setdefault(entry["event_id"], event_payload(entry))
    return events


def stamp_digest(digest: bytes, calendars=DEFAULT_CALENDARS, timeout: float = 15) -> tuple[bytes, list[str]]:
    """A serialized .ots proof for `digest`, submitted to every reachable
    calendar behind a random nonce (as `ots stamp` does). Returns the proof
    and the calendars that failed; raises if none accepted it."""
    proof = DetachedTimestampFile(OpSHA256(), Timestamp(digest))
    nonced = proof.timestamp.ops.add(OpAppend(os.urandom(16)))
    tip = nonced.ops.add(OpSHA256())
    failed = []
    for url in calendars:
        try:
            tip.merge(RemoteCalendar(url).submit(tip.msg, timeout=timeout))
        except Exception as error:   # one calendar down must not stop the others
            failed.append(f"{url}: {error}")
    if len(failed) == len(calendars):
        raise RuntimeError("no OpenTimestamps calendar accepted the digest: " + "; ".join(failed))
    return serialize(proof), failed


def serialize(proof: DetachedTimestampFile) -> bytes:
    ctx = BytesSerializationContext()
    proof.serialize(ctx)
    return ctx.getbytes()


def load_proof(data: bytes) -> DetachedTimestampFile:
    return DetachedTimestampFile.deserialize(BytesDeserializationContext(data))


def _walk(timestamp: Timestamp):
    yield timestamp
    for child in timestamp.ops.values():
        yield from _walk(child)


def proof_state(proof: DetachedTimestampFile) -> dict:
    """{"bitcoin_heights": [...], "pending": [calendar URLs]}."""
    heights, pending = [], []
    for _, attestation in proof.timestamp.all_attestations():
        if isinstance(attestation, BitcoinBlockHeaderAttestation):
            heights.append(attestation.height)
        elif isinstance(attestation, PendingAttestation):
            pending.append(attestation.uri)
    return {"bitcoin_heights": sorted(set(heights)), "pending": sorted(set(pending))}


def upgrade_proof(proof: DetachedTimestampFile, timeout: float = 15) -> bool:
    """Ask each pending calendar for its completed timestamp and merge it.
    Returns whether anything new was learned."""
    changed = False
    for node in list(_walk(proof.timestamp)):
        for attestation in list(node.attestations):
            if not isinstance(attestation, PendingAttestation):
                continue
            try:
                upgraded = RemoteCalendar(attestation.uri).get_timestamp(node.msg, timeout=timeout)
            except Exception:   # not committed yet, or calendar unreachable
                continue
            before = proof_state(proof)
            node.merge(upgraded)
            changed |= proof_state(proof) != before
    return changed


def stamp_all(base_dir: str, proof_dir: Path, calendars=DEFAULT_CALENDARS) -> list[str]:
    proof_dir.mkdir(parents=True, exist_ok=True)
    notes = []
    for event_id, event in sorted(ledger_events(base_dir).items()):
        path = proof_dir / f"{event_id}.ots"
        if path.exists():
            continue
        try:
            data, failed = stamp_digest(event_digest(event), calendars)
        except RuntimeError as error:
            notes.append(f"{event_id}: {error}")
            continue
        path.write_bytes(data)
        notes.append(f"{event_id}: stamped" + (f" ({len(failed)} calendar(s) unreachable)" if failed else ""))
    return notes


def upgrade_all(proof_dir: Path) -> list[str]:
    notes = []
    for path in sorted(proof_dir.glob("*.ots")):
        proof = load_proof(path.read_bytes())
        if proof_state(proof)["bitcoin_heights"]:
            continue
        if upgrade_proof(proof):
            path.write_bytes(serialize(proof))
            heights = proof_state(proof)["bitcoin_heights"]
            notes.append(f"{path.stem}: " + (f"in Bitcoin block {heights[0]}" if heights else "updated"))
    return notes


def status(base_dir: str, proof_dir: Path) -> list[dict]:
    rows = []
    for event_id, event in sorted(ledger_events(base_dir).items()):
        path = proof_dir / f"{event_id}.ots"
        row = {"event_id": event_id, "digest": event_digest(event).hex(), "proof": "none"}
        if path.exists():
            proof = load_proof(path.read_bytes())
            if proof.file_digest != event_digest(event):
                row["proof"] = "MISMATCH"
            else:
                state = proof_state(proof)
                row["proof"] = (f"bitcoin block {state['bitcoin_heights'][0]}" if state["bitcoin_heights"]
                                else f"pending at {len(state['pending'])} calendar(s)")
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("stamp", "upgrade", "status"))
    parser.add_argument("--ledgers", type=Path, default=ROOT / "autonomous")
    parser.add_argument("--proofs", type=Path, default=DEFAULT_PROOF_DIR)
    args = parser.parse_args(argv)

    if args.command == "stamp":
        notes = stamp_all(str(args.ledgers), args.proofs)
        print("\n".join(notes) or "every event already has a proof")
    elif args.command == "upgrade":
        notes = upgrade_all(args.proofs)
        print("\n".join(notes) or "no proofs completed yet (Bitcoin confirmation usually takes a few hours)")
    else:
        for row in status(str(args.ledgers), args.proofs):
            print(f"{row['event_id']}  {row['proof']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
