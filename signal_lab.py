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
signal_lab.py
=============
The signal lab's command line: move real or simulated signals between
sources and sinks, send the DNA twin over radio, decode it back, and drive the
twin with EEG. The spec strings are signal_io.py's, so every command works on
simulated input now and on real hardware later.

  python signal_lab.py devices
  python signal_lab.py bridge --source eeg:synthetic --sink stats --seconds 5
  python signal_lab.py bridge --source rf:sim --sink file:tone.cf32 --seconds 2
  python signal_lab.py bridge --source rf:soapy:driver=rtlsdr?freq=100e6 --sink udp:127.0.0.1:9700
  python signal_lab.py send-twin --twin run.json --sink file:twin.cf32
  python signal_lab.py receive-twin --source rf:file:twin.cf32?rate=250e3 --twin run.json
  python signal_lab.py eeg-control --source eeg:synthetic --twin run.json --seconds 30

--allow-remote lets UDP sources and sinks use other machines (with
SIGNAL_LINK_KEY set). --transmit plus signal_tx_policy.json is required
before anything goes out over the air; see signal_io.py.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

import signal_io
import twin_signals


def load_twin(path: Path) -> dict:
    import dna_twin_viewer

    return dna_twin_viewer.twin_from_run(json.loads(path.read_text(encoding="utf-8")))


def twin_sequence(args) -> tuple[str, str]:
    if args.dna:
        return args.dna.upper(), "given sequence"
    if args.twin:
        twin = load_twin(args.twin)
        return twin[args.strand], f"{twin['case_label']} ({args.strand})"
    raise SystemExit("give --twin RUN.json or --dna ACGT...")


def modem_of(args) -> twin_signals.Modem:
    return twin_signals.Modem(args.rate, args.baud, args.deviation)


def cmd_devices(args) -> int:
    try:
        from brainflow.board_shim import BoardIds

        names = sorted(n.lower().removesuffix("_board") for n in BoardIds.__members__)
        print(f"BrainFlow boards (eeg:<name>): {', '.join(names)}")
    except ImportError:
        print("BrainFlow not installed: pip install brainflow")
    try:
        sdr = signal_io._soapy()
        found = sdr.Device.enumerate()
        print(f"SoapySDR radios: {[dict(d) for d in found] or 'none connected'}")
    except RuntimeError as error:
        print(str(error))
    return 0


def cmd_bridge(args) -> int:
    source = signal_io.open_source(args.source, args.allow_remote)
    sink = signal_io.open_sink(args.sink, args.allow_remote, args.transmit, args.policy)
    frames, started = 0, time.time()
    try:
        for frame in source.frames():
            sink.write(frame)
            frames += 1
            if args.seconds and time.time() - started >= args.seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        sink.close()
    print(f"moved {frames} frame(s) from {args.source} to {args.sink}", file=sys.stderr)
    return 0


def cmd_send_twin(args) -> int:
    dna, label = twin_sequence(args)
    modem = modem_of(args)
    iq = np.tile(twin_signals.dna_to_iq(dna, modem), args.repeat)
    sink = signal_io.open_sink(args.sink, args.allow_remote, args.transmit, args.policy)
    try:
        for start in range(0, len(iq), 16384):
            sink.write(signal_io.Frame("iq", modem.sample_rate, iq[start:start + 16384], "twin", center_hz=None))
    finally:
        sink.close()
    seconds = len(iq) / modem.sample_rate
    print(f"sent {label}: {len(dna)} bases as {len(iq)} IQ samples ({seconds:.2f} s at "
          f"{modem.sample_rate:g} S/s, {modem.baud:g} baud BFSK +/-{modem.deviation:g} Hz) to {args.sink}")
    return 0


