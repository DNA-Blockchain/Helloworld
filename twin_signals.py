#!/usr/bin/env python3
# ============================================================================
#  SPDX-License-Identifier: UPL-1.0
#
#  Copyright (c) 2026 Chase Allen Ringquist
#
#  This file is part of an operating system, software, and network Work
#  conceived and authored by Chase Allen Ringquist. The Author retains
#  copyright and authorship. Use of this file is licensed as follows.
#
#  ----------------------------------------------------------------------------
#  The Universal Permissive License (UPL), Version 1.0
#
#  Subject to the condition set forth below, permission is hereby granted to
#  any person obtaining a copy of this software, associated documentation
#  and/or data (collectively the "Software"), free of charge and under any
#  and all copyright rights in the Software, and any and all patent rights
#  owned or freely licensable by each licensor hereunder covering either
#  (i) the unmodified Software as contributed to or provided by such
#  licensor, or (ii) the Larger Works (as defined below), to deal in both
#
#  (a) the Software, and
#
#  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
#  if one is included with the Software (each a "Larger Work" to which the
#  Software is contributed by such licensors),
#
#  without restriction, including without limitation the rights to copy,
#  create derivative works of, display, perform, and distribute the Software
#  and make, use, sell, offer for sale, import, export, have made, and have
#  sold the Software and the Larger Work(s), and to sublicense the foregoing
#  rights on either these or other terms.
#
#  This license is subject to the following condition:
#
#  The above copyright notice and either this complete permission notice or
#  at a minimum a reference to the UPL must be included in all copies or
#  substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#  ----------------------------------------------------------------------------
#
#  Do not remove or alter this notice or any record of origin.
#  See NOTICE.md in the project root for authorship and ownership terms.
#
#  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
#            Bixby, OK, United States
# ============================================================================

