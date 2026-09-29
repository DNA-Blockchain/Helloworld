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
run_node_cli.py — run ONE real network node, for real cross-machine use.

Where run_consolidated_network.py runs 3 nodes in one process on
127.0.0.1 (a local test), this runs a single node that can bind to a real
network interface and connect out to peers on OTHER machines' real IPs.

Setup, once per node:
    python run_node_cli.py --id 0 --show-key
prints this node's Ed25519 public signing key (creating the key file under
--workdir if needed). Give each node every other node's key via --trust.

Run (machine A, 192.168.1.10):
    python run_node_cli.py --id 0 --port 9601 --bind 0.0.0.0 \\
        --peers 192.168.1.20:9601,192.168.1.21:9601 \\
        --trust 1=<node-1 key> --trust 2=<node-2 key>

and likewise on the other machines with their own --id and the other
nodes' addresses/keys. Every node must share the same --identity-text (or
the identity check will correctly fail — that means they're not the same
network).

Trust model: by default only peers whose keys were given with --trust (or
pinned on an earlier run, saved in <workdir>/keys/) are accepted. --tofu
instead pins whatever key a new node_id first presents, which is fine for a
quick test on a trusted LAN but lets anyone who reaches the port first claim
an unused node_id. A pinned key that later changes is always rejected.

Honest limitation: --bind 0.0.0.0 makes the port reachable from your whole
network (or the internet, if forwarded). Signatures and pinning stop
unknown nodes from getting blocks accepted, but anyone can still connect and
attempt a handshake. For anything beyond a trusted LAN, add a firewall rule
restricting the port to known peer IPs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from collections.abc import Callable

from network_node import NetworkNode
from research_provenance import ResearchProvenanceQueue
from digital_dna import DigitalDNA
from token_ledger import TokenLedger
from dna_binary_codec import encode_to_dna
from run_consolidated_network import research_enricher, external_info_enricher
from work_sharing import WorkManager, WorkSchedule
from atomic_io import replace_with_retry
import live_store

DEFAULT_IDENTITY_TEXT = "dna-chain-project default network"


