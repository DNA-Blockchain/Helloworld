"""The temporal predictor: a feature sequence -> a visual latent state, in memory or imagination mode.

Prediction
  The sequence is summarized as an exponentially weighted context (newest weight 1, each older step
  times `decay`), so the state depends on the trajectory, not one sample. A linear map and tanh give
  the neural component. The latent is a mix of three sources, each with an explicit weight:

    evidence    a stored historical anchor for the chosen event (only if one exists)
    inference   the neural component from the person's signals
    generative  seeded noise: detail the system makes up

  Memory mode favours evidence; imagination mode allows more generation. Without an anchor, evidence
  is 0, whatever the mode: the system can't recall what it never stored. Confidence is computed from
  the mix (evidence 1.0, inference 0.6, generative 0.2) times signal quality and baseline readiness.

Learning
  Feedback is a rating in [-1, 1] of a shown state. A learning burst does reward-weighted gradient
  ascent on  rating * <tanh(W c), shown>  for a fixed number of epochs: outputs rated positive are
  reinforced and ones rated negative suppressed. It learns only what the ratings say, nothing more.
  Training works on a copy, so the live model keeps serving until the new one is swapped in.
"""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from enum import Enum

import numpy as np

LATENT_SIZE = 64
SOURCE_CONFIDENCE = {"evidence": 1.0, "inference": 0.6, "generative": 0.2}
MIX = {  # (mode, has anchor) -> evidence, inference, generative
    ("memory", True): (0.70, 0.25, 0.05), ("memory", False): (0.0, 0.75, 0.25),
    ("imagination", True): (0.25, 0.35, 0.40), ("imagination", False): (0.0, 0.50, 0.50),
}


class VisualMode(Enum):
    MEMORY = "memory"
    IMAGINATION = "imagination"


@dataclass
class VisualLatentState:
    timestamp: float
    mode: str
    event_id: str | None
    scene: np.ndarray                 # LATENT_SIZE values in [-1, 1]
    neural: np.ndarray                # the inference component alone (what feedback trains)
    context: np.ndarray               # the sequence summary it came from
    evidence_weight: float
    inference_weight: float
    generative_weight: float
    confidence: float
    model_version: str

    # Named slices for a generator: what the scene looks like, and how it's framed and lit.
    camera = property(lambda self: self.scene[0:8])
    motion = property(lambda self: self.scene[8:16])
    depth = property(lambda self: self.scene[16:24])
    lighting = property(lambda self: self.scene[24:32])
    continuity = property(lambda self: self.scene[32:40])

    def summary(self) -> dict:
        return {"mode": self.mode, "event_id": self.event_id, "model_version": self.model_version,
                "confidence": round(self.confidence, 3), "evidence": self.evidence_weight,
                "inference": self.inference_weight, "generative": self.generative_weight}


def compose(neural: np.ndarray, context: np.ndarray, mode: VisualMode, anchor: np.ndarray | None, quality: float,
            timestamp: float, event_id: str | None, model_version: str, rng: np.random.Generator) -> VisualLatentState:
    """A model's neural output, mixed with the stored anchor and generated detail by mode, with the
    confidence that mix earns. Any predictor can use it so evidence is accounted for the same way."""
    neural = np.asarray(neural, dtype=float)
    if neural.shape != (LATENT_SIZE,):
        raise ValueError(f"a predictor's neural output has {LATENT_SIZE} values, not shape {neural.shape}")
    evidence, inference, generative = MIX[(mode.value, anchor is not None)]
    scene = inference * neural + generative * np.tanh(rng.normal(size=LATENT_SIZE))
    if anchor is not None:
        scene = scene + evidence * anchor
    confidence = (evidence * SOURCE_CONFIDENCE["evidence"] + inference * SOURCE_CONFIDENCE["inference"]
                  + generative * SOURCE_CONFIDENCE["generative"]) * quality
    return VisualLatentState(timestamp=timestamp, mode=mode.value, event_id=event_id, scene=np.clip(scene, -1, 1),
                             neural=neural, context=context, evidence_weight=evidence, inference_weight=inference,
                             generative_weight=generative, confidence=float(confidence), model_version=model_version)