"""
twin_signals.py
===============
Real signal paths for the DNA twin.

1. DNA over radio. A twin's sequence is sent as an ordinary digital radio
   packet: 2 bits per base (the project's A=00 C=01 G=10 T=11 code), framed
   as preamble, sync word, base count, the bases, then a CRC-32, and
   modulated as continuous-phase binary FSK. dna_to_iq gives complex baseband
   samples any SDR can transmit or any file sink can store. iq_to_dna
   demodulates them back, from a simulation, a recording or a live radio, and
   checks the CRC. This is data transmission. The DNA has no radio frequency
   of its own; the frequency is whatever the operator tunes the radio to.

2. EEG controls. A brain-computer interface can't read thoughts. What it can
   reliably pick up is changes in rhythm the user produces on purpose, and the
   strongest is posterior alpha (8-12 Hz), which rises when the eyes close or
   attention relaxes. EEGControl calibrates a per-person baseline of relative
   alpha power, then emits "select" when alpha stays well above that baseline
   and "next" when it falls back. A signal lab can map those events to
   stepping through the twin's differences. It is a simple band-power
   threshold, not a medical measurement.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from dna_binary_codec import REVERSE_MAP as BASE_TO_BITS

BITS_TO_BASE = {bits: base for base, bits in BASE_TO_BITS.items()}
PREAMBLE = [1, 0] * 32
SYNC = [int(b) for b in format(0xD391, "016b")]
MAX_BASES = 65535


@dataclass(frozen=True)
class Modem:
    sample_rate: float = 250_000.0
    baud: float = 5_000.0
    deviation: float = 10_000.0     # tone offset from centre, Hz, each side

    @property
    def samples_per_bit(self) -> int:
        spb = self.sample_rate / self.baud
        if spb != int(spb) or spb < 4:
            raise ValueError("sample_rate must be a whole multiple (at least 4) of baud")
        return int(spb)


def packet_bits(dna: str) -> list[int]:
    bases = dna.upper()
    if not bases or set(bases) - set("ACGT"):
        raise ValueError("a packet carries a non-empty ACGT sequence")
    if len(bases) > MAX_BASES:
        raise ValueError(f"at most {MAX_BASES} bases per packet")
    body = [int(b) for b in format(len(bases), "016b")]
    body += [int(bit) for base in bases for bit in BASE_TO_BITS[base]]
    crc = zlib.crc32(bytes(body)) & 0xFFFFFFFF
    return PREAMBLE + SYNC + body + [int(b) for b in format(crc, "032b")]


def dna_to_iq(dna: str, modem: Modem = Modem(), amplitude: float = 0.7) -> np.ndarray:
    """The packet as continuous-phase BFSK complex baseband (complex64), with
    a short silence each side so a receiver can find it."""
    bits = np.repeat(np.array(packet_bits(dna)) * 2 - 1, modem.samples_per_bit)
    phase = np.cumsum(2 * np.pi * modem.deviation * bits / modem.sample_rate)
    signal = amplitude * np.exp(1j * phase)
    pad = np.zeros(modem.samples_per_bit * 16, dtype=np.complex64)
    return np.concatenate([pad, signal.astype(np.complex64), pad])


@dataclass
class Decoded:
    dna: Optional[str]
    crc_ok: bool
    found_sync: bool
    reason: str = ""


def iq_to_dna(iq: np.ndarray, modem: Modem = Modem()) -> Decoded:
    """Demodulate BFSK: an FM discriminator, centred on the signal's own mean
    frequency (so a tuning offset doesn't matter), averaged over one bit, then
    the bit timing that best matches the sync word. Returns the sequence only
    if the CRC matches."""
    spb = modem.samples_per_bit
    if len(iq) < spb * (len(PREAMBLE) + len(SYNC) + 48):
        return Decoded(None, False, False, "too few samples for a packet")
    freq = np.angle(iq[1:] * np.conj(iq[:-1]))            # instantaneous frequency, rad/sample
    power = np.abs(iq[1:]) ** 2
    active = power > 0.25 * np.percentile(power, 99)       # ignore silence and weak noise
    if not active.any():
        return Decoded(None, False, False, "no signal")
    centre = float(np.median(freq[active]))
    smooth = np.convolve(np.where(active, freq - centre, 0.0), np.ones(spb) / spb, mode="same")
    target = np.array(PREAMBLE[-16:] + SYNC, dtype=np.int8)
    best = None                                            # (strength, offset, index)
    for offset in range(spb):
        samples = smooth[offset::spb]
        hard = (samples > 0).astype(np.int8)
        if len(hard) < len(target):
            continue
        windows = np.lib.stride_tricks.sliding_window_view(hard, len(target))
        for index in np.flatnonzero((windows == target).all(axis=1)):
            strength = float(np.mean(np.abs(samples[index:index + len(target)])))
            if best is None or strength > best[0]:
                best = (strength, offset, int(index))
    if best is None:
        return Decoded(None, False, False, "no sync word found")
    _, offset, index = best
    samples = smooth[offset::spb]
    correction = float(np.mean(samples[max(0, index - 32):index + 16]))   # balanced preamble
    body = ((samples[index + len(target):] - correction) > 0).astype(int)
    if len(body) < 16:
        return Decoded(None, False, True, "packet cut off")
    count = int("".join(map(str, body[:16])), 2)
    needed = 16 + count * 2 + 32
    if count == 0 or len(body) < needed:
        return Decoded(None, False, True, "packet cut off or corrupt length")
    payload = [int(b) for b in body[:16 + count * 2]]
    crc = int("".join(map(str, body[16 + count * 2:needed])), 2)
    dna = "".join(BITS_TO_BASE[f"{payload[i]}{payload[i + 1]}"] for i in range(16, len(payload), 2))
    ok = (zlib.crc32(bytes(payload)) & 0xFFFFFFFF) == crc
    return Decoded(dna if ok else None, ok, True, "" if ok else "CRC mismatch")


# ------------------------------------------------------------ EEG controls

def band_power(data: np.ndarray, rate: float, low: float, high: float) -> np.ndarray:
    """Total power per channel between low and high Hz (Hann-windowed FFT).
    Summed, not averaged, so bands of different widths compare fairly and a
    sub-band can never exceed the band containing it."""
    x = data - data.mean(axis=-1, keepdims=True)
    spectrum = np.abs(np.fft.rfft(x * np.hanning(x.shape[-1]), axis=-1)) ** 2
    freqs = np.fft.rfftfreq(x.shape[-1], 1 / rate)
    mask = (freqs >= low) & (freqs < high)
    return spectrum[..., mask].sum(axis=-1) if mask.any() else np.zeros(x.shape[:-1])


def relative_alpha(data: np.ndarray, rate: float) -> float:
    """Alpha (8-12 Hz) power as a fraction (0-1) of 1-30 Hz power, median
    across channels."""
    alpha = band_power(data, rate, 8, 12)
    total = band_power(data, rate, 1, 30) + 1e-12
    return float(np.median(alpha / total))


@dataclass
class EEGControl:
    rate: float
    window_seconds: float = 2.0
    calibration_windows: int = 5
    rise: float = 1.5          # select when relative alpha > baseline * rise
    hold_windows: int = 2      # ...for this many windows in a row
    buffer: Optional[np.ndarray] = None
    baseline_values: list[float] = field(default_factory=list)
    above: int = 0
    selected: bool = False

    @property
    def baseline(self) -> Optional[float]:
        if len(self.baseline_values) < self.calibration_windows:
            return None
        return float(np.median(self.baseline_values))

    def feed(self, data: np.ndarray) -> list[dict]:
        """Add samples (channels, n); returns any control events."""
        self.buffer = data if self.buffer is None else np.concatenate([self.buffer, data], axis=1)
        window = int(self.window_seconds * self.rate)
        events = []
        while self.buffer.shape[1] >= window:
            chunk, self.buffer = self.buffer[:, :window], self.buffer[:, window:]
            value = relative_alpha(chunk, self.rate)
            if self.baseline is None:
                self.baseline_values.append(value)
                if self.baseline is not None:
                    events.append({"event": "calibrated", "baseline_alpha": round(self.baseline, 4)})
                continue
            self.above = self.above + 1 if value > self.baseline * self.rise else 0
            if self.above >= self.hold_windows and not self.selected:
                self.selected = True
                events.append({"event": "select", "alpha": round(value, 4)})
            elif self.above == 0 and self.selected:
                self.selected = False
                events.append({"event": "next", "alpha": round(value, 4)})
        return events
