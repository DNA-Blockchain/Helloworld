"""The twin's current state: each source's features against that person's own baseline.

Every source keeps a running baseline per feature (neurovisual.signals.PersonalBaseline, Welford mean and
variance). A reading's deviation is its largest absolute z-score against that baseline. A change is
reported when one source deviates by more than `threshold` standard deviations for `sustain` readings
in a row, once its baseline is established; one spike isn't a change.

Confidence is the mean quality of the sources that are really there, times how established the least
established baseline is. With nothing connected it is 0 and no change is ever reported.

The state holds deviations and qualities only. Feature values stay inside the estimator.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from neurovisual.signals import PersonalBaseline

from .sensors import Observation


@dataclass
class SourceState:
    available: bool
    quality: float = 0.0
    deviation: float = 0.0           # largest |z| against this person's baseline
    readiness: float = 0.0
    detail: str = ""


@dataclass
class TwinState:
    timestamp: float
    sources: dict[str, SourceState]
    confidence: float
    changes: list[str] = field(default_factory=list)      # sources whose change was confirmed at this reading


class StateEstimator:
    def __init__(self, threshold: float = 3.0, sustain: int = 3, warmup: int = 20):
        self.threshold, self.sustain, self.warmup = threshold, sustain, warmup
        self.baselines: dict[tuple[str, tuple[str, ...]], PersonalBaseline] = {}
        self.streaks: dict[str, int] = {}

    def update(self, observations: list[Observation]) -> TwinState:
        sources, changes, qualities, readiness = {}, [], [], []
        for o in observations:
            if not o.available or not o.features:
                sources[o.source] = SourceState(False, detail=o.detail)
                self.streaks[o.source] = 0
                continue
            names = tuple(sorted(o.features))
            x = np.array([o.features[n] for n in names])
            baseline = self.baselines.setdefault((o.source, names), PersonalBaseline(len(names), self.warmup))
            deviation = float(np.max(np.abs(baseline.zscore(x)))) if baseline.n >= 2 else 0.0
            ready = baseline.readiness
            if ready >= 1.0 and deviation > self.threshold:
                self.streaks[o.source] = self.streaks.get(o.source, 0) + 1
                if self.streaks[o.source] == self.sustain:
                    changes.append(o.source)
                elif self.streaks[o.source] > self.sustain:
                    baseline.update(x)       # a confirmed, lasting shift becomes part of the baseline
            else:
                self.streaks[o.source] = 0
                baseline.update(x)           # until then, deviating readings don't move the baseline
            sources[o.source] = SourceState(True, o.quality, round(deviation, 3), ready, o.detail)
            qualities.append(o.quality)
            readiness.append(ready)
        confidence = float(np.mean(qualities) * min(readiness)) if qualities else 0.0
        return TwinState(time.time(), sources, round(confidence, 3), changes)
