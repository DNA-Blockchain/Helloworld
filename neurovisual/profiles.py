"""Presets for the three uses: research, gaming and AI development. Every field can be overridden.

  research      10 Hz; every step recorded with the raw EEG; generation slow and deliberate; no stream
  gaming        30 Hz for responsiveness; latent streamed to the game engine; frequent generation;
                nothing recorded unless asked
  development   10 Hz; steps recorded without raw EEG; stream and generation on, for wiring up models
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Profile:
    name: str
    hz: float
    record: bool
    include_raw: bool
    stream: bool
    render_interval: float          # seconds between generations (AsyncRenderer.min_interval)
    learn_interval: float           # seconds between learning bursts


PROFILES = {
    "research": Profile("research", hz=10, record=True, include_raw=True, stream=False, render_interval=5.0, learn_interval=60),
    "gaming": Profile("gaming", hz=30, record=False, include_raw=False, stream=True, render_interval=1.0, learn_interval=30),
    "development": Profile("development", hz=10, record=True, include_raw=False, stream=True, render_interval=2.0, learn_interval=30),
}


def profile(name: str, **overrides) -> Profile:
    if name not in PROFILES:
        raise ValueError(f"profiles are {', '.join(PROFILES)}; not {name!r}")
    return replace(PROFILES[name], **overrides)
