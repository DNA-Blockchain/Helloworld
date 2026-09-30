"""The signal lab: IQ file formats, the twin's DNA over a BFSK radio link, the
UDP frame link and its authentication, the transmit gate, and EEG controls."""
import json
import threading
import time

import numpy as np
import pytest

import signal_io as sio
import signal_lab
import twin_signals as ts

DNA = "ATGGATTTATCTGCTCTTCGCGTTGAAGAAGTACAAAATGTCATTAATGCTATGCAG"


def test_iq_file_formats_round_trip():
    rng = np.random.default_rng(0)
    iq = (0.8 * (rng.random(1000) - 0.5) + 0.8j * (rng.random(1000) - 0.5)).astype(np.complex64)
    assert np.array_equal(sio.decode_iq(sio.encode_iq(iq, "cf32"), "cf32"), iq)
    for fmt in ("cs8", "cu8"):                               # 8-bit: within one quantisation step
        back = sio.decode_iq(sio.encode_iq(iq, fmt), fmt)
        assert np.max(np.abs(back - iq)) < 1.5 / 127
    with pytest.raises(ValueError):
        sio.iq_format("capture.wav")


def _channel(iq, snr_db, shift_hz=0.0, rate=250_000.0, seed=1):
    n = np.arange(len(iq))
    shifted = (iq * np.exp(2j * np.pi * shift_hz * n / rate)).astype(np.complex64)
    return np.concatenate([f.data for f in sio.SimulatedRF(rate=rate, iq=shifted, snr_db=snr_db,
                                                           seed=seed).frames()])


@pytest.mark.parametrize("snr_db,shift_hz", [(40, 0), (12, 0), (12, 3000), (12, -3000)])
def test_dna_survives_the_radio_link(snr_db, shift_hz):
    decoded = ts.iq_to_dna(_channel(ts.dna_to_iq(DNA), snr_db, shift_hz))
    assert decoded.crc_ok and decoded.dna == DNA


def test_a_corrupted_packet_is_refused_not_misread():
    iq = ts.dna_to_iq(DNA)
    spb = ts.Modem().samples_per_bit
    body_start = spb * (16 + len(ts.PREAMBLE) + len(ts.SYNC) + 16)   # past the length field
    iq[body_start:body_start + spb * 3] = np.conj(iq[body_start:body_start + spb * 3])  # flip 3 bits
    decoded = ts.iq_to_dna(iq)
    assert decoded.found_sync and not decoded.crc_ok and decoded.dna is None
    assert ts.iq_to_dna(_channel(np.zeros(50_000, np.complex64), 20)).dna is None


def test_packet_rejects_bad_sequences_and_bad_modems():
    for bad in ("", "ACGN", "A" * (ts.MAX_BASES + 1)):
        with pytest.raises(ValueError):
            ts.packet_bits(bad)
    with pytest.raises(ValueError):
        ts.Modem(sample_rate=10_000, baud=3_000).samples_per_bit


def _eeg_frame(n=250, channels=4):
    data = np.random.default_rng(2).standard_normal((channels, n)).astype(np.float32)
    return sio.Frame("eeg", 250.0, data, "eeg:test", channels=[f"C{i}" for i in range(channels)])


def _receive(source, count, out):
    for frame in source.frames():
        out.append(frame)
        if len(out) >= count:
            break


def test_udp_link_carries_eeg_and_iq_frames():
    source = sio.UDPSource("127.0.0.1", 0, timeout=3)
    port = source.sock.getsockname()[1]
    got = []
    t = threading.Thread(target=_receive, args=(source, 2, got))
    t.start()
    sink = sio.UDPSink("127.0.0.1", port)
    eeg = _eeg_frame()
    iq = sio.Frame("iq", 1e6, np.arange(100, dtype=np.float32).astype(np.complex64), "rf:test", center_hz=1e8)
    sink.write(eeg)
    sink.write(iq)
    t.join(5)
    sink.close(); source.close()
    assert np.array_equal(got[0].data, eeg.data) and got[0].channels == eeg.channels
    assert np.array_equal(got[1].data, iq.data) and got[1].center_hz == 1e8


def test_big_frames_are_split_to_fit_udp():
    frame = sio.Frame("iq", 2.4e6, np.ones(40_000, np.complex64), "rf:test")
    datagrams = sio.pack_frames(frame, "s", 0, None)
    assert len(datagrams) > 1 and all(len(d) <= 65507 for d in datagrams)
    parts = [sio.unpack_frame(d, None) for d in datagrams]
    assert sum(p.data.size for p in parts) == 40_000


def test_keyed_link_rejects_unsigned_forged_and_replayed_frames(monkeypatch):
    key = b"shared-secret"
    guard = sio.LinkReplayGuard()
    [good] = sio.pack_frames(_eeg_frame(), "s1", 5, key)
    assert sio.unpack_frame(good, key, guard) is not None
    assert sio.unpack_frame(good, key, guard) is None                         # replay
    [unsigned] = sio.pack_frames(_eeg_frame(), "s1", 6, None)
    assert sio.unpack_frame(unsigned, key, guard) is None
    [forged] = sio.pack_frames(_eeg_frame(), "s1", 7, b"wrong-key")
    assert sio.unpack_frame(forged, key, guard) is None
    tampered = bytearray(sio.pack_frames(_eeg_frame(), "s1", 8, key)[0])
    tampered[-1] ^= 1
    assert sio.unpack_frame(bytes(tampered), key, guard) is None
    [stale] = sio.pack_frames(_eeg_frame(), "s1", 9, key)
    monkeypatch.setattr(sio.time, "time", lambda: time.monotonic() + 1e9)
    assert sio.unpack_frame(stale, key, guard) is None


