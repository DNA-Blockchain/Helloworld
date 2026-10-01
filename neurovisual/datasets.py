"""Session datasets: every moment of a session recorded for training models later, encrypted on disk.

A session file (.nvds) holds, per real-time step:
  features_raw, features (baseline z-scores), context, neural and scene latents, the evidence /
  inference / generative weights, confidence, signal quality, mode, event, model version, the
  generation request's seed and prompt, and optionally the raw EEG window (include_raw)
plus every rating (with its notes), the stored memories (anchors) and the session's configuration.

Format: a plaintext header (schema, session id, counts, feature names, model fingerprint: nothing
personal) followed by frames, each a chunk of steps as compressed JSON Lines encrypted with
AES-256-GCM under a key kept on this PC (autonomous/neurovisual/dataset.key). The header and frame
number are authenticated with each frame, so frames can't be swapped or edited. Frames are written as
the session runs, so a long session doesn't fill memory, and a crash loses at most one frame.

Size: about 2 KB per step without raw EEG; raw 1-second windows add about 1 KB per channel per step
(16 channels at 250 Hz: about 0.6 GB per hour at 10 Hz).

Exports (export_npz, export_jsonl) are decrypted, plaintext copies for a training job: write them only
where you intend to train, and delete them after.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import struct
import time
import uuid
from pathlib import Path

import numpy as np

MAGIC = b"NVDS1\n"
SCHEMA = "rabbitsoft-neurovisual-dataset.v1"


def _crypto():
    import crypto_layer

    return crypto_layer


def _plain(value):
    if isinstance(value, np.ndarray):
        return [round(float(x), 6) for x in value.ravel()] if value.ndim == 1 else value.round(3).tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


class SessionRecorder:
    def __init__(self, directory: Path, key: bytes, feature_names: list[str], profile: str = "",
                 include_raw: bool = False, frame_steps: int = 300, model_fingerprint: str = ""):
        self.session_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self.path = Path(directory) / f"{self.session_id}.nvds"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.key, self.include_raw, self.frame_steps = key, include_raw, frame_steps
        self.header = {"schema": SCHEMA, "session_id": self.session_id, "created_at": time.time(),
                       "profile": profile, "features": feature_names, "include_raw": include_raw,
                       "model_fingerprint": model_fingerprint}
        header_bytes = json.dumps(self.header, sort_keys=True).encode("utf-8")
        self._aad = hashlib.sha256(header_bytes).digest()
        with self.path.open("wb") as f:
            f.write(MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes)
        self._pending: list[dict] = []
        self.frames = self.steps = self.ratings = 0
        self.closed = False

    # -- recording ---------------------------------------------------------------------------------------
    def record_step(self, state, features_raw, features, quality: float, request=None, window=None) -> None:
        row = {"type": "step", "index": self.steps, "t": state.timestamp, "mode": state.mode,
               "event_id": state.event_id, "model_version": state.model_version,
               "features_raw": _plain(features_raw), "features": _plain(features), "context": _plain(state.context),
               "neural": _plain(state.neural), "scene": _plain(state.scene),
               "weights": [state.evidence_weight, state.inference_weight, state.generative_weight],
               "confidence": round(state.confidence, 6), "quality": round(float(quality), 6)}
        if request is not None:
            row["request"] = {"seed": request.seed, "prompt": request.prompt, "guidance": request.guidance,
                              "strength": request.strength}
        if self.include_raw and window is not None:
            row["raw"] = {"sample_rate": window.sample_rate, "data": np.asarray(window.data, dtype=np.float32).round(2).tolist()}
        self.steps += 1
        self._add(row)

    def record_rating(self, rating: float, notes: str = "", step: int | None = None) -> None:
        self.ratings += 1
        self._add({"type": "rating", "step": self.steps - 1 if step is None else step, "rating": float(rating),
                   "notes": notes, "t": time.time()})

    def record_anchor(self, event_id: str, description: str, context: dict) -> None:
        self._add({"type": "anchor", "event_id": event_id, "description": description, "context": context})

    def record_generation(self, result: dict) -> None:
        self._add({"type": "generation", **{k: v for k, v in result.items() if k in ("status", "path", "sha256", "prompt_id", "error")}})

    def _add(self, row: dict) -> None:
        if self.closed:
            raise ValueError("this session has been closed")
        self._pending.append(row)
        if sum(r["type"] == "step" for r in self._pending) >= self.frame_steps:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        body = gzip.compress("\n".join(json.dumps(r, separators=(",", ":")) for r in self._pending).encode("utf-8"))
        payload = _crypto().aead_encrypt(self.key, body, aad=self._aad + struct.pack(">I", self.frames))
        with self.path.open("ab") as f:
            f.write(struct.pack(">I", len(payload)) + payload)
        self.frames += 1
        self._pending = []

    def close(self) -> dict:
        """Writes what's left and returns the session summary (counts and the file's SHA-256)."""
        if not self.closed:
            self.flush()
            self.closed = True
        return {"session_id": self.session_id, "path": str(self.path), "steps": self.steps,
                "ratings": self.ratings, "frames": self.frames,
                "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest()}


# -- reading and exporting ---------------------------------------------------------------------------------
def read_session(path: Path, key: bytes) -> tuple[dict, list[dict]]:
    """(header, rows). Raises ValueError if the file was altered or the key is wrong."""
    data = Path(path).read_bytes()
    if not data.startswith(MAGIC):
        raise ValueError(f"{path} isn't a neurovisual session file")
    offset = len(MAGIC)
    (length,) = struct.unpack(">I", data[offset:offset + 4])
    header_bytes = data[offset + 4:offset + 4 + length]
    header, offset = json.loads(header_bytes), offset + 4 + length
    aad, rows, frame = hashlib.sha256(header_bytes).digest(), [], 0
    while offset < len(data):
        (size,) = struct.unpack(">I", data[offset:offset + 4])
        try:
            body = _crypto().aead_decrypt(key, data[offset + 4:offset + 4 + size], aad=aad + struct.pack(">I", frame))
        except Exception as error:
            raise ValueError(f"{path}: frame {frame} can't be decrypted (altered, or a different key)") from error
        rows += [json.loads(line) for line in gzip.decompress(body).decode("utf-8").splitlines() if line]
        offset, frame = offset + 4 + size, frame + 1
    return header, rows


def training_records(rows: list[dict]) -> list[dict]:
    """Rated steps as records a predictor's trained() accepts: context, neural, rating."""
    steps = {r["index"]: r for r in rows if r["type"] == "step"}
    return [{"context": np.asarray(steps[r["step"]]["context"]), "neural": np.asarray(steps[r["step"]]["neural"]),
             "rating": r["rating"]} for r in rows if r["type"] == "rating" and r["step"] in steps]