def cmd_receive_twin(args) -> int:
    modem = modem_of(args)
    source = signal_io.open_source(args.source, args.allow_remote)
    chunks, started = [], time.time()
    try:
        for frame in source.frames():
            chunks.append(frame.data)
            if args.seconds and time.time() - started >= args.seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
    if not chunks:
        print("no samples received")
        return 1
    decoded = twin_signals.iq_to_dna(np.concatenate(chunks), modem)
    if not decoded.crc_ok:
        print(f"no valid packet: {decoded.reason}")
        return 1
    print(f"received {len(decoded.dna)} bases, CRC-32 OK: {decoded.dna}")
    if args.twin:
        twin = load_twin(args.twin)
        match = next((part for part in ("sample", "reference", "edited") if twin[part] == decoded.dna), None)
        print(f"matches the twin's {match} strand" if match else "does not match any strand of the twin")
        return 0 if match else 1
    return 0


def cmd_eeg_control(args) -> int:
    source = signal_io.open_source(args.source, args.allow_remote)
    twin = load_twin(args.twin) if args.twin else None
    control, cursor, started = None, 0, time.time()
    print("calibrating: relax with eyes open for the first windows, then close your eyes to select")
    try:
        for frame in source.frames():
            if frame.kind != "eeg":
                raise SystemExit(f"{args.source} is not an EEG source")
            control = control or twin_signals.EEGControl(frame.sample_rate)
            for event in control.feed(frame.data.astype(np.float64)):
                if twin and twin["mutations"] and event["event"] in ("select", "next"):
                    if event["event"] == "next":
                        cursor = (cursor + 1) % len(twin["mutations"])
                    m = twin["mutations"][cursor]
                    event["difference"] = {"position": m["position"], "reference": m["reference"],
                                           "observed": m["observed"]}
                print(json.dumps(event))
            if args.seconds and time.time() - started >= args.seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--allow-remote", action="store_true",
                        help=f"let UDP specs use other machines (needs {signal_io.LINK_KEY_ENV})")

    def tx(sp):
        sp.add_argument("--transmit", action="store_true",
                        help="allow an over-the-air sink (also needs the transmit policy file)")
        sp.add_argument("--policy", type=Path, default=signal_io.DEFAULT_POLICY)

    def modem(sp):
        sp.add_argument("--rate", type=float, default=250_000.0, help="samples per second")
        sp.add_argument("--baud", type=float, default=5_000.0)
        sp.add_argument("--deviation", type=float, default=10_000.0, help="FSK tone offset, Hz")

    sub.add_parser("devices", help="list BrainFlow boards and connected SoapySDR radios")

    sp = sub.add_parser("bridge", help="move frames from any source to any sink")
    sp.add_argument("--source", required=True)
    sp.add_argument("--sink", default="stats")
    sp.add_argument("--seconds", type=float, default=0, help="stop after this long (0 = until the source ends)")
    common(sp); tx(sp)

    sp = sub.add_parser("send-twin", help="modulate a twin's sequence as a BFSK radio packet")
    sp.add_argument("--twin", type=Path, help="remission_workflow.py run JSON")
    sp.add_argument("--strand", default="sample", choices=("sample", "reference", "edited"))
    sp.add_argument("--dna", help="send this ACGT sequence instead of a twin")
    sp.add_argument("--sink", required=True)
    sp.add_argument("--repeat", type=int, default=1)
    common(sp); tx(sp); modem(sp)

    sp = sub.add_parser("receive-twin", help="demodulate a twin packet and check its CRC")
    sp.add_argument("--source", required=True)
    sp.add_argument("--twin", type=Path, help="also say which strand of this twin it matches")
    sp.add_argument("--seconds", type=float, default=0)
    common(sp); modem(sp)

    sp = sub.add_parser("eeg-control", help="alpha-rhythm select/next events, optionally stepping a twin")
    sp.add_argument("--source", default="eeg:synthetic")
    sp.add_argument("--twin", type=Path)
    sp.add_argument("--seconds", type=float, default=30)
    common(sp)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {"devices": cmd_devices, "bridge": cmd_bridge, "send-twin": cmd_send_twin,
               "receive-twin": cmd_receive_twin, "eeg-control": cmd_eeg_control}[args.command]
    try:
        return handler(args)
    except (PermissionError, ValueError, RuntimeError, OSError) as error:
        print(f"refused: {error}" if isinstance(error, PermissionError) else f"error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