def test_leaving_the_machine_needs_permission_and_a_key(monkeypatch):
    monkeypatch.delenv(sio.LINK_KEY_ENV, raising=False)
    with pytest.raises(PermissionError, match="allow-remote"):
        sio.UDPSink("192.0.2.10", 9700)
    with pytest.raises(PermissionError, match=sio.LINK_KEY_ENV):
        sio.UDPSink("192.0.2.10", 9700, allow_remote=True)
    monkeypatch.setenv(sio.LINK_KEY_ENV, "k")
    assert sio.UDPSink("192.0.2.10", 9700, allow_remote=True).key == b"k"
    assert sio.UDPSink("127.0.0.1", 9700).key == b"k"                         # loopback signs too when set


def _policy(tmp_path, operator="KX0XXX (General)", bands=None):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"operator": operator, "bands": bands if bands is not None else [
        {"name": "2 m", "low_hz": 144e6, "high_hz": 148e6, "max_seconds": 1}]}))
    return path


def test_transmit_gate_needs_flag_policy_operator_and_band(tmp_path):
    with pytest.raises(PermissionError, match="--transmit"):
        sio.TransmitGate(False, 146e6, 250e3, _policy(tmp_path))
    with pytest.raises(PermissionError, match="no transmit policy"):
        sio.TransmitGate(True, 146e6, 250e3, tmp_path / "missing.json")
    with pytest.raises(PermissionError, match="operator"):
        sio.TransmitGate(True, 146e6, 250e3, _policy(tmp_path, operator=" "))
    with pytest.raises(PermissionError, match="not inside"):
        sio.TransmitGate(True, 100e6, 250e3, _policy(tmp_path))                 # FM broadcast
    with pytest.raises(PermissionError, match="not inside"):
        sio.TransmitGate(True, 144.05e6, 250e3, _policy(tmp_path))              # spills below the edge
    gate = sio.TransmitGate(True, 146e6, 250e3, _policy(tmp_path))
    gate.spend(200_000)                                                          # 0.8 s
    with pytest.raises(PermissionError, match="airtime"):
        gate.spend(100_000)                                                      # would pass 1 s


def test_example_policy_cannot_be_used_as_is(tmp_path):
    import shutil
    from pathlib import Path
    example = Path(sio.__file__).with_name("signal_tx_policy.example.json")
    shutil.copy(example, tmp_path / "p.json")
    with pytest.raises(PermissionError, match="operator"):
        sio.TransmitPolicy.load(tmp_path / "p.json")


def test_transmit_sink_is_refused_before_the_radio_is_touched(tmp_path):
    spec = "rf:soapy:driver=hackrf?freq=146e6&rate=250e3"
    with pytest.raises(PermissionError):
        sio.open_sink(spec, transmit=False)
    with pytest.raises(PermissionError):
        sio.open_sink(spec, transmit=True, policy_path=tmp_path / "none.json")


def test_eeg_control_calibrates_then_selects_on_alpha_and_releases():
    rate, rng = 250.0, np.random.default_rng(3)
    t = np.arange(int(rate * 2)) / rate

    def window(alpha):
        noise = rng.standard_normal((4, t.size)) * 5
        return noise + alpha * np.sin(2 * np.pi * 10 * t)

    control = ts.EEGControl(rate)
    events = []
    for alpha in [2] * 5 + [30] * 3 + [2] * 2:
        events += control.feed(window(alpha))
    kinds = [e["event"] for e in events]
    assert kinds == ["calibrated", "select", "next"]


def test_brainflow_synthetic_board_streams_frames():
    pytest.importorskip("brainflow")
    source = sio.open_source("eeg:synthetic")
    try:
        frame = next(source.frames())
    finally:
        source.close()
    assert frame.kind == "eeg" and frame.sample_rate == 250 and frame.data.shape[0] == 16
    with pytest.raises(ValueError, match="unknown BrainFlow board"):
        sio.resolve_board("not_a_board")
    assert sio.resolve_board("cyton") == 0 and sio.resolve_board("ganglion") == 1


def test_lab_sends_a_twin_and_reads_it_back(tmp_path, capsys):
    out = tmp_path / "twin.cs8"
    assert signal_lab.main(["send-twin", "--dna", DNA, "--sink", f"file:{out}"]) == 0
    assert signal_lab.main(["receive-twin", "--source", f"rf:file:{out}?rate=250e3"]) == 0
    assert f"CRC-32 OK: {DNA}" in capsys.readouterr().out
    assert signal_lab.main(["send-twin", "--dna", DNA,
                            "--sink", "rf:soapy:driver=hackrf?freq=146e6&rate=250e3"]) == 2
    assert "refused" in capsys.readouterr().out