def parse_peers(peers_str: str) -> list[tuple[str, int]]:
    """'host:port,host:port' -> [(host, port), ...]. IPv6 hosts go in
    brackets: [::1]:9601."""
    result = []
    for entry in (peers_str or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        host, sep, port_str = entry.rpartition(":")
        if not sep or not host:
            raise ValueError(f"peer '{entry}' is not host:port")
        host = host[1:-1] if host.startswith("[") and host.endswith("]") else host
        port = int(port_str) if port_str.isdigit() else 0
        if not 1 <= port <= 65535:
            raise ValueError(f"peer '{entry}' has an invalid port")
        result.append((host, port))
    return result


def parse_trust(entries: list[str]) -> dict[int, str]:
    """['1=<64 hex>', '2=<64 hex>,3=<64 hex>', ...] -> {1: '<64 hex>', ...}
    (each --trust may also hold a comma-separated list)"""
    result = {}
    for entry in (e.strip() for group in entries or [] for e in group.split(",")):
        if not entry:
            continue
        node_str, sep, key_hex = entry.partition("=")
        if not sep:
            raise ValueError(f"--trust '{entry}' is not ID=KEY")
        key_hex = key_hex.strip().lower()
        if len(key_hex) != 64 or any(c not in "0123456789abcdef" for c in key_hex):
            raise ValueError(f"--trust '{entry}': key must be 64 hex characters")
        result[int(node_str)] = key_hex
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run one real dna-chain-project network node.")
    p.add_argument("--id", type=int, required=True, help="this node's integer id")
    p.add_argument("--port", type=int, default=9601, help="port this node listens on")
    p.add_argument("--bind", default="127.0.0.1",
                   help="interface to bind (127.0.0.1 for local-only, 0.0.0.0 for LAN/real network)")
    p.add_argument("--peers", default="", help="comma-separated host:port list of OTHER nodes")
    p.add_argument("--trust", action="append", default=[], metavar="ID=KEY",
                   help="pin another node's Ed25519 public key (repeatable, or comma-separated); see --show-key")
    p.add_argument("--tofu", action="store_true",
                   help="also accept (and pin) nodes on first contact without --trust")
    p.add_argument("--show-key", action="store_true", help="print this node's public signing key and exit")
    p.add_argument("--identity-text", default=DEFAULT_IDENTITY_TEXT,
                   help="text every node in this network must share identically")
    p.add_argument("--mine-interval", type=float, default=1.5)
    p.add_argument("--duration", type=float, default=0.0, help="seconds to run, 0 = run until Ctrl+C")
    p.add_argument(
        "--allow-research-gossip", action="store_true",
        help="opt in to adding a hash of a public ClinicalTrials.gov record to peer blocks",
    )
    p.add_argument(
        "--no-research", action="store_true",
        help="compatibility option; research-result gossip is already off by default",
    )
    p.add_argument(
        "--allow-external-info", action="store_true",
        help="opt in to adding Bitcoin/Ethereum market snapshots to peer blocks",
    )
    p.add_argument(
        "--no-external-info", action="store_true",
        help="compatibility option; external-info sharing is off by default",
    )
    p.add_argument(
        "--provenance-queue", type=str,
        help="publish queued public research hashes/provenance only; incompatible with enrichers",
    )
    p.add_argument("--workdir", default="./node_data", help="where this node's keys/chain/identity/token files live")
    p.add_argument("--work-sharing", action="store_true",
                   help="split research/chain-tip lookups and chain audits with the other nodes "
                        "(replaces the per-block research/external enrichers)")
    p.add_argument("--round-seconds", type=float, default=300.0, help="work-sharing round length")
    p.add_argument("--takeover-seconds", type=float, default=20.0,
                   help="how long each next-in-line node waits before taking over a job")
    p.add_argument("--status-file", help="write this node's status JSON here every 30s and on exit")
    p.add_argument("--stop-file", help="stop cleanly when this file appears (used by node_supervisor.py)")
    p.add_argument("--live-db", default=os.environ.get(live_store.ENV_VAR),
                   help=f"also mirror chain/ledger/DNA/status into this live_store.py SQLite file "
                        f"(default: ${live_store.ENV_VAR}; off when unset)")
    return p


def build_enrichers(args: argparse.Namespace) -> list[Callable]:
    """Build block enrichers, keeping research-result gossip opt-in."""
    enrichers = []
    if args.allow_research_gossip:
        enrichers.append(research_enricher)
    if args.allow_external_info and not args.no_external_info:
        enrichers.append(external_info_enricher)
    return enrichers


def write_status(node, path: str) -> None:
    status = node.status()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)
    replace_with_retry(tmp, path)
    live_store.snapshot("status", node.node_key, status)


async def watch(node, stop_event: asyncio.Event, status_file: str | None, stop_file: str | None) -> None:
    """Writes the status file every 30s and stops the node when the stop
    file appears."""
    last_status = 0.0
    while not stop_event.is_set():
        if stop_file and os.path.exists(stop_file):
            node.log("stop file found, stopping")
            stop_event.set()
            break
        if status_file and time.time() - last_status >= 30:
            try:
                write_status(node, status_file)
            except OSError as e:
                node.log(f"could not write status file: {e}")
            last_status = time.time()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


