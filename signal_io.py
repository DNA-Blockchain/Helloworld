#!/usr/bin/env python3
"""
signal_io.py
============
One interface for real and simulated signals: EEG from any BrainFlow board,
radio IQ samples from any SoapySDR radio or from recordings, and signal
frames over the network. Every source yields Frames and every sink takes
them, so the same lab code runs on BrainFlow's synthetic board today and on a
real OpenBCI board or SDR later, with only the spec string changed.

Source specs:
  eeg:synthetic                              BrainFlow's simulated board (no hardware)
  eeg:cyton?serial_port=/dev/ttyUSB0         any BrainFlow board by name, with its
  eeg:ganglion?serial_port=COM3              BrainFlowInputParams as query fields
  eeg:playback?file=rec.csv&master_board=cyton   a BrainFlow recording
  rf:sim?freq=100e6&rate=1e6&tone=50e3       simulated IQ: a tone plus noise
  rf:file:capture.cu8?rate=2.4e6&freq=100e6  a recording: .cu8 (rtl_sdr), .cs8
                                             (hackrf_transfer), .cf32/.cfile (GNU Radio)
  rf:soapy:driver=rtlsdr?freq=100e6&rate=2.4e6&gain=30   any SoapySDR radio
  udp:127.0.0.1:9700                         frames arriving over the network

Sink specs:
  stats                                      print a line per frame
  file:out.cf32 | file:out.cs8 | file:eeg.csv   write to a file
  udp:127.0.0.1:9700                         send frames over the network
  rf:soapy:driver=hackrf?freq=144.39e6&rate=2e6   transmit (gated, see below)

Network: sockets bind and send to loopback unless allow_remote is set, and
leaving the machine requires SIGNAL_LINK_KEY. With a key every datagram
carries an HMAC-SHA256, and a receiver drops unsigned, forged, replayed
(sequence not increasing) or stale (more than 30 s off) frames. EEG is
personal data: keep it on this machine unless you mean to send it.

Transmitting: radio transmission is legally regulated (in the US, FCC Part 97
for licensed amateurs and Part 15 for low-power devices), and transmitting
outside your allocation can interfere with emergency, aviation and other
services. An rf:soapy sink therefore refuses to open unless transmit=True
(the --transmit flag) AND a policy file names the operator and the bands
they may use. The whole occupied bandwidth (centre +/- rate/2) must sit
inside one band, and total airtime is capped by that band's max_seconds.
Receiving, recordings and simulation have no such gate.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import socket
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import parse_qsl

import numpy as np

LINK_KEY_ENV = "SIGNAL_LINK_KEY"
MAGIC = b"NOSF"
MAX_DATAGRAM = 60000
MAX_CLOCK_SKEW = 30.0
DEFAULT_POLICY = Path(__file__).resolve().parent / "signal_tx_policy.json"


@dataclass
class Frame:
    """A block of samples. kind "eeg": data is (channels, samples) float32
    microvolts. kind "iq": data is complex64 baseband samples around
    center_hz."""
    kind: str
    sample_rate: float
    data: np.ndarray
    source: str
    t: float = field(default_factory=time.time)
    center_hz: Optional[float] = None
    channels: list[str] = field(default_factory=list)

    def header(self) -> dict:
        return {"kind": self.kind, "sample_rate": self.sample_rate, "source": self.source, "t": self.t,
                "center_hz": self.center_hz, "channels": self.channels, "shape": list(self.data.shape)}


def parse_spec(spec: str) -> tuple[str, str, dict]:
    """"rf:file:x.cu8?rate=2e6" -> ("rf", "file:x.cu8", {"rate": "2e6"})."""
    kind, _, rest = spec.partition(":")
    target, _, query = rest.partition("?")
    return kind, target, dict(parse_qsl(query))


def _is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _link_key(host: str, allow_remote: bool) -> Optional[bytes]:
    key = os.environ.get(LINK_KEY_ENV, "").encode() or None
    if not _is_loopback(host):
        if not allow_remote:
            raise PermissionError(f"{host} is not this machine; pass --allow-remote to use the network")
        if key is None:
            raise PermissionError(f"set {LINK_KEY_ENV} (the same on both ends) before sending signals "
                                  "off this machine, so frames are authenticated")
    return key


# ----------------------------------------------------------------- sources

class Source:
    def frames(self) -> Iterator[Frame]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class BrainFlowSource(Source):
    """Any BrainFlow board. Unknown names list the valid ones."""

    def __init__(self, board: str, params: dict, chunk_seconds: float = 0.25):
        from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams

        BoardShim.disable_board_logger()
        self.board_id = resolve_board(board)
        inputs = BrainFlowInputParams()
        for key, value in params.items():
            if not hasattr(inputs, key):
                raise ValueError(f"BrainFlow has no input parameter {key!r}")
            setattr(inputs, key, int(value) if isinstance(getattr(inputs, key), int) else value)
        self.shim = BoardShim(self.board_id, inputs)
        self.rate = BoardShim.get_sampling_rate(self.board_id)
        self.eeg_rows = BoardShim.get_eeg_channels(self.board_id)
        try:
            names = BoardShim.get_eeg_names(self.board_id)
        except Exception:
            names = [f"ch{i + 1}" for i in range(len(self.eeg_rows))]
        self.names = list(names)[:len(self.eeg_rows)]
        self.chunk_seconds = chunk_seconds
        self.label = f"eeg:{BoardIds(self.board_id).name.lower()}"
        self.shim.prepare_session()
        self.shim.start_stream()

    def frames(self) -> Iterator[Frame]:
        while True:
            time.sleep(self.chunk_seconds)
            data = self.shim.get_board_data()
            if data.shape[1]:
                yield Frame("eeg", float(self.rate), data[self.eeg_rows].astype(np.float32), self.label,
                            channels=self.names)

    def close(self) -> None:
        try:
            self.shim.stop_stream()
        finally:
            self.shim.release_session()


def resolve_board(name: str) -> int:
    from brainflow.board_shim import BoardIds

    if name.lstrip("-").isdigit():
        return int(name)
    upper = name.upper()
    for candidate in (upper, f"{upper}_BOARD", f"{upper}_FILE_BOARD"):
        if candidate in BoardIds.__members__:
            return BoardIds[candidate].value
    known = ", ".join(sorted(n.lower().removesuffix("_board") for n in BoardIds.__members__))
    raise ValueError(f"unknown BrainFlow board {name!r}; known: {known}")


class SimulatedRF(Source):
    """A tone at `tone` Hz from centre plus complex Gaussian noise, or, with
    `iq`, a given baseband signal (e.g. twin_signals.dna_to_iq) played once
    through the same noise."""

    def __init__(self, rate: float = 1e6, center_hz: float = 100e6, tone: float = 50e3,
                 snr_db: float = 20.0, chunk: int = 16384, iq: Optional[np.ndarray] = None,
                 seed: Optional[int] = None):
        self.rate, self.center_hz, self.tone, self.chunk = rate, center_hz, tone, chunk
        self.noise = 10 ** (-snr_db / 20)
        self.iq = iq
        self.rng = np.random.default_rng(seed)
        self.n = 0

    def _noise(self, count: int) -> np.ndarray:
        return (self.noise / np.sqrt(2) * (self.rng.standard_normal(count)
                                           + 1j * self.rng.standard_normal(count))).astype(np.complex64)

    def frames(self) -> Iterator[Frame]:
        if self.iq is not None:
            for start in range(0, len(self.iq), self.chunk):
                part = self.iq[start:start + self.chunk]
                yield Frame("iq", self.rate, (part + self._noise(len(part))).astype(np.complex64),
                            "rf:sim", center_hz=self.center_hz)
            return
        while True:
            idx = np.arange(self.n, self.n + self.chunk)
            self.n += self.chunk
            tone = np.exp(2j * np.pi * self.tone * idx / self.rate).astype(np.complex64)
            yield Frame("iq", self.rate, tone + self._noise(self.chunk), "rf:sim", center_hz=self.center_hz)


IQ_FORMATS = {".cu8": "cu8", ".cs8": "cs8", ".cf32": "cf32", ".cfile": "cf32", ".fc32": "cf32"}


def iq_format(path: str) -> str:
    fmt = IQ_FORMATS.get(Path(path).suffix.lower())
    if fmt is None:
        raise ValueError(f"unknown IQ file type {Path(path).suffix!r}; use {', '.join(IQ_FORMATS)}")
    return fmt


def decode_iq(raw: bytes, fmt: str) -> np.ndarray:
    if fmt == "cf32":
        return np.frombuffer(raw[:len(raw) // 8 * 8], dtype=np.complex64).copy()
    if fmt == "cu8":      # rtl_sdr: unsigned bytes centred on 127.5
        pairs = (np.frombuffer(raw[:len(raw) // 2 * 2], dtype=np.uint8).astype(np.float32) - 127.5) / 127.5
    else:                 # cs8, hackrf_transfer: signed bytes
        pairs = np.frombuffer(raw[:len(raw) // 2 * 2], dtype=np.int8).astype(np.float32) / 127.0
    return (pairs[0::2] + 1j * pairs[1::2]).astype(np.complex64)


def encode_iq(iq: np.ndarray, fmt: str) -> bytes:
    if fmt == "cf32":
        return iq.astype(np.complex64).tobytes()
    pairs = np.empty(iq.size * 2, dtype=np.float32)
    pairs[0::2], pairs[1::2] = iq.real, iq.imag
    pairs = np.clip(pairs, -1.0, 1.0)
    if fmt == "cu8":
        return np.round(pairs * 127.5 + 127.5).astype(np.uint8).tobytes()
    return np.round(pairs * 127).astype(np.int8).tobytes()


class FileRF(Source):
    def __init__(self, path: str, rate: float, center_hz: Optional[float] = None, chunk: int = 65536):
        self.path, self.rate, self.center_hz, self.chunk = path, rate, center_hz, chunk
        self.fmt = iq_format(path)
        self.bytes_per_sample = 8 if self.fmt == "cf32" else 2

    def frames(self) -> Iterator[Frame]:
        with open(self.path, "rb") as f:
            while raw := f.read(self.chunk * self.bytes_per_sample):
                yield Frame("iq", self.rate, decode_iq(raw, self.fmt), f"rf:file:{Path(self.path).name}",
                            center_hz=self.center_hz)


def _soapy():
    try:
        import SoapySDR  # noqa: F401
        return SoapySDR
    except ImportError as error:
        raise RuntimeError(
            "SoapySDR isn't installed. On Ubuntu/WSL: sudo apt install python3-soapysdr soapysdr-module-all, "
            "then make the venv with --system-site-packages. Plug the radio in with usbipd on WSL."
        ) from error


class SoapyRF(Source):
    """Receive from any SoapySDR radio (RTL-SDR, HackRF, LimeSDR, Pluto, ...)."""

    def __init__(self, device: str, rate: float, center_hz: float, gain: Optional[float] = None,
                 channel: int = 0, chunk: int = 16384):
        sdr_mod = _soapy()
        self.sdr = sdr_mod.Device(device)
        self.sdr.setSampleRate(sdr_mod.SOAPY_SDR_RX, channel, rate)
        self.sdr.setFrequency(sdr_mod.SOAPY_SDR_RX, channel, center_hz)
        if gain is not None:
            self.sdr.setGain(sdr_mod.SOAPY_SDR_RX, channel, gain)
        self.stream = self.sdr.setupStream(sdr_mod.SOAPY_SDR_RX, sdr_mod.SOAPY_SDR_CF32, [channel])
        self.sdr.activateStream(self.stream)
        self.rate, self.center_hz, self.chunk, self.label = rate, center_hz, chunk, f"rf:soapy:{device}"

    def frames(self) -> Iterator[Frame]:
        buf = np.empty(self.chunk, dtype=np.complex64)
        while True:
            result = self.sdr.readStream(self.stream, [buf], self.chunk)
            if result.ret > 0:
                yield Frame("iq", self.rate, buf[:result.ret].copy(), self.label, center_hz=self.center_hz)

    def close(self) -> None:
        self.sdr.deactivateStream(self.stream)
        self.sdr.closeStream(self.stream)


# ------------------------------------------------------------- network link

def pack_frames(frame: Frame, stream_id: str, seq: int, key: Optional[bytes]) -> list[bytes]:
    """The frame as one or more datagrams (split along samples to fit UDP)."""
    data = frame.data
    per_sample = data.itemsize * (data.shape[0] if data.ndim == 2 else 1)
    step = max(1, (MAX_DATAGRAM - 1024) // per_sample)
    width = data.shape[-1]
    out = []
    for i, start in enumerate(range(0, width, step)):
        part = data[..., start:start + step]
        header = dict(Frame(frame.kind, frame.sample_rate, part, frame.source, frame.t, frame.center_hz,
                            frame.channels).header(), stream=stream_id, seq=seq + i,
                      dtype=str(part.dtype), sent=time.time())
        head = json.dumps(header, separators=(",", ":")).encode()
        body = struct.pack(">I", len(head)) + head + np.ascontiguousarray(part).tobytes()
        mac = hmac.new(key, body, hashlib.sha256).digest() if key else b"\0" * 32
        out.append(MAGIC + mac + body)
    return out


class LinkReplayGuard:
    def __init__(self):
        self.last: dict[str, int] = {}

    def accept(self, header: dict) -> bool:
        stream, seq = header.get("stream", ""), int(header.get("seq", -1))
        if abs(time.time() - float(header.get("sent", 0))) > MAX_CLOCK_SKEW:
            return False
        if seq <= self.last.get(stream, -1):
            return False
        self.last[stream] = seq
        return True


def unpack_frame(datagram: bytes, key: Optional[bytes], guard: Optional[LinkReplayGuard] = None
                 ) -> Optional[Frame]:
    """A Frame from a datagram, or None if it's malformed, unsigned or forged
    when a key is set, or replayed."""
    if len(datagram) < 40 or datagram[:4] != MAGIC:
        return None
    mac, body = datagram[4:36], datagram[36:]
    if key is not None and not hmac.compare_digest(mac, hmac.new(key, body, hashlib.sha256).digest()):
        return None
    (head_len,) = struct.unpack(">I", body[:4])
    try:
        header = json.loads(body[4:4 + head_len])
        data = np.frombuffer(body[4 + head_len:], dtype=np.dtype(header["dtype"])).reshape(header["shape"])
    except (ValueError, KeyError, TypeError):
        return None
    if key is not None and guard is not None and not guard.accept(header):
        return None
    return Frame(header["kind"], header["sample_rate"], data.copy(), header["source"], header["t"],
                 header.get("center_hz"), header.get("channels") or [])


class UDPSource(Source):
    def __init__(self, host: str, port: int, allow_remote: bool = False, timeout: Optional[float] = None):
        self.key = _link_key(host, allow_remote)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.settimeout(timeout)
        self.guard = LinkReplayGuard()
        self.rejected = 0

    def frames(self) -> Iterator[Frame]:
        while True:
            try:
                datagram, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                return
            frame = unpack_frame(datagram, self.key, self.guard)
            if frame is None:
                self.rejected += 1
                continue
            yield frame

    def close(self) -> None:
        self.sock.close()


# -------------------------------------------------------------------- sinks

class Sink:
    def write(self, frame: Frame) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class StatsSink(Sink):
    def __init__(self, out=print):
        self.out = out

    def write(self, frame: Frame) -> None:
        self.out(describe(frame))


def describe(frame: Frame) -> str:
    n = frame.data.shape[-1]
    if frame.kind == "iq":
        power = 10 * np.log10(np.mean(np.abs(frame.data) ** 2) + 1e-20)
        spectrum = np.abs(np.fft.fftshift(np.fft.fft(frame.data)))
        peak = (np.argmax(spectrum) - n / 2) * frame.sample_rate / n
        where = f" peak {((frame.center_hz or 0) + peak) / 1e6:.4f} MHz" if n else ""
        return f"{frame.source}: {n} IQ samples, {power:.1f} dBFS{where}"
    rms = np.sqrt(np.mean(frame.data.astype(np.float64) ** 2, axis=1))
    return f"{frame.source}: {n} samples x {frame.data.shape[0]} ch, RMS {np.median(rms):.1f} uV (median)"


class FileSink(Sink):
    def __init__(self, path: str):
        self.path = path
        self.csv = path.lower().endswith(".csv")
        self.fmt = None if self.csv else iq_format(path)
        self.f = open(path, "w" if self.csv else "wb", encoding="utf-8" if self.csv else None, newline="" if self.csv else None)
        self.wrote_header = False

    def write(self, frame: Frame) -> None:
        if self.csv:
            if frame.kind != "eeg":
                raise ValueError("CSV files hold EEG; write IQ to .cf32, .cs8 or .cu8")
            if not self.wrote_header:
                self.f.write(",".join(frame.channels or [f"ch{i + 1}" for i in range(frame.data.shape[0])]) + "\n")
                self.wrote_header = True
            for column in frame.data.T:
                self.f.write(",".join(f"{v:.3f}" for v in column) + "\n")
        else:
            if frame.kind != "iq":
                raise ValueError("IQ files hold radio samples; write EEG to .csv")
            self.f.write(encode_iq(frame.data, self.fmt))

    def close(self) -> None:
        self.f.close()


class UDPSink(Sink):
    def __init__(self, host: str, port: int, allow_remote: bool = False):
        self.key = _link_key(host, allow_remote)
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.stream_id = os.urandom(6).hex()
        self.seq = 0

    def write(self, frame: Frame) -> None:
        for datagram in pack_frames(frame, self.stream_id, self.seq, self.key):
            self.sock.sendto(datagram, self.addr)
            self.seq += 1

    def close(self) -> None:
        self.sock.close()


@dataclass
class TransmitPolicy:
    operator: str
    bands: list[dict]

    @classmethod
    def load(cls, path: Path) -> "TransmitPolicy":
        if not path.exists():
            raise PermissionError(
                f"no transmit policy at {path}. Write one naming the operator (e.g. callsign and licence) "
                "and the bands they may transmit in; see signal_tx_policy.example.json")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not str(raw.get("operator", "")).strip() or not raw.get("bands"):
            raise PermissionError("the transmit policy must name an operator and at least one band")
        return cls(raw["operator"], raw["bands"])

    def band_for(self, center_hz: float, rate: float) -> dict:
        low, high = center_hz - rate / 2, center_hz + rate / 2
        for band in self.bands:
            if float(band["low_hz"]) <= low and high <= float(band["high_hz"]):
                return band
        raise PermissionError(
            f"{low / 1e6:.4f}-{high / 1e6:.4f} MHz is not inside any band in the transmit policy")


class TransmitGate:
    """Everything a transmitting sink must pass: the flag, the policy, the
    band, and the band's airtime cap."""

    def __init__(self, transmit: bool, center_hz: float, rate: float, policy_path: Path = DEFAULT_POLICY):
        if not transmit:
            raise PermissionError("transmitting needs --transmit (and a transmit policy); receiving doesn't")
        self.policy = TransmitPolicy.load(policy_path)
        self.band = self.policy.band_for(center_hz, rate)
        self.max_seconds = float(self.band.get("max_seconds", 10))
        self.rate = rate
        self.airtime = 0.0

    def spend(self, samples: int) -> None:
        seconds = samples / self.rate
        if self.airtime + seconds > self.max_seconds:
            raise PermissionError(f"airtime cap reached ({self.max_seconds:g} s in {self.band.get('name', 'band')})")
        self.airtime += seconds


