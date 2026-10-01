"""The real-time system: sensors -> features -> baseline -> fusion -> prediction -> generator, with
feedback and learning bursts that never block the real-time loop.

Two compute modes:
  real time   every cycle reads a window, updates the baseline, predicts, conditions a generation
              request, and hands it to the generator (or the background renderer); no training
  burst       when feedback has accumulated and the interval has passed, training runs on a copy of the
              model in a background thread; the trained model is swapped in atomically and recorded in
              the provenance ledger

Every slot is open (interfaces.py): the sensors, the predictor (any model with predict/fingerprint,
trainable if it has trained()), the generator (any existing image/video generator via generators.py),
the dataset recorder and the live stream.

Raw signals, notes and memories live in bounded in-memory buffers, and on disk only inside the
encrypted session dataset when recording is on. The provenance ledger holds fingerprints and metrics.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .conditioning import condition
from .generators import PlaceholderGenerator
from .interfaces import Predictor, check
from .model import LATENT_SIZE, TemporalPredictor, VisualLatentState, VisualMode, anchor_embedding
from .provenance import ProvenanceLedger
from .signals import BANDS, PersonalBaseline, SimulatedEEG, SimulatedPhysiology, band_powers, signal_quality

SEQUENCE_LENGTH = 32
PHYSIOLOGY_WEIGHT = 0.25          # slow signals nudge the state; they don't drive it
HISTORY = 600                     # states and ratings kept in memory (60 s at 10 Hz)


@dataclass
class Anchor:
    event_id: str
    description: str
    context: dict
    embedding: np.ndarray = field(repr=False)


class NeurovisualSystem:
    def __init__(self, eeg=None, physiology=None, ledger: ProvenanceLedger | None = None, generator=None,
                 seed: int = 0, learn_interval: float = 30.0, clock=time.monotonic, predictor=None,
                 recorder=None, renderer=None, stream=None):
        self.eeg = eeg or SimulatedEEG(seed=seed)
        self.physiology = physiology or SimulatedPhysiology(seed=seed)
        self.ledger, self.recorder, self.renderer, self.stream = ledger, recorder, renderer, stream
        self.generator = generator or PlaceholderGenerator()
        self.clock, self.learn_interval = clock, learn_interval
        self.feature_names = list(BANDS) + list(self.physiology.read().values)
        self.baseline = PersonalBaseline(len(self.feature_names))
        self.model = check(predictor, Predictor, "predictor") if predictor is not None else \
            TemporalPredictor(len(self.feature_names), seed=seed)
        self._swap = threading.Lock()
        self.sequence: deque[np.ndarray] = deque(maxlen=SEQUENCE_LENGTH)
        self.states: deque[VisualLatentState] = deque(maxlen=HISTORY)
        self.feedback: deque[dict] = deque(maxlen=HISTORY)
        self.anchors: dict[str, Anchor] = {}
        self.mode, self.event_id = VisualMode.MEMORY, None
        self.last_learning = clock()
        self.bursts: list[dict] = []
        self._learner: threading.Thread | None = None

    # -- setup -------------------------------------------------------------------------------------------
    def add_memory(self, event_id: str, description: str, context: dict | None = None) -> None:
        self.anchors[event_id] = Anchor(event_id, description, context or {}, anchor_embedding(description))
        if self.recorder:
            self.recorder.record_anchor(event_id, description, context or {})

    def set_mode(self, mode: VisualMode, event_id: str | None = None) -> None:
        self.mode, self.event_id = mode, event_id

    # -- real time ---------------------------------------------------------------------------------------
    def step(self) -> dict:
        started = self.clock()
        window, slow = self.eeg.read(), self.physiology.read()
        raw = np.concatenate([band_powers(window), np.asarray(list(slow.values.values()), dtype=float)])
        self.baseline.update(raw)
        features = self.baseline.zscore(raw)
        features[len(BANDS):] *= PHYSIOLOGY_WEIGHT
        self.sequence.append(features)
        anchor = self.anchors.get(self.event_id) if self.event_id else None
        quality = signal_quality(window) * self.baseline.readiness
        with self._swap:
            model = self.model
        state = model.predict(list(self.sequence), self.mode, anchor.embedding if anchor else None,
                              quality=quality, timestamp=window.timestamp, event_id=self.event_id)
        self.states.append(state)
        request = condition(state, anchor.description if anchor else None)
        frame = self.renderer.submit(request) if self.renderer else self.generator.render(request)
        if self.recorder:
            self.recorder.record_step(state, raw, features, quality, request, window)
        if self.stream:
            self.stream.send(state)
        self.maybe_learn()
        return {"state": state, "request": request, "frame": frame, "latency_seconds": self.clock() - started}

    def run(self, seconds: float, hz: float = 10.0, sleep=time.sleep) -> dict:
        """Steps at `hz` for `seconds`; returns timing figures for the real-time path."""
        interval, latencies = 1.0 / hz, []
        end = self.clock() + seconds
        while self.clock() < end:
            began = self.clock()
            latencies.append(self.step()["latency_seconds"])
            spare = interval - (self.clock() - began)
            if spare > 0:
                sleep(spare)
        return {"steps": len(latencies), "mean_latency_ms": 1000 * float(np.mean(latencies)) if latencies else 0.0,
                "max_latency_ms": 1000 * float(np.max(latencies)) if latencies else 0.0,
                "deadline_misses": sum(l > interval for l in latencies)}

    # -- feedback and learning ---------------------------------------------------------------------------
    def rate(self, rating: float, notes: str = "") -> None:
        """Rates the latest state, from -1 (wrong) to 1 (right). Notes are kept in memory, and on disk only
        in the encrypted session dataset when recording."""
        if not self.states:
            raise ValueError("there's no state to rate yet")
        if not -1.0 <= rating <= 1.0:
            raise ValueError("a rating is between -1 and 1")
        state = self.states[-1]
        self.feedback.append({"context": state.context, "neural": state.neural, "rating": float(rating),
                              "mode": state.mode, "event_id": state.event_id, "notes": notes,
                              "model_version": state.model_version})
        if self.recorder:
            self.recorder.record_rating(rating, notes)

    def maybe_learn(self, force: bool = False) -> bool:
        """Starts a learning burst in the background if one is due. Returns whether it started."""
        if self._learner and self._learner.is_alive():
            return False
        due = force or self.clock() - self.last_learning >= self.learn_interval
        if not due:
            return False
        self.last_learning = self.clock()            # due or not, the interval restarts: no busy retries
        if not self.feedback:
            return False
        records = list(self.feedback)
        self.feedback.clear()
        self._learner = threading.Thread(target=self._learn, args=(records,), name="neurovisual-learning", daemon=True)
        self._learner.start()
        return True

    def _learn(self, records: list[dict]) -> None:
        started = time.perf_counter()
        with self._swap:
            current = self.model
        if not hasattr(current, "trained"):
            self.bursts.append({"records": len(records), "skipped": f"{type(current).__name__} has no trained()"})
            return
        trained, metrics = current.trained(records)
        metrics["seconds"] = round(time.perf_counter() - started, 4)
        with self._swap:
            self.model = trained
        if self.ledger:
            self.ledger.append("learning_burst", data=[{k: (v.tolist() if isinstance(v, np.ndarray) else v)
                                                         for k, v in r.items()} for r in records],
                               model_sha256=trained.fingerprint(),
                               config={"predictor": type(trained).__name__, "features": self.feature_names,
                                       "sequence_length": SEQUENCE_LENGTH, "latent_size": LATENT_SIZE,
                                       "physiology_weight": PHYSIOLOGY_WEIGHT, "decay": getattr(trained, "decay", None),
                                       "epochs": metrics.get("epochs"), "learning_rate": metrics.get("learning_rate")},
                               metrics=metrics)
        self.bursts.append(metrics)

    def wait_for_learning(self, timeout: float = 30.0) -> None:
        if self._learner:
            self._learner.join(timeout)

    # -- shutdown ----------------------------------------------------------------------------------------
    def close(self) -> dict:
        """Stops the renderer, closes sensors and the stream, and finishes the session dataset (its summary
        goes in the provenance ledger as a keyed digest). Returns what was closed."""
        self.wait_for_learning()
        summary: dict = {}
        if self.renderer:
            self.renderer.close()
            summary["renderer"] = self.renderer.stats()
            if self.recorder:
                for result in self.renderer.results:
                    self.recorder.record_generation(result)
        for sensor in (self.eeg, self.physiology):
            if hasattr(sensor, "close"):
                sensor.close()
        if self.stream:
            self.stream.close()
            summary["stream_datagrams"] = self.stream.sent
        if self.recorder:
            summary["dataset"] = self.recorder.close()
            if self.ledger:
                self.ledger.append("dataset_recorded", data=summary["dataset"], model_sha256=self.model.fingerprint(),
                                   config={"features": self.feature_names, "include_raw": self.recorder.include_raw},
                                   metrics={k: summary["dataset"][k] for k in ("steps", "ratings", "frames")})
        return summary