def train_from_sessions(predictor, paths: list[Path], key: bytes):
    """Trains any predictor that has trained() on the ratings in recorded sessions."""
    records = [rec for p in paths for rec in training_records(read_session(p, key)[1])]
    if not records:
        raise ValueError("the sessions hold no ratings to train on")
    if not hasattr(predictor, "trained"):
        raise TypeError(f"{type(predictor).__name__} can't be trained here (no trained() method)")
    return predictor.trained(records)


def export_npz(paths: list[Path], key: bytes, out: Path) -> dict:
    """Arrays for any framework: per step features, context, neural, scene, weights, confidence,
    quality, mode (0 memory, 1 imagination), session index; ratings as (step row, rating)."""
    columns = {k: [] for k in ("features", "context", "neural", "scene", "weights", "confidence", "quality", "mode", "session")}
    rated_rows, ratings, offset = [], [], 0
    for n, p in enumerate(paths):
        _, rows = read_session(p, key)
        steps = [r for r in rows if r["type"] == "step"]
        for r in steps:
            for k in ("features", "context", "neural", "scene", "weights", "confidence", "quality"):
                columns[k].append(r[k])
            columns["mode"].append(0 if r["mode"] == "memory" else 1)
            columns["session"].append(n)
        for r in rows:
            if r["type"] == "rating" and 0 <= r["step"] < len(steps):
                rated_rows.append(offset + r["step"])
                ratings.append(r["rating"])
        offset += len(steps)
    arrays = {k: np.asarray(v, dtype=float if k not in ("mode", "session") else int) for k, v in columns.items()}
    arrays.update(rated_rows=np.asarray(rated_rows, dtype=int), ratings=np.asarray(ratings, dtype=float))
    np.savez_compressed(out, **arrays)
    return {"path": str(out), "steps": offset, "ratings": len(ratings)}


def export_jsonl(paths: list[Path], key: bytes, out: Path) -> dict:
    """Every row of every session as JSON Lines (loads directly with Hugging Face datasets or pandas)."""
    count = 0
    with Path(out).open("w", encoding="utf-8") as f:
        for p in paths:
            header, rows = read_session(p, key)
            for r in rows:
                f.write(json.dumps({"session_id": header["session_id"], **r}, separators=(",", ":")) + "\n")
                count += 1
    return {"path": str(out), "rows": count}