class SoapyTX(Sink):
    def __init__(self, device: str, rate: float, center_hz: float, gate: TransmitGate,
                 gain: Optional[float] = None, channel: int = 0):
        sdr_mod = _soapy()
        self.gate = gate
        self.sdr = sdr_mod.Device(device)
        self.sdr.setSampleRate(sdr_mod.SOAPY_SDR_TX, channel, rate)
        self.sdr.setFrequency(sdr_mod.SOAPY_SDR_TX, channel, center_hz)
        if gain is not None:
            self.sdr.setGain(sdr_mod.SOAPY_SDR_TX, channel, gain)
        self.stream = self.sdr.setupStream(sdr_mod.SOAPY_SDR_TX, sdr_mod.SOAPY_SDR_CF32, [channel])
        self.sdr.activateStream(self.stream)

    def write(self, frame: Frame) -> None:
        if frame.kind != "iq":
            raise ValueError("only IQ frames can be transmitted")
        self.gate.spend(frame.data.shape[-1])
        self.sdr.writeStream(self.stream, [frame.data.astype(np.complex64)], frame.data.shape[-1])

    def close(self) -> None:
        self.sdr.deactivateStream(self.stream)
        self.sdr.closeStream(self.stream)


# ----------------------------------------------------------------- opening

def _hz(value, default=None):
    return float(value) if value is not None else default


