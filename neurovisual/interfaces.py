"""The open interfaces: any sensor, model or generator that fits these plugs into NeurovisualSystem.

    Sensor      read() -> EEGWindow (EEG) or PhysiologySample (slow signals); optional close()
    Predictor   version_text, predict(...), fingerprint(); optional trained(records) for learning bursts
    Generator   render(request) -> dict (image/video output, its file and SHA-256, or a queued job)

Third-party code is loaded by reference, "package.module:attribute", where the attribute is a class
or factory called with the keyword arguments the slot provides (a predictor gets feature_dim). The
built-in TemporalPredictor, the simulated sensors and the adapters in sensors.py and generators.py
are reference implementations. docs/neurovisual/SDK.md has worked examples.
"""
from __future__ import annotations

import importlib
from typing import Any, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class Sensor(Protocol):
    def read(self) -> Any: ...


@runtime_checkable
class Predictor(Protocol):
    version_text: str

    def predict(self, sequence: list[np.ndarray], mode, anchor: np.ndarray | None, quality: float,
                timestamp: float, event_id: str | None = None): ...

    def fingerprint(self) -> str: ...


@runtime_checkable
class Generator(Protocol):
    def render(self, request) -> dict: ...


def load_plugin(reference: str, **kwargs):
    """Imports "package.module:attribute" and, if the attribute is callable, calls it with kwargs."""
    module_name, _, attribute = reference.partition(":")
    if not module_name or not attribute:
        raise ValueError(f"a plugin reference looks like package.module:attribute, not {reference!r}")
    target = getattr(importlib.import_module(module_name), attribute)
    return target(**kwargs) if callable(target) else target


def check(obj, protocol, slot: str):
    """Returns obj if it fits the slot's interface, else raises TypeError saying what's missing."""
    if not isinstance(obj, protocol):
        missing = [name for name in getattr(protocol, "__protocol_attrs__", ()) if not hasattr(obj, name)]
        raise TypeError(f"{type(obj).__name__} can't be the {slot}: it's missing {', '.join(missing) or 'methods'}")
    return obj
