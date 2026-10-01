"""A local, append-only provenance ledger for the prototype's data, models and compute.

Each entry links to the previous one by hash, so any edit breaks verification from that point on.
Entries hold fingerprints and metrics, never raw EEG, physiology, notes or memories:

  data_digest     HMAC-SHA-256 of the training records under a key kept on this PC. A plain hash of
                  personal data can be confirmed by anyone who guesses the content; a keyed one can't.
  model_sha256    the model fingerprint (weights and version)
  config_sha256   SHA-256 of the configuration
  metrics         counts, durations, compute (device, GPU or CPU, throughput) and objective values
  links           the earlier blocks it derives from: training runs link their dataset and parent
                  model, a model version links its training runs, so lineage() traces any model back

Block kinds: genesis, dataset (a versioned collection of sessions), training_set (the hash of the
exact training data per mode), training_run (memory, imagination or all; with compute), model_version
(a released checkpoint), learning_burst (live) and dataset_recorded (one session).

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
        fields = ProvenanceLedger.FIELDS + tuple(k for k in ("links",) if k in entry)
        return sha256({k: entry[k] for k in fields})

    def append(self, kind: str, data, model_sha256: str, config: dict, metrics: dict,
               links: list[str] | None = None) -> dict:
        """Adds a block. `links` are the hashes of earlier blocks this one derives from (the dataset a
        training run used, the runs a model version came from), so lineage can be traced."""
        known = {e["hash"] for e in self.entries}
        if links and not set(links) <= known:
            raise ValueError("a block can only link to blocks already in the ledger")
        entry = {"index": len(self.entries), "timestamp": time.time(), "kind": kind,
                 "data_digest": keyed_digest(self.key, data), "model_sha256": model_sha256,
                 "config_sha256": sha256(config), "metrics": metrics,
                 "previous": self.entries[-1]["hash"] if self.entries else "0" * 64}
        if links:
            entry["links"] = list(links)
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
            earlier = {e.get("hash") for e in self.entries[:i]}
            if any(link not in earlier for link in entry.get("links", [])):
                problems.append(f"entry {i}: links to a block that isn't before it")
        return not problems, problems

    # -- lineage -----------------------------------------------------------------------------------------
    def by_hash(self, entry_hash: str) -> dict | None:
        return next((e for e in self.entries if e["hash"] == entry_hash), None)

    def latest(self, kind: str, **match) -> dict | None:
        for entry in reversed(self.entries):
            if entry["kind"] == kind and all(entry["metrics"].get(k) == v for k, v in match.items()):
                return entry
        return None

    def lineage(self, entry_hash: str) -> list[dict]:
        """The block and everything it derives from, through its links, newest first."""
        seen, order, stack = set(), [], [entry_hash]
        while stack:
            current = self.by_hash(stack.pop())
            if current is None or current["hash"] in seen:
                continue
            seen.add(current["hash"])
            order.append(current)
            stack.extend(current.get("links", []))
        return sorted(order, key=lambda e: -e["index"])

    def describe(self, entry: dict) -> str:
        m, kind = entry["metrics"], entry["kind"]
        if kind == "dataset":
            return (f"Dataset {m['name']} v{m['version']}: {m['sessions']} sessions, {m['steps']} steps, "
                    f"{m['ratings']} ratings{', raw EEG' if m.get('raw_eeg') else ''}")
        if kind == "training_set":
            return f"Training-set hash ({m['mode']}): {m['records']} records, sha256 {m['sha256'][:16]}…"
        if kind == "training_run":
            c = m.get("compute", {})
            device = f"GPU {c['gpu']}" if c.get("gpu") else f"CPU {c.get('cpu', '?')}"
            return (f"{m['mode'].capitalize()}-model training: {m['predictor']} on {m['records']} ratings, "
                    f"{m.get('epochs')} epochs, {device}, {c.get('seconds')} s, "
                    f"objective {m.get('objective_before')} -> {m.get('objective_after')}")
        if kind == "model_version":
            return f"Model v{m['version']} ({m['predictor']}), fingerprint {entry['model_sha256'][:16]}…"
        if kind == "learning_burst":
            return f"Live learning burst: {m.get('records')} ratings, model {m.get('old_version')} -> {m.get('new_version')}"
        if kind == "dataset_recorded":
            return f"Session recorded: {m.get('steps')} steps, {m.get('ratings')} ratings"
        return kind.capitalize()

    def render(self) -> list[str]:
        """The chain as blocks, oldest first, each linked to the one before it."""
        lines = []
        for entry in self.entries:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry["timestamp"]))
            links = entry.get("links")
            source = ""
            if links:
                source = f"  (from block{'s' if len(links) > 1 else ''} " + ", ".join(
                    str(self.by_hash(h)["index"]) for h in links) + ")"
            if lines:
                lines.append("    ↓")
            lines.append(f"Block {entry['index']}  {self.describe(entry)}{source}")
            lines.append(f"         {stamp}  hash {entry['hash'][:16]}…  previous {entry['previous'][:16]}…")
        ok, problems = self.verify()
        lines.append(f"Chain {'verified' if ok else 'BROKEN: ' + '; '.join(problems)} ({len(self.entries)} blocks)")
        return lines
