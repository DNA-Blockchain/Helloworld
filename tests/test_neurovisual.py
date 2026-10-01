"""The neural -> visual prototype: signal features, baseline, temporal prediction, evidence accounting,
learning from ratings without blocking real time, and a provenance ledger that holds no personal data."""
import json
import math
import threading
import time

import numpy as np
import pytest

from neurovisual import NeurovisualSystem, ProvenanceLedger, VisualMode
from neurovisual.model import TemporalPredictor, anchor_embedding
from neurovisual.provenance import keyed_digest, load_or_create_key
from neurovisual.signals import BANDS, EEGWindow, PersonalBaseline, band_powers, signal_quality

KEY = b"k" * 32


def sine_window(freq, channels=4, rate=256.0):
    t = np.arange(int(rate)) / rate
    return EEGWindow(0.0, np.tile(20 * np.sin(2 * math.pi * freq * t), (channels, 1)), rate)


@pytest.mark.parametrize("freq,band", [(2, "delta"), (6, "theta"), (10, "alpha"), (20, "beta"), (38, "gamma")])
def test_band_power_finds_the_right_band(freq, band):
    powers = band_powers(sine_window(freq))
    assert list(BANDS)[int(np.argmax(powers))] == band


def test_signal_quality_flags_dead_channels_and_bad_values():
    window = sine_window(10)
    assert signal_quality(window) == 1.0
    window.data[0] = 0.0
    assert signal_quality(window) == 0.75
    window.data[1, 3] = np.nan
    assert signal_quality(window) == 0.0


def test_the_personal_baseline_centres_each_person_on_themselves():
    rng = np.random.default_rng(1)
    baseline = PersonalBaseline(2)
    assert baseline.readiness == 0 and not baseline.zscore(np.ones(2)).any()
    for _ in range(500):
        baseline.update(rng.normal([100, -5], [10, 0.5]))
    assert np.allclose(baseline.zscore(np.array([100, -5])), 0, atol=0.15)
    assert np.allclose(baseline.zscore(np.array([110, -4.5])), 1, atol=0.15) and baseline.readiness == 1


def test_prediction_depends_on_the_sequence_not_only_the_newest_sample():
    model = TemporalPredictor(3, seed=0)
    last = np.array([1.0, 0.0, 0.0])
    a = model.predict([np.zeros(3), np.zeros(3), last], VisualMode.MEMORY, None, 1.0, 0.0)
    b = model.predict([np.ones(3) * 2, np.ones(3) * 2, last], VisualMode.MEMORY, None, 1.0, 0.0)
    assert not np.allclose(a.neural, b.neural)


def test_evidence_is_claimed_only_when_a_stored_memory_exists():
    model, seq, anchor = TemporalPredictor(3), [np.zeros(3)], anchor_embedding("sunset gathering")
    without = model.predict(seq, VisualMode.MEMORY, None, 1.0, 0.0)
    with_anchor = model.predict(seq, VisualMode.MEMORY, anchor, 1.0, 0.0)
    imagined = model.predict(seq, VisualMode.IMAGINATION, anchor, 1.0, 0.0)
    assert without.evidence_weight == 0 and with_anchor.evidence_weight == 0.7
    assert with_anchor.confidence > imagined.confidence > 0 and without.confidence < with_anchor.confidence
    assert model.predict(seq, VisualMode.MEMORY, anchor, 0.0, 0.0).confidence == 0     # no signal, no confidence
    assert np.array_equal(anchor, anchor_embedding("sunset gathering")) and np.all(np.abs(with_anchor.scene) <= 1)


def test_learning_follows_the_ratings_and_leaves_the_live_model_alone():
    model = TemporalPredictor(3, seed=2)
    rng = np.random.default_rng(3)
    records = []
    for rating in (1.0, 0.8, -0.6):
        state = model.predict([rng.normal(size=3)], VisualMode.MEMORY, None, 1.0, 0.0)
        records.append({"context": state.context, "neural": state.neural, "rating": rating})
    weights = model.W.copy()
    trained, metrics = model.trained(records)
    assert metrics["objective_after"] > metrics["objective_before"]
    assert np.array_equal(model.W, weights) and model.version_text == "1.0.0" and trained.version_text == "1.1.0"
    assert trained.fingerprint() != model.fingerprint()
    again, _ = model.trained(records)
    assert again.fingerprint() == trained.fingerprint()                 # deterministic, not wall-clock bound


