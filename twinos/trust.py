"""Which peers this agent trusts: their Ed25519 keys, pinned by the owner.

Discovery (IDENTITY_REQUEST) is open, so a new peer can learn this agent's id and key. Everything else
needs the sender to be pinned here, with the same key it signs with. Pinning is the owner's decision
(python -m twinos trust); a key is never pinned automatically, because trusting the first key seen would
let whoever answers first become that peer.

Stored in autonomous/twinos/peers.json: {agent_id: {"public_key", "name", "agent_type", "pinned_at"}}.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from atomic_io import replace_with_retry

from .identity import agent_id_for
from .locking import locked


class TrustStore:
    def __init__(self, path: Path):
        self.path = path

    @property
    def peers(self) -> dict[str, dict]:
        """Read from the file each time, so a running server sees a peer the owner has just pinned."""
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def pin(self, agent_id: str, public_key: str, name: str = "", agent_type: str = "generic_agent") -> dict:
        try:
            derived = agent_id_for(public_key)
        except ValueError as error:
            raise ValueError("the key must be the peer's Ed25519 public key in hex (64 characters)") from error
        if len(public_key) != 64 or derived != agent_id:
            raise ValueError(f"that key belongs to {derived}, not {agent_id}")
        entry = {"public_key": public_key, "name": name, "agent_type": agent_type, "pinned_at": time.time()}
        with locked(self.path):
            peers = self.peers
            peers[agent_id] = entry
            self._save(peers)
        return entry

    def unpin(self, agent_id: str) -> bool:
        with locked(self.path):
            peers = self.peers
            removed = peers.pop(agent_id, None) is not None
            if removed:
                self._save(peers)
        return removed

    def is_trusted(self, agent_id: str, public_key: str) -> bool:
        peer = self.peers.get(agent_id)
        return peer is not None and peer["public_key"] == public_key

    def _save(self, peers: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(peers, indent=2), encoding="utf-8")
        replace_with_retry(str(temporary), str(self.path))
