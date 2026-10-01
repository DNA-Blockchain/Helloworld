"""The open neurovisual SDK: plug-in models, generator connectors, live sensors, the game stream and
encrypted session datasets that train any connected model."""
import base64
import importlib.util
import json
import socket
import time

import numpy as np
import pytest

from neurovisual import NeurovisualSystem, ProvenanceLedger, VisualMode
from neurovisual.conditioning import condition
from neurovisual.datasets import (SessionRecorder, export_jsonl, export_npz, read_session, train_from_sessions,
                                  training_records)
from neurovisual.generators import (AsyncRenderer, Automatic1111Generator, ComfyUIGenerator, DiffusersGenerator,
                                    GeneratorRefused, GeneratorUnavailable, HTTPGenerator)
from neurovisual.interfaces import load_plugin
from neurovisual.model import TemporalPredictor
from neurovisual.profiles import profile
from neurovisual.stream import LatentStream

KEY = b"d" * 32
FEATURES = ["delta", "theta", "alpha", "beta", "gamma", "cortisol", "heart_rate"]


def session(tmp_path, steps=20, include_raw=False, frame_steps=8, **kw):
    recorder = SessionRecorder(tmp_path / "ds", KEY, FEATURES, profile="research", include_raw=include_raw,
                               frame_steps=frame_steps)
    system = NeurovisualSystem(seed=0, recorder=recorder, learn_interval=float("inf"), **kw)
    system.add_memory("lake", "my sister's birthday at the lake")
    system.set_mode(VisualMode.MEMORY, "lake")
    for i in range(steps):
        system.step()
        if i in (5, 12):
            system.rate(0.9 if i == 5 else -0.4, "private note about the lake")
    return system, recorder


# -- datasets ------------------------------------------------------------------------------------------------
def test_a_session_is_recorded_encrypted_and_reads_back(tmp_path):
    system, recorder = session(tmp_path)
    summary = system.close()["dataset"]
    assert (summary["steps"], summary["ratings"], summary["frames"]) == (20, 2, 3)     # 8 + 8 + rest
    raw = recorder.path.read_bytes()
    assert b"sister" not in raw and b"private note" not in raw and b"lake" not in raw
    header, rows = read_session(recorder.path, KEY)
    assert header["features"] == FEATURES and header["profile"] == "research"
    steps = [r for r in rows if r["type"] == "step"]
    assert len(steps) == 20 and len(steps[0]["scene"]) == 64 and steps[0]["request"]["seed"] >= 0
    assert [r["rating"] for r in rows if r["type"] == "rating"] == [0.9, -0.4]
    assert any(r["type"] == "anchor" and r["description"] == "my sister's birthday at the lake" for r in rows)


def test_a_tampered_frame_or_wrong_key_is_refused(tmp_path):
    system, recorder = session(tmp_path)
    system.close()
    with pytest.raises(ValueError, match="frame 0 can't be decrypted"):
        read_session(recorder.path, b"x" * 32)
    data = bytearray(recorder.path.read_bytes())
    data[-5] ^= 0xFF
    recorder.path.write_bytes(bytes(data))
    with pytest.raises(ValueError, match="frame 2"):
        read_session(recorder.path, KEY)


def test_raw_eeg_is_recorded_only_when_asked(tmp_path):
    system, recorder = session(tmp_path, steps=3, include_raw=True)
    system.close()
    steps = [r for r in read_session(recorder.path, KEY)[1] if r["type"] == "step"]
    assert np.asarray(steps[0]["raw"]["data"]).shape == (8, 256) and steps[0]["raw"]["sample_rate"] == 256.0


def test_recorded_ratings_train_a_model_and_export_for_any_framework(tmp_path):
    system, recorder = session(tmp_path)
    system.close()
    records = training_records(read_session(recorder.path, KEY)[1])
    assert [r["rating"] for r in records] == [0.9, -0.4] and records[0]["context"].shape == (7,)
    trained, metrics = train_from_sessions(TemporalPredictor(7), [recorder.path], KEY)
    assert metrics["records"] == 2 and trained.version_text == "1.1.0"
    npz = export_npz([recorder.path], KEY, tmp_path / "train.npz")
    arrays = np.load(tmp_path / "train.npz")
    assert npz == {"path": str(tmp_path / "train.npz"), "steps": 20, "ratings": 2}
    assert arrays["scene"].shape == (20, 64) and arrays["context"].shape == (20, 7)
    assert list(arrays["rated_rows"]) == [5, 12] and list(arrays["ratings"]) == [0.9, -0.4]
    lines = export_jsonl([recorder.path], KEY, tmp_path / "train.jsonl")
    assert lines["rows"] == 20 + 2 + 1 and json.loads((tmp_path / "train.jsonl").read_text().splitlines()[0])["session_id"]


