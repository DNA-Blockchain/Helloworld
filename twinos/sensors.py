"""Signal sources for the twin's state, and the MicroPython device link.

Every source returns an Observation: named numeric features, a quality from 0 to 1, and whether the
source is really there. A source that isn't connected says so (available=False) instead of pretending.

  EEGSource        EEG through neurovisual's sensors: BrainFlow (OpenBCI, Muse, Neurosity... or board -1,
                   BrainFlow's synthetic board), Lab Streaming Layer, or the simulated EEG. Features are
                   log band powers, delta to gamma (neurovisual/signals.py), averaged over channels.
  PluginSource     any other measurement (RF/radar, audio, a wearable) from "package.module:attribute",
                   an object whose read() returns {feature: number}. RF gives physical measurements
                   (range, Doppler, motion, breathing rate); it doesn't read DNA or thoughts.
  Unavailable      a slot with no driver yet; always available=False, with the reason.

EEG features are signal measurements, not thoughts. They feed a per-person baseline (state.py), and a
change against that baseline is a hint the owner can act on, never a command.

MicroPythonSerial talks to an ESP32, RP2040 or similar board over USB serial (pip install pyserial): one
JSON object per line each way. docs/twinos/README.md has the matching main.py for the board.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field

from neurovisual.interfaces import load_plugin
from neurovisual.sensors import SensorUnavailable
from neurovisual.signals import BANDS, SimulatedEEG, band_powers, signal_quality


@dataclass
class Observation:
    source: str
    timestamp: float
    available: bool
    features: dict[str, float] = field(default_factory=dict)
    quality: float = 0.0
    detail: str = ""


class EEGSource:
    def __init__(self, sensor, kind: str):
        self.sensor, self.kind, self.name = sensor, kind, "eeg"

    @classmethod
    def open(cls, kind: str = "simulated", **options) -> "EEGSource":
        if kind == "simulated":
            return cls(SimulatedEEG(seed=options.get("seed", 0)), kind)
        if kind == "brainflow":
            from neurovisual.sensors import BrainFlowEEG
            return cls(BrainFlowEEG(board_id=options.get("board_id", -1), serial_port=options.get("serial_port", "")), kind)
        if kind == "lsl":
            from neurovisual.sensors import LSLEEG
            return cls(LSLEEG(stream_type=options.get("stream_type", "EEG")), kind)
        raise ValueError(f"EEG sources are simulated, brainflow and lsl; not {kind!r}")

    def observe(self) -> Observation:
        try:
            window = self.sensor.read()
        except SensorUnavailable as error:
            return Observation(self.name, time.time(), False, detail=str(error))
        features = dict(zip(BANDS, (float(x) for x in band_powers(window))))
        return Observation(self.name, time.time(), True, features, signal_quality(window), detail=self.kind)

    def close(self) -> None:
        if hasattr(self.sensor, "close"):
            self.sensor.close()


class PluginSource:
    def __init__(self, name: str, reference: str, **options):
        self.name, self.reference = name, reference
        self.driver = load_plugin(reference, **options)

    def observe(self) -> Observation:
        try:
            raw = self.driver.read()
            features = {str(k): float(v) for k, v in raw.items()}
        except Exception as error:      # a third-party driver's failure is this reading's state, not a crash
            return Observation(self.name, time.time(), False, detail=f"{type(error).__name__}: {error}")
        finite = {k: v for k, v in features.items() if math.isfinite(v)}
        quality = len(finite) / len(features) if features else 0.0
        return Observation(self.name, time.time(), bool(finite), finite, quality, detail=self.reference)

    def close(self) -> None:
        if hasattr(self.driver, "close"):
            self.driver.close()


class Unavailable:
    def __init__(self, name: str, reason: str):
        self.name, self.reason = name, reason

    def observe(self) -> Observation:
        return Observation(self.name, time.time(), False, detail=self.reason)

    def close(self) -> None:
        pass


class MicroPythonSerial:
    """One JSON command per line to the board, one JSON reply per line back."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 2.0, connection=None):
        if connection is None:
            try:
                import serial
            except ImportError as error:
                raise SensorUnavailable("pyserial isn't installed: pip install pyserial") from error
            try:
                connection = serial.Serial(port, baudrate, timeout=timeout)
            except serial.SerialException as error:
                raise SensorUnavailable(f"can't open {port}: {error}") from error
        self.port, self.connection = port, connection

    def send(self, command: dict) -> dict:
        self.connection.write((json.dumps(command, separators=(",", ":")) + "\n").encode("utf-8"))
        self.connection.flush()
        line = self.connection.readline()
        if not line:
            raise TimeoutError(f"no reply from the board on {self.port}")
        reply = json.loads(line.decode("utf-8"))
        if not isinstance(reply, dict):
            raise ValueError("the board's reply isn't a JSON object")
        return reply

    def close(self) -> None:
        self.connection.close()