def open_source(spec: str, allow_remote: bool = False) -> Source:
    kind, target, q = parse_spec(spec)
    if kind == "eeg":
        return BrainFlowSource(target or "synthetic", q)
    if kind == "rf":
        mode, _, rest = target.partition(":")
        if mode == "sim":
            return SimulatedRF(_hz(q.get("rate"), 1e6), _hz(q.get("freq"), 100e6), _hz(q.get("tone"), 50e3),
                               _hz(q.get("snr"), 20.0))
        if mode == "file":
            if "rate" not in q:
                raise ValueError("a recording needs ?rate=<samples per second>; the file doesn't store it")
            return FileRF(rest, float(q["rate"]), _hz(q.get("freq")))
        if mode == "soapy":
            return SoapyRF(rest, _hz(q.get("rate"), 2.4e6), _hz(q.get("freq"), 100e6), _hz(q.get("gain")))
    if kind == "udp":
        host, _, port = target.rpartition(":")
        return UDPSource(host or "127.0.0.1", int(port), allow_remote, _hz(q.get("timeout")))
    raise ValueError(f"unknown source {spec!r}")


def open_sink(spec: str, allow_remote: bool = False, transmit: bool = False,
              policy_path: Path = DEFAULT_POLICY) -> Sink:
    kind, target, q = parse_spec(spec)
    if kind == "stats":
        return StatsSink()
    if kind == "file":
        return FileSink(target)
    if kind == "udp":
        host, _, port = target.rpartition(":")
        return UDPSink(host or "127.0.0.1", int(port), allow_remote)
    if kind == "rf" and target.startswith("soapy:"):
        rate, freq = _hz(q.get("rate"), 2e6), _hz(q.get("freq"))
        if freq is None:
            raise ValueError("a transmit sink needs ?freq=<centre Hz>")
        gate = TransmitGate(transmit, freq, rate, policy_path)     # refuses before touching the radio
        return SoapyTX(target.partition(":")[2], rate, freq, gate, _hz(q.get("gain")))
    raise ValueError(f"unknown sink {spec!r}")