def test_closing_records_the_dataset_in_the_ledger(tmp_path):
    ledger = ProvenanceLedger(KEY, tmp_path / "ledger.jsonl")
    system, recorder = session(tmp_path, ledger=ledger)
    summary = system.close()["dataset"]
    entry = ledger.entries[-1]
    assert entry["kind"] == "dataset_recorded" and entry["metrics"] == {"steps": 20, "ratings": 2, "frames": 3}
    assert "lake" not in (tmp_path / "ledger.jsonl").read_text() and summary["sha256"] in json.dumps(summary)


# -- open model slot -----------------------------------------------------------------------------------------
class ExternalModel:
    """A minimal third-party predictor: no training."""
    version_text = "ext-1"

    def __init__(self, feature_dim):
        self.feature_dim = feature_dim

    def predict(self, sequence, mode, anchor, quality, timestamp, event_id=None):
        from neurovisual.model import compose
        return compose(np.full(64, 0.1), np.asarray(sequence[-1]), mode, anchor, quality, timestamp, event_id,
                       self.version_text, np.random.default_rng(0))

    def fingerprint(self):
        return "ext"


def test_any_model_plugs_in_and_a_model_without_training_is_reported(tmp_path):
    model = load_plugin("tests.test_neurovisual_sdk:ExternalModel", feature_dim=7)
    system = NeurovisualSystem(seed=0, predictor=model)
    system.step()
    assert system.states[-1].model_version == "ext-1"
    system.rate(0.5)
    system.maybe_learn(force=True)
    system.wait_for_learning()
    assert system.bursts == [{"records": 1, "skipped": "ExternalModel has no trained()"}]
    with pytest.raises(TypeError, match="can't be the predictor"):
        NeurovisualSystem(predictor=object())
    with pytest.raises(ValueError, match="package.module:attribute"):
        load_plugin("no_colon")


@pytest.mark.skipif(not importlib.util.find_spec("torch"), reason="PyTorch isn't installed")
def test_the_pytorch_example_model_runs_live_and_learns():
    from neurovisual.examples.torch_predictor import GRUPredictor

    system = NeurovisualSystem(seed=0, predictor=GRUPredictor(7), learn_interval=float("inf"))
    for _ in range(5):
        system.step()
    system.rate(1.0)
    system.step()
    system.rate(-0.5)
    system.maybe_learn(force=True)
    system.wait_for_learning(60)
    burst = system.bursts[-1]
    assert burst["objective_after"] > burst["objective_before"] and system.model.version_text == "1.1.0"
    assert system.states[-1].context.shape == (32, 7)


# -- generators ----------------------------------------------------------------------------------------------
def state_for(mode=VisualMode.MEMORY, anchor=True):
    from neurovisual.model import anchor_embedding
    model = TemporalPredictor(7)
    return model.predict([np.ones(7)], mode, anchor_embedding("sunset") if anchor else None, 1.0, 0.0, "e1")


def test_a_state_becomes_a_generator_request():
    memory = condition(state_for(), "a gathering at sunset")
    imagined = condition(state_for(VisualMode.IMAGINATION), "a gathering at sunset")
    assert memory.prompt.startswith("a gathering at sunset, ") and memory.contains_memory_text
    assert imagined.prompt.startswith("an imagined variation of: a gathering at sunset")
    assert memory.guidance > imagined.guidance and imagined.strength > memory.strength
    assert condition(state_for(), "x").seed == condition(state_for(), "x").seed and len(memory.latent) == 64
    assert condition(state_for(anchor=False)).prompt.startswith("an abstract scene")


def test_comfyui_fills_the_workflow_keeping_types():
    sent = []
    workflow = {"3": {"inputs": {"seed": "{{seed}}", "cfg": "{{guidance}}", "text": "{{prompt}} :: style"}}}
    gen = ComfyUIGenerator(workflow, post=lambda url, body, *a: sent.append((url, body)) or {"prompt_id": "p1"})
    request = condition(state_for(), "sunset")
    assert gen.render(request)["prompt_id"] == "p1"
    url, body = sent[0]
    inputs = body["prompt"]["3"]["inputs"]
    assert url == "http://127.0.0.1:8188/prompt" and inputs["seed"] == request.seed and isinstance(inputs["seed"], int)
    assert inputs["text"] == f"{request.prompt} :: style" and inputs["cfg"] == request.guidance


