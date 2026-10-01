"""A local, append-only provenance ledger for the prototype's data, models and compute.

Each entry links to the previous one by hash, so any edit breaks verification from that point on.
Entries hold fingerprints and metrics, never raw EEG, physiology, notes or memories:

  data_digest     HMAC-SHA-256 of the training records under a key kept on this PC. A plain hash of
                  personal data can be confirmed by anyone who guesses the content; a keyed one can't.
  model_sha256    the model fingerprint (weights and version)
  config_sha256   SHA-256 of the configuration
  metrics         counts, durations and objective values

The ledger is a JSON Lines file under autonomous/ (gitignored), and it stays on this PC. It is
separate from the shared research chain, which is public and permanent; nothing here is published.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path


def stable_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256(value) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def keyed_digest(key: bytes, value) -> str:
    return hmac.new(key, stable_json(value).encode("utf-8"), hashlib.sha256).hexdigest()


def load_or_create_key(path: Path) -> bytes:
    """The ledger's 32-byte key, created on first use and kept beside the ledger."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = os.urandom(32)
        path.write_bytes(key)
        return key


class ProvenanceLedger:
    FIELDS = ("index", "timestamp", "kind", "data_digest", "model_sha256", "config_sha256", "metrics", "previous")

    def __init__(self, key: bytes, path: Path | None = None):
        self.key, self.path = key, path
        self.entries: list[dict] = []
        if path and path.exists():
            self.entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        if not self.entries:
            self.append("genesis", data=None, model_sha256="", config={"ledger": "neurovisual", "version": 1}, metrics={})

    @staticmethod
    def entry_hash(entry: dict) -> str:
        return sha256({k: entry[k] for k in ProvenanceLedger.FIELDS})

    def append(self, kind: str, data, model_sha256: str, config: dict, metrics: dict) -> dict:
        entry = {"index": len(self.entries), "timestamp": time.time(), "kind": kind,
                 "data_digest": keyed_digest(self.key, data), "model_sha256": model_sha256,
                 "config_sha256": sha256(config), "metrics": metrics,
                 "previous": self.entries[-1]["hash"] if self.entries else "0" * 64}
        entry["hash"] = self.entry_hash(entry)
        self.entries.append(entry)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(stable_json(entry) + "\n")
        return entry

    def verify(self) -> tuple[bool, list[str]]:
        problems = []
        for i, entry in enumerate(self.entries):
            if entry.get("index") != i:
                problems.append(f"entry {i}: index is {entry.get('index')}")
            if self.entry_hash(entry) != entry.get("hash"):
                problems.append(f"entry {i}: contents don't match its hash")
            expected = self.entries[i - 1]["hash"] if i else "0" * 64
            if entry.get("previous") != expected:
                problems.append(f"entry {i}: doesn't link to entry {i - 1}")
        return not problems, problems
