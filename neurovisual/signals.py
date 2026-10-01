"""Signals: EEG windows and slow physiology, their features, and the personal baseline.

EEG arrives as windows of raw multichannel samples (channels x samples). Features are log band powers
(delta to gamma) from a Hann-windowed FFT averaged over channels, so they mean the same thing for any
headset and sample rate. Physiology (hormone levels, heart rate, skin conductance...) changes slowly
and arrives as named normalized values.

Every person's signals differ, so features are expressed against that person's own running baseline
(z-scores with Welford's online mean and variance) rather than against anyone else's.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

BANDS = {"delta": (1.0, 4.0), "theta": (4.0, 8.0), "alpha": (8.0, 13.0), "beta": (13.0, 30.0), "gamma": (30.0, 45.0)}


@dataclass
class EEGWindow:
    timestamp: float
    data: np.ndarray                 # channels x samples, in microvolts
    sample_rate: float


@dataclass
class PhysiologySample:
    timestamp: float
    values: dict[str, float]         # normalized 0..1, slow-changing


def band_powers(window: EEGWindow) -> np.ndarray:
    """log10 power per band (BANDS order), averaged over channels."""
    data = np.asarray(window.data, dtype=float)
    data = data - data.mean(axis=1, keepdims=True)
    spectrum = np.abs(np.fft.rfft(data * np.hanning(data.shape[1]), axis=1)) ** 2
    freqs = np.fft.rfftfreq(data.shape[1], d=1.0 / window.sample_rate)
    powers = [spectrum[:, (freqs >= lo) & (freqs < hi)].sum(axis=1).mean() for lo, hi in BANDS.values()]
    return np.log10(np.asarray(powers) + 1e-12)


def signal_quality(window: EEGWindow) -> float:
    """The share of channels carrying signal (a flat channel is a disconnected electrode); 0.0 if any
    value isn't finite."""
    data = np.asarray(window.data, dtype=float)
    if not np.all(np.isfinite(data)):
        return 0.0
    return float(np.mean(data.std(axis=1) > 1e-6))


class PersonalBaseline:
    """Running mean and variance per feature (Welford), for one person."""

    def __init__(self, size: int, warmup: int = 20):
        self.n, self.warmup = 0, warmup
        self.mean = np.zeros(size)
        self._m2 = np.zeros(size)

    def update(self, x: np.ndarray) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        self._m2 += delta * (x - self.mean)

    def zscore(self, x: np.ndarray) -> np.ndarray:
        if self.n < 2:
            return np.zeros_like(x)
        std = np.sqrt(self._m2 / (self.n - 1))
        return (x - self.mean) / np.maximum(std, 1e-6)

    @property
    def readiness(self) -> float:
        """0..1: how established the baseline is; predictions are weighted down until it is."""
        return min(1.0, self.n / self.warmup)


class SimulatedEEG:
    """Multichannel EEG-like windows: band oscillations whose amplitudes drift slowly, plus noise.
    A stand-in for an acquisition layer; it carries no information about anyone's mind."""

    FREQS = {"delta": 2.0, "theta": 6.0, "alpha": 10.0, "beta": 20.0, "gamma": 38.0}

    def __init__(self, channels: int = 8, sample_rate: float = 256.0, window_seconds: float = 1.0,
                 step_seconds: float = 0.1, seed: int = 0):
        self.channels, self.sample_rate, self.step = channels, sample_rate, step_seconds
        self.samples = int(sample_rate * window_seconds)
        self.rng = np.random.default_rng(seed)
        self.t = 0.0
        self.amplitudes = {band: 10.0 for band in self.FREQS}

    def read(self) -> EEGWindow:
        self.t += self.step
        for band in self.amplitudes:            # slow drift, kept in a plausible range
            self.amplitudes[band] = float(np.clip(self.amplitudes[band] * math.exp(self.rng.normal(0, 0.05)), 2, 40))
        times = self.t + np.arange(self.samples) / self.sample_rate
        phases = self.rng.uniform(0, 2 * math.pi, size=(self.channels, len(self.FREQS)))
        data = self.rng.normal(0, 2.0, size=(self.channels, self.samples))
        for k, (band, freq) in enumerate(self.FREQS.items()):
            data += self.amplitudes[band] * np.sin(2 * math.pi * freq * times + phases[:, k:k + 1])
        return EEGWindow(timestamp=self.t, data=data, sample_rate=self.sample_rate)


class SimulatedPhysiology:
    """Slow, bounded random walks standing in for hormone and other physiological measurements."""

    def __init__(self, names: tuple[str, ...] = ("cortisol", "heart_rate"), seed: int = 0):
        self.rng = np.random.default_rng(seed + 1)
        self.values = {name: 0.5 for name in names}
        self.t = 0.0

    def read(self) -> PhysiologySample:
        self.t += 0.1
        for name in self.values:
            self.values[name] = float(np.clip(self.values[name] + self.rng.normal(0, 0.005), 0.0, 1.0))
        return PhysiologySample(timestamp=self.t, values=dict(self.values))