def test_automatic1111_saves_the_image_with_its_fingerprint(tmp_path):
    png = b"\x89PNG fake"
    gen = Automatic1111Generator(out_dir=tmp_path, post=lambda url, body, *a: {"images": [base64.b64encode(png).decode()]})
    result = gen.render(condition(state_for(), "sunset"))
    assert result["status"] == "done" and (tmp_path / result["path"].split("\\")[-1].split("/")[-1]).read_bytes() == png
    with pytest.raises(GeneratorUnavailable, match="no image"):
        Automatic1111Generator(out_dir=tmp_path, post=lambda *a: {"detail": "model not loaded"}).render(condition(state_for()))


def test_a_remote_generator_needs_https_and_a_yes(monkeypatch):
    with pytest.raises(ValueError, match="https"):
        HTTPGenerator("http://example.org/gen")
    asked, sent = [], []
    request = condition(state_for(), "my sister's birthday")
    refused = HTTPGenerator("https://gen.example.org/v1", consent=lambda q: asked.append(q) or False,
                            post=lambda *a: sent.append(a) or {})
    with pytest.raises(GeneratorRefused):
        refused.render(request)
    assert "includes the stored memory's description" in asked[0] and not sent
    monkeypatch.setenv("NV_TEST_KEY", "secret-123")
    ok = HTTPGenerator("https://gen.example.org/v1", api_key_env="NV_TEST_KEY", consent=lambda q: True,
                       post=lambda url, body, headers: sent.append(headers) or {"id": 7})
    assert ok.render(request)["response"] == {"id": 7} and ok.render(request)
    assert sent[0] == {"Authorization": "Bearer secret-123"}                  # asked once, key from env


def test_diffusers_missing_is_reported_with_the_install_command():
    if importlib.util.find_spec("diffusers"):
        pytest.skip("diffusers is installed here")
    with pytest.raises(GeneratorUnavailable, match="pip install diffusers"):
        DiffusersGenerator("any/model")


def test_the_renderer_keeps_live_time_and_reports_errors():
    class Slow:
        calls = 0

        def render(self, request):
            Slow.calls += 1
            time.sleep(0.2)
            if Slow.calls == 2:
                raise RuntimeError("GPU out of memory")
            return {"status": "done", "seed": request.seed}

    renderer = AsyncRenderer(Slow(), min_interval=0.0)
    system = NeurovisualSystem(seed=0, renderer=renderer)
    started = time.perf_counter()
    for _ in range(30):
        assert system.step()["frame"]["status"] == "submitted"
    assert time.perf_counter() - started < 1.0                                # 30 steps never wait for 0.2 s renders
    time.sleep(0.7)
    stats = renderer.stats()
    renderer.close()
    assert stats["dropped"] > 20 and stats["rendered"] >= 1 and stats["errors"] == 1
    assert stats["last_error"] == "RuntimeError: GPU out of memory"


# -- live sensors and the game stream ------------------------------------------------------------------------
@pytest.mark.skipif(not importlib.util.find_spec("brainflow"), reason="BrainFlow isn't installed")
def test_brainflow_synthetic_board_drives_the_system():
    from neurovisual.sensors import BrainFlowEEG

    eeg = BrainFlowEEG(board_id=-1, window_seconds=0.5)
    try:
        system = NeurovisualSystem(eeg=eeg, seed=0)
        result = [system.step() for _ in range(3)][-1]
        assert eeg.rate == 250 and len(eeg.channels) == 16 and result["state"].scene.shape == (64,)
    finally:
        eeg.close()


def test_the_latent_stream_reaches_a_local_game_engine():
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(2)
    stream = LatentStream(port=listener.getsockname()[1])
    system = NeurovisualSystem(seed=0, stream=stream)
    system.step()
    message = json.loads(listener.recv(65535))
    assert message["mode"] == "memory" and len(message["scene"]) == 64 and len(message["camera"]) == 8
    stream.close()
    listener.close()
    with pytest.raises(ValueError, match="allow_remote"):
        LatentStream(host="203.0.113.5")


def test_profiles_set_the_use_case_and_can_be_overridden():
    assert profile("gaming").hz == 30 and profile("gaming").stream and not profile("gaming").record
    assert profile("research").include_raw and profile("research", record=False).record is False
    with pytest.raises(ValueError, match="research, gaming, development"):
        profile("other")
