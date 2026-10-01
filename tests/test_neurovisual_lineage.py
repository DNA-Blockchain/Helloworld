"""Provenance lineage: dataset -> training-set hash -> memory/imagination training runs (with compute)
-> model version, chained block by block, and traceable from any model back to its data."""
import importlib.util

import numpy as np
import pytest

from neurovisual import NeurovisualSystem, ProvenanceLedger, VisualMode
from neurovisual.compute import compute_info, resolve_device
from neurovisual.datasets import SessionRecorder
from neurovisual.model import TemporalPredictor
from neurovisual.training import TrainingPipeline

KEY = b"t" * 32
FEATURES = ["delta", "theta", "alpha", "beta", "gamma", "cortisol", "heart_rate"]


def record_session(directory, seed):
    recorder = SessionRecorder(directory, KEY, FEATURES, profile="research")
    system = NeurovisualSystem(seed=seed, recorder=recorder, learn_interval=float("inf"))
    system.add_memory("e", "an evening by the water")
    for mode, rating in ((VisualMode.MEMORY, 0.8), (VisualMode.IMAGINATION, -0.3)):
        system.set_mode(mode, "e")
        for _ in range(12):
            system.step()
        system.rate(rating)
    system.close()
    return recorder.path


@pytest.fixture
def setup(tmp_path):
    sessions = [record_session(tmp_path / "ds", seed) for seed in (1, 2)]
    ledger = ProvenanceLedger(KEY, tmp_path / "ledger.jsonl")
    return TrainingPipeline(ledger, KEY, tmp_path / "models"), ledger, sessions


def test_a_pipeline_run_writes_the_whole_chain(setup):
    pipeline, ledger, sessions = setup
    result = pipeline.train(TemporalPredictor(7), sessions, device="cpu")
    kinds = [e["kind"] for e in ledger.entries]
    assert kinds == ["genesis", "dataset", "training_set", "training_run", "training_set", "training_run", "model_version"]
    runs = [r for r in result["runs"] if "block" in r]
    assert [(r["mode"], r["records"]) for r in runs] == [("memory", 2), ("imagination", 2)]   # per-session matching
    assert all(r["compute"]["device"] == "cpu" and r["compute"]["seconds"] >= 0 for r in runs)
    release = ledger.entries[-1]
    assert result["model_version"] == "1.1.0" and release["metrics"]["version"] == "1.1.0"
    assert release["links"] == [ledger.entries[3]["hash"], ledger.entries[5]["hash"]]
    assert [e["kind"] for e in ledger.lineage(release["hash"])] == \
        ["model_version", "training_run", "training_set", "training_run", "training_set", "dataset"]
    assert ledger.verify()[0] and ledger.entries[1]["metrics"]["ratings"] == 4


def test_versions_continue_from_the_verified_latest_model(setup):
    pipeline, ledger, sessions = setup
    first = pipeline.train(TemporalPredictor(7), sessions[:1], device="cpu")
    second = pipeline.train(TemporalPredictor(7), sessions, device="cpu")
    third = pipeline.train(TemporalPredictor(7), sessions, modes=("all",), device="cpu")
    assert (first["model_version"], second["model_version"], third["model_version"]) == ("1.1.0", "1.2.0", "1.3.0")
    v12, v13 = ledger.latest("model_version", version="1.2.0"), ledger.latest("model_version", version="1.3.0")
    assert v13["metrics"]["parent_version"] == "1.2.0"
    assert sum(e["kind"] == "dataset" for e in ledger.entries) == 2               # same sessions: same dataset block
    assert v12["hash"] in [e["hash"] for e in ledger.lineage(v13["hash"])]        # v1.3 traces back through v1.2
    model, entry = pipeline.latest_model(TemporalPredictor)
    assert model.version_text == "1.3.0" and model.fingerprint() == entry["model_sha256"]
    checkpoint = pipeline.model_dir / entry["metrics"]["checkpoint"]
    checkpoint.write_bytes(checkpoint.read_bytes() + b"x")
    with pytest.raises(ValueError, match="doesn't match its SHA-256"):
        pipeline.latest_model(TemporalPredictor)


def test_the_chain_reads_block_by_block(setup):
    pipeline, ledger, sessions = setup
    pipeline.train(TemporalPredictor(7), sessions, device="cpu")
    text = "\n".join(ledger.render())
    assert text.startswith("Block 0  Genesis") and "    ↓\nBlock 1  Dataset personal v1: 2 sessions" in text
    assert "Memory-model training: TemporalPredictor on 2 ratings" in text and "Imagination-model training" in text
    assert "Block 6  Model v1.1.0 (TemporalPredictor)" in text and "(from blocks 3, 5)" in text
    assert text.endswith("Chain verified (7 blocks)")


def test_links_must_point_backwards(tmp_path):
    ledger = ProvenanceLedger(KEY, tmp_path / "l.jsonl")
    with pytest.raises(ValueError, match="already in the ledger"):
        ledger.append("training_run", data=None, model_sha256="", config={}, metrics={}, links=["f" * 64])
    first = ledger.append("dataset", data=None, model_sha256="", config={}, metrics={})
    ledger.append("training_run", data=None, model_sha256="", config={}, metrics={}, links=[first["hash"]])
    ledger.entries[2]["links"] = [ledger.entries[2]["hash"]]
    ok, problems = ledger.verify()
    assert not ok and "entry 2: links to a block that isn't before it" in problems


def test_compute_is_recorded_honestly():
    info = compute_info("cpu")
    assert info["device"] == "cpu" and info["cpu_cores"] and "host_os" in info
    if importlib.util.find_spec("torch"):
        import torch
        if not torch.cuda.is_available():
            with pytest.raises(RuntimeError, match="no CUDA GPU"):
                resolve_device("cuda")
    assert resolve_device("cpu") == "cpu"


def test_a_numpy_model_refuses_gpu_training(setup, monkeypatch):
    pipeline, _, sessions = setup
    monkeypatch.setattr("neurovisual.training.resolve_device", lambda d: "cuda")
    with pytest.raises(RuntimeError, match="trains on the CPU only"):
        pipeline.train(TemporalPredictor(7), sessions, device="cuda")


@pytest.mark.skipif(not importlib.util.find_spec("torch"), reason="PyTorch isn't installed")
def test_the_pytorch_model_trains_from_sessions_another_model_recorded(setup):
    from neurovisual.examples.torch_predictor import GRUPredictor

    pipeline, ledger, sessions = setup
    result = pipeline.train(GRUPredictor(7), sessions, device="auto")
    runs = [r for r in result["runs"] if "block" in r]
    assert all(r["objective_after"] >= r["objective_before"] for r in runs)
    model, entry = pipeline.latest_model(GRUPredictor)
    assert model.version_text == "1.1.0" and entry["metrics"]["checkpoint"].endswith(".pt")
    state = model.predict([np.zeros(7)] * 3, VisualMode.MEMORY, None, 1.0, 0.0)
    assert state.context.shape == (32, 7)                                        # its own input, rebuilt from features
