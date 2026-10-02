"""This agent's identity: a persistent Ed25519 key, and the agent id derived from it.

The agent id is "agent-" plus the first 24 hex digits of the SHA-256 of the raw public key, so an id
can't be claimed without the matching key: a receiver recomputes it from the key carried in the message.
The private key is a PKCS#8 PEM file under autonomous/twinos/ (crypto_layer.load_or_create_signing_keypair);
identity.json beside it holds only the name and type.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import crypto_layer

AGENT_TYPES = ("digital_twin", "coding_agent", "terminal_agent", "development_agent", "automation_agent",
               "micropython_agent", "gpu_agent", "os_agent", "generic_agent")


def agent_id_for(public_key_hex: str) -> str:
    return "agent-" + hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()[:24]


class AgentIdentity:
    def __init__(self, home: Path, name: str = "Personal Digital Twin", agent_type: str = "digital_twin"):
        if agent_type not in AGENT_TYPES:
            raise ValueError(f"agent types are {', '.join(AGENT_TYPES)}; not {agent_type!r}")
        home.mkdir(parents=True, exist_ok=True)
        self._private, public = crypto_layer.load_or_create_signing_keypair(str(home / "identity.pem"))
        self.public_key = public.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.agent_id = agent_id_for(self.public_key)
        info_path = home / "identity.json"
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {"name": name, "agent_type": agent_type}
            info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
        self.name, self.agent_type = info.get("name", name), info.get("agent_type", agent_type)

    def sign(self, data: bytes) -> str:
        return crypto_layer.sign(self._private, data).hex()