def test_a_learning_burst_never_blocks_the_real_time_loop(monkeypatch):
    system = NeurovisualSystem(seed=0, learn_interval=0.0)
    system.add_memory("e1", "outdoor event near sunset")
    system.set_mode(VisualMode.MEMORY, "e1")
    system.step()
    system.rate(0.9, "felt right")
    release = threading.Event()
    real = system.model.trained

    def slow(records):
        release.wait(5)
        return real(records)

    monkeypatch.setattr(system.model, "trained", slow)
    assert system.maybe_learn(force=True)
    started = time.perf_counter()
    steps = [system.step() for _ in range(10)]                            # while training is still running
    assert time.perf_counter() - started < 1.0 and system._learner.is_alive()
    assert all(s["state"].model_version == "1.0.0" for s in steps)
    release.set()
    system.wait_for_learning()
    assert system.step()["state"].model_version == "1.1.0" and len(system.bursts) == 1


def test_without_feedback_the_scheduler_waits_a_full_interval():
    now = [0.0]
    system = NeurovisualSystem(seed=0, learn_interval=30.0, clock=lambda: now[0])
    now[0] = 31.0
    assert not system.maybe_learn() and system.last_learning == 31.0      # no feedback: no burst, timer restarts
    system.step()
    system.rate(0.5)
    now[0] = 40.0
    assert not system.maybe_learn()                                        # not due yet
    now[0] = 61.0
    assert system.maybe_learn()
    system.wait_for_learning()


def test_ratings_are_checked_and_history_is_bounded():
    system = NeurovisualSystem(seed=0)
    with pytest.raises(ValueError, match="no state"):
        system.rate(0.5)
    for _ in range(700):
        system.step()
    assert len(system.states) == 600 and len(system.sequence) == 32
    with pytest.raises(ValueError, match="between -1 and 1"):
        system.rate(2)


def test_the_ledger_detects_tampering_and_holds_no_personal_data(tmp_path):
    path = tmp_path / "nv" / "provenance.jsonl"
    system = NeurovisualSystem(ledger=ProvenanceLedger(KEY, path), seed=0, learn_interval=0.0)
    system.add_memory("birthday", "my sister's birthday at the lake")
    system.set_mode(VisualMode.MEMORY, "birthday")
    system.step()
    system.rate(0.7, "it was my sister's birthday")
    system.maybe_learn(force=True)
    system.wait_for_learning()
    text = path.read_text()
    assert "sister" not in text and "birthday" not in text and "lake" not in text
    reloaded = ProvenanceLedger(KEY, path)
    assert [e["kind"] for e in reloaded.entries] == ["genesis", "learning_burst"] and reloaded.verify()[0]
    burst = reloaded.entries[1]
    assert burst["model_sha256"] == system.model.fingerprint() and burst["metrics"]["records"] == 1
    lines = text.splitlines()
    tampered = json.loads(lines[1])
    tampered["metrics"]["records"] = 99
    path.write_text(lines[0] + "\n" + json.dumps(tampered) + "\n")
    ok, problems = ProvenanceLedger(KEY, path).verify()
    assert not ok and "entry 1: contents don't match its hash" in problems


def test_personal_data_digests_are_keyed(tmp_path):
    record = {"notes": "a private memory"}
    assert keyed_digest(KEY, record) != keyed_digest(b"x" * 32, record)
    key = load_or_create_key(tmp_path / "ledger.key")
    assert len(key) == 32 and load_or_create_key(tmp_path / "ledger.key") == key


def test_the_demo_session_runs(capsys):
    from neurovisual.__main__ import main

    assert main(["--seconds", "0.3", "--no-ledger"]) == 0
    out = capsys.readouterr().out
    assert "memory" in out and "imagination" in out and "model 1.0.0 -> 1.1.0" in out
