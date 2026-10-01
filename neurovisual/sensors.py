"""Live EEG through the two common open SDKs, as Sensor adapters that return EEGWindow.

  BrainFlowEEG   BrainFlow (pip install brainflow): OpenBCI Cyton/Ganglion, Muse, Neurosity, BrainBit,
                 g.tec Unicorn and more, by board id. Board -1 is BrainFlow's synthetic board, which
                 streams generated EEG with no hardware: use it to test the full live path.
  LSLEEG         Lab Streaming Layer (pip install pylsl): any device or app that publishes an LSL stream
                 of type "EEG" (most research amplifiers and OpenViBE, NeuroPype, BCI2000...).

Both keep the newest `window_seconds` of samples and return them on each read(), so the real-time loop
runs at its own rate whatever the device's sample rate. Signals stay in memory; nothing is sent anywhere.
"""
from __future__ import annotations

import time

import numpy as np

from .signals import EEGWindow


class SensorUnavailable(RuntimeError):
    pass


class BrainFlowEEG:
    def __init__(self, board_id: int = -1, window_seconds: float = 1.0, serial_port: str = "",
                 mac_address: str = "", timeout: float = 5.0):
        try:
            from brainflow.board_shim import BoardShim, BrainFlowInputParams
        except ImportError as error:
            raise SensorUnavailable("BrainFlow isn't installed: pip install brainflow") from error
        params = BrainFlowInputParams()
        params.serial_port, params.mac_address = serial_port, mac_address
        BoardShim.disable_board_logger()
        self.board = BoardShim(board_id, params)
        self.rate = BoardShim.get_sampling_rate(board_id)
        self.channels = BoardShim.get_eeg_channels(board_id)
        self.samples = int(self.rate * window_seconds)
        self.timeout = timeout
        self.board.prepare_session()
        self.board.start_stream()

    def read(self) -> EEGWindow:
        deadline = time.monotonic() + self.timeout
        data = self.board.get_current_board_data(self.samples)
        while data.shape[1] < self.samples // 4:          # just started: wait for a usable window
            if time.monotonic() > deadline:
                raise SensorUnavailable(f"no EEG data from the board within {self.timeout:.0f} s")
            time.sleep(0.02)
            data = self.board.get_current_board_data(self.samples)
        return EEGWindow(timestamp=time.time(), data=np.asarray(data[self.channels], dtype=float),
                         sample_rate=float(self.rate))

    def close(self) -> None:
        try:
            self.board.stop_stream()
        finally:
            self.board.release_session()


class LSLEEG:
    def __init__(self, stream_type: str = "EEG", window_seconds: float = 1.0, timeout: float = 5.0):
        try:
            from pylsl import StreamInlet, resolve_byprop
        except ImportError as error:
            raise SensorUnavailable("pylsl isn't installed: pip install pylsl") from error
        streams = resolve_byprop("type", stream_type, timeout=timeout)
        if not streams:
            raise SensorUnavailable(f"no LSL stream of type {stream_type!r} found within {timeout:.0f} s")
        self.inlet = StreamInlet(streams[0])
        info = self.inlet.info()
        self.rate = info.nominal_srate() or 250.0
        self.buffer = np.zeros((info.channel_count(), int(self.rate * window_seconds)))
        self.filled = 0

    def read(self) -> EEGWindow:
        chunk, _ = self.inlet.pull_chunk(timeout=0.0)
        if chunk:
            new = np.asarray(chunk, dtype=float).T[:, -self.buffer.shape[1]:]
            self.buffer = np.concatenate([self.buffer[:, new.shape[1]:], new], axis=1)
            self.filled = min(self.buffer.shape[1], self.filled + new.shape[1])
        # Until the window has filled, return only what has arrived (quality is judged on that).
        data = self.buffer[:, -self.filled:] if self.filled else self.buffer[:, :1]
        return EEGWindow(timestamp=time.time(), data=data.copy(), sample_rate=float(self.rate))

    def close(self) -> None:
        self.inlet.close_stream()