async def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 0 <= args.id < 2 ** 32:
        parser.error("--id must be between 0 and 4294967295")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        peers = parse_peers(args.peers)
        trusted = parse_trust(args.trust)
    except ValueError as e:
        parser.error(str(e))
    if args.allow_research_gossip and args.no_research:
        parser.error("--allow-research-gossip and --no-research cannot be used together")
    # Provenance blocks are mined without enrichers; work sharing runs in its
    # own background loop and its blocks carry only work items, so the two
    # can share a node. Live enrichers would mix other data into blocks.
    if args.provenance_queue and (args.allow_research_gossip or args.allow_external_info):
        parser.error("--provenance-queue cannot be combined with live enrichers")

    os.makedirs(args.workdir, exist_ok=True)
    if args.live_db:
        try:
            live_store.enable(args.live_db)
        except Exception as e:   # optional mirror; the node runs on its JSON files regardless
            print(f"[live_store] disabled: {e}")
    keys_dir = os.path.join(args.workdir, "keys")
    passphrase = os.environ.get("DNA_NODE_KEY_PASSPHRASE", "").encode() or None

    identity_strand = encode_to_dna(hashlib.sha256(args.identity_text.encode("utf-8")).digest())
    dna = DigitalDNA(seed_label=f"node-{args.id}",
                     dna_path=os.path.join(args.workdir, f"identity_node-{args.id}.dna.json"))
    ledger = TokenLedger(store_path=os.path.join(args.workdir, f"tokens_node-{args.id}.json"))

    enrichers = [] if args.work_sharing or args.provenance_queue else build_enrichers(args)

    try:
        node = NetworkNode(
            node_id=args.id,
            port=args.port,
            peer_ports=None,
            peers=peers,
            bind_host=args.bind,
            dna=dna,
            identity_strand=identity_strand,
            ledger=ledger,
            chain_dir=args.workdir,
            mine_interval=args.mine_interval,
            enrichers=enrichers,
            require_known_peers=not args.tofu,
            signing_key_path=os.path.join(keys_dir, f"node-{args.id}.ed25519.pem"),
            signing_key_passphrase=passphrase,
            known_peers_path=os.path.join(keys_dir, f"node-{args.id}.known_peers.json"),
            provenance_queue=(
                ResearchProvenanceQueue(args.provenance_queue)
                if args.provenance_queue else None
            ),
        )
        for peer_id, key_hex in trusted.items():
            node.trust_peer(peer_id, key_hex)
    except ValueError as e:
        print(f"REFUSING TO START: {e}")
        print(f"If a peer's key change is intended, remove its entry from "
              f"{os.path.join(keys_dir, f'node-{args.id}.known_peers.json')}.")
        return 1

    if args.show_key:
        print(f"node-{args.id} public signing key: {node.signing_pub_hex}")
        print(f"Other nodes trust it with:  --trust {args.id}={node.signing_pub_hex}")
        return 0

    if args.work_sharing:
        WorkManager(node, WorkSchedule(
            round_seconds=args.round_seconds,
            research_every=3 if args.allow_research_gossip else 0,
            external_every=2 if args.allow_external_info and not args.no_external_info else 0,
        ), takeover_seconds=args.takeover_seconds).attach()

    print("=" * 78)
    print(f"REAL NETWORK NODE  id={args.id}  bind={args.bind}:{args.port}")
    print(f"This node's public signing key: {node.signing_pub_hex}")
    print(f"Peers: {peers if peers else '(none — will just mine its own local chain)'}")
    if args.provenance_queue:
        print("Chain payload mode: hashes and source/timestamp provenance only; no record content.")
        print(f"Research provenance outbox: {args.provenance_queue}")
    print(f"Pinned peer keys: {sorted(node.peer_signing_keys) or '(none)'}"
          f"{'  [+ trust on first use]' if args.tofu else ''}")
    print(f"Identity strand (must match every peer's): {identity_strand}")
    if args.bind not in ("127.0.0.1", "localhost", "::1"):
        print(f"NOTE: listening on {args.bind} — reachable from other machines. "
              f"Restrict port {args.port} to your peers' IPs with a firewall rule.")
        if args.tofu:
            print("WARNING: --tofu on a network interface lets whoever connects first claim an unused node id.")
    if peers and not node.peer_signing_keys and not args.tofu:
        print("WARNING: no peer keys pinned and --tofu is off, so every peer will be rejected. "
              "Pass --trust ID=KEY for each peer.")
    print("=" * 78)

    stop_event = asyncio.Event()
    run_task = asyncio.create_task(node.run(stop_event))
    watcher = asyncio.create_task(watch(node, stop_event, args.status_file, args.stop_file))
    try:
        if args.duration > 0:
            await asyncio.sleep(args.duration)
        else:
            # shield: Ctrl+C cancels main(), not the node, so the finally
            # below can stop it cleanly (server closed, chain saved)
            await asyncio.shield(run_task)
    except asyncio.CancelledError:
        pass
    finally:
        stop_event.set()
        if not run_task.done():
            await run_task
        await watcher
        if args.status_file:
            write_status(node, args.status_file)

    ok, msg = node.chain.verify_chain()
    print("\n" + "=" * 78)
    print(f"node-{args.id} stopped. mined={node.block_counter} received={node.blocks_received}")
    print(f"chain verify: {msg} ({'OK' if ok else 'FAILED'})")
    # Tokens are awarded to a block's ORIGIN by whichever peer verifies it,
    # so this node's ledger tracks what IT awarded to others, never its own
    # balance; a network-wide balance would need peers to gossip ledger
    # updates, which isn't implemented.
    awarded = {f"node-{pid}": ledger.balance(f"node-{pid}") for pid in sorted(node.peer_signing_keys)}
    print(f"tokens THIS node awarded to peers (local view only): {awarded}")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(0)