def anchor_embedding(description: str) -> np.ndarray:
    """A deterministic unit vector for a described event. A placeholder for a real visual embedding
    (from the person's own photos or video, kept off-chain); same description, same vector."""
    seed = int.from_bytes(hashlib.sha256(description.encode("utf-8")).digest()[:8], "big")
    v = np.random.default_rng(seed).normal(size=LATENT_SIZE)
    return np.tanh(v / np.linalg.norm(v) * 4)


class TemporalPredictor:
    def __init__(self, feature_dim: int, seed: int = 0, decay: float = 0.8):
        self.rng = np.random.default_rng(seed)
        self.W = self.rng.normal(0, 1 / np.sqrt(feature_dim), size=(LATENT_SIZE, feature_dim))
        self.decay = decay
        self.version = (1, 0, 0)

    @property
    def version_text(self) -> str:
        return ".".join(map(str, self.version))

    def context(self, sequence: list[np.ndarray]) -> np.ndarray:
        if not sequence:
            raise ValueError("the predictor needs at least one feature vector")
        weights = self.decay ** np.arange(len(sequence))[::-1]
        return (weights[:, None] * np.asarray(sequence)).sum(axis=0) / weights.sum()

    def predict(self, sequence: list[np.ndarray], mode: VisualMode, anchor: np.ndarray | None,
                quality: float, timestamp: float, event_id: str | None = None) -> VisualLatentState:
        ctx = self.context(sequence)
        return compose(np.tanh(self.W @ ctx), ctx, mode, anchor, quality, timestamp, event_id,
                       self.version_text, self.rng)

    def objective(self, records: list[dict]) -> float:
        """Mean rating-weighted agreement with the rated outputs (higher is better)."""
        if not records:
            return 0.0
        return float(np.mean([r["rating"] * np.dot(np.tanh(self.W @ r["context"]), r["neural"]) / LATENT_SIZE
                              for r in records]))

    def trained(self, records: list[dict], epochs: int = 25, learning_rate: float = 0.5) -> tuple[
            "TemporalPredictor", dict]:
        """A new predictor trained on the rated records, and the burst's metrics. This one is unchanged."""
        model = copy.deepcopy(self)
        before = model.objective(records)
        for _ in range(epochs):
            gradient = np.zeros_like(model.W)
            for r in records:
                out = np.tanh(model.W @ r["context"])
                gradient += np.outer(r["rating"] * r["neural"] * (1 - out ** 2), r["context"])
            model.W += learning_rate * gradient / (len(records) * LATENT_SIZE)
        major, minor, patch = model.version
        model.version = (major, minor + 1, patch)
        return model, {"records": len(records), "epochs": epochs, "learning_rate": learning_rate,
                       "objective_before": round(before, 6), "objective_after": round(model.objective(records), 6),
                       "old_version": self.version_text, "new_version": model.version_text}

    def save(self, path) -> None:
        """A checkpoint (.npz): weights, version and decay."""
        with open(path, "wb") as f:
            np.savez(f, W=self.W, version=np.asarray(self.version), decay=np.asarray(self.decay))

    @classmethod
    def load(cls, path) -> "TemporalPredictor":
        with np.load(path) as data:
            model = cls(data["W"].shape[1], decay=float(data["decay"]))
            model.W = data["W"].copy()
            model.version = tuple(int(x) for x in data["version"])
        return model

    def fingerprint(self) -> str:
        """SHA-256 of the weights and version: identifies exactly which model produced an output."""
        digest = hashlib.sha256(self.version_text.encode())
        digest.update(np.ascontiguousarray(self.W, dtype="<f8").tobytes())
        return digest.hexdigest()
