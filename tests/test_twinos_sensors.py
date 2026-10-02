"""TwinOS part 2: signal sources, the twin's state against a personal baseline, the handlers that do real
work (context, tests, training, MicroPython) and the sense/learn commands."""
import json
import sys

import pytest

from neurovisual.signals import BANDS
from neurovisual.sensors import SensorUnavailable
from tests.test_neurovisual_lineage import KEY, record_session
from tests.test_twinos import ask, make_paths
from twinos.__main__ import main
from twinos.node import AgentNode
from twinos.sensors import EEGSource, MicroPythonSerial, Observation, PluginSource, Unavailable
from twinos.state import StateEstimator


class FakeRF:
    """A plugin driver, loaded by reference like a real one."""

    def __init__(self, values=None):
        self.values = values or {"range_m": 1.5, "doppler_hz": 0.2}

    def read(self):
        return dict(self.values)


class BrokenRF:
    def read(self):
        raise OSError("radar unplugged")


class Scripted:
    """A source that returns the given feature values in turn."""

    def __init__(self, name, values):
        self.name, self.values, self.i = name, values, 0

    def observe(self):
        value = self.values[min(self.i, len(self.values) - 1)]
        self.i += 1
        return Observation(self.name, float(self.i), True, {"a": value, "b": 1.0}, 1.0)

    def close(self):
        pass


def steady(n, base=10.0):
    return [base + (0.1 if i % 2 else -0.1) for i in range(n)]


# -- sources -------------------------------------------------------------------------------------------
def test_simulated_eeg_gives_band_power_features():
    source = EEGSource.open("simulated")
    o = source.observe()
    assert o.available and list(o.features) == list(BANDS) and o.quality == 1.0 and o.detail == "simulated"
    with pytest.raises(ValueError, match="EEG sources"):
        EEGSource.open("telepathy")


def test_plugin_sources_load_by_reference_and_report_failures_honestly():
    good = PluginSource("rf", "tests.test_twinos_sensors:FakeRF")
    assert good.observe().features == {"range_m": 1.5, "doppler_hz": 0.2}
    nan = PluginSource("rf", "tests.test_twinos_sensors:FakeRF", values={"a": float("nan"), "b": 1.0})
    assert nan.observe().quality == 0.5
    broken = PluginSource("rf", "tests.test_twinos_sensors:BrokenRF").observe()
    assert not broken.available and "radar unplugged" in broken.detail
    missing = Unavailable("audio", "no driver").observe()
    assert not missing.available and missing.detail == "no driver"


# -- state ---------------------------------------------------------------------------------------------
def test_nothing_connected_means_no_confidence_and_no_change():
    estimator = StateEstimator()
    for _ in range(30):
        state = estimator.update([Unavailable("eeg", "x").observe(), Unavailable("rf", "y").observe()])
    assert state.confidence == 0.0 and state.changes == []


def test_a_sustained_deviation_is_one_change_and_a_spike_is_none():
    estimator = StateEstimator(threshold=3.0, sustain=3, warmup=10)
    source = Scripted("eeg", steady(12) + [30.0] + steady(4) + [30.0] * 6)
    changes = []
    for _ in range(23):
        state = estimator.update([source.observe()])
        changes += [(source.i, c) for c in state.changes]
    assert changes == [(20, "eeg")]          # the single spike at 13 isn't a change; the third high reading is
    assert state.confidence == 1.0


def test_a_lasting_shift_becomes_the_new_baseline():
    estimator = StateEstimator(threshold=3.0, sustain=3, warmup=10)
    source = Scripted("eeg", steady(12) + [30.0 + (0.1 if i % 2 else -0.1) for i in range(200)])
    deviations = [estimator.update([source.observe()]).sources["eeg"].deviation for _ in range(212)]
    assert deviations[14] > 3 and deviations[-1] < 3


# -- handlers ------------------------------------------------------------------------------------------
@pytest.fixture
def pair(tmp_path):
    paths = make_paths(tmp_path)
    twin = AgentNode(home=tmp_path / "twin", paths=paths)
    coder = AgentNode(home=tmp_path / "coder", paths=paths, name="Coder", agent_type="coding_agent")
    twin.trust.pin(coder.identity.agent_id, coder.identity.public_key)
    return twin, coder


def test_peers_see_the_real_handlers_and_only_status_is_automatic(pair):
    twin, coder = pair
    caps = ask(coder, twin, "CAPABILITY_REQUEST", {})["payload"]
    assert caps == {"task_types": ["gpu_training", "run_tests", "status", "update_context"], "automatic": ["status"]}
    reply = ask(coder, twin, "TASK_REQUEST", {"task_type": "run_tests", "description": "run them",
                                              "parameters": {"tests": "tests/test_twinos.py"}})
    assert reply["message_type"] == "APPROVAL_REQUIRED"


def test_update_context_keeps_summaries_and_refuses_personal_information(pair):
    twin, coder = pair
    good = twin.run_local("update_context", "", {"category": "project", "summary": "Working on TwinOS part 2"})
    assert good.status == "completed"
    entries = [json.loads(line) for line in twin.context_path.read_text().splitlines()]
    assert entries[0]["summary"] == "Working on TwinOS part 2" and entries[0]["source_agent"] == twin.identity.agent_id
    personal = twin.run_local("update_context", "", {"category": "contact", "summary": "email me at someone@example.com"})
    assert personal.status == "failed" and "personal information" in personal.result["error"]
    for params in ({"category": "Bad Category!", "summary": "x"}, {"category": "ok", "summary": ""},
                   {"category": "ok", "summary": "x" * 501}):
        assert twin.run_local("update_context", "", params).status == "failed"
    assert len(twin.context_path.read_text().splitlines()) == 1


def test_run_tests_runs_only_named_test_files(tmp_path):
    paths = make_paths(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    (tmp_path / "tests" / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    twin = AgentNode(home=tmp_path / "twin", paths=paths)
    ok = twin.run_local("run_tests", "", {"tests": "tests/test_ok.py"})
    assert ok.status == "completed" and "1 passed" in ok.result["summary"]
    bad = twin.run_local("run_tests", "", {"tests": ["tests/test_bad.py"]})
    assert bad.status == "failed" and "1 failed" in bad.result["summary"]
    for target in ("../secret.py", "tests/../x.py", "-k evil", "tests/test_ok.py --pdb", "", "tests/x.py; rm -rf /"):
        result = twin.run_local("run_tests", "", {"tests": target}).result
        assert result["success"] is False and "error" in result


def test_training_needs_recorded_sessions_and_then_releases_a_version(pair):
    twin, _ = pair
    empty = twin.run_local("gpu_training", "", {"device": "cpu"})
    assert empty.status == "failed" and "no recorded sessions" in empty.result["error"]
    store = twin.paths.autonomous / "neurovisual"
    store.mkdir(parents=True, exist_ok=True)
    (store / "dataset.key").write_bytes(KEY)
    for seed in (1, 2):
        record_session(store / "datasets", seed)
    trained = twin.run_local("gpu_training", "", {"device": "cpu"})
    assert trained.status == "completed", trained.result
    assert trained.result["sessions"] == 2 and trained.result["model_version"]
    assert {r["mode"] for r in trained.result["runs"]} == {"memory", "imagination"}
    assert all(r["device"] == "cpu" for r in trained.result["runs"] if "device" in r)
    assert twin.run_local("gpu_training", "", {"device": "tpu"}).status == "failed"


class FakeBoard:
    def __init__(self, replies):
        self.replies, self.written = list(replies), []

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass

    def readline(self):
        return self.replies.pop(0) if self.replies else b""

    def close(self):
        pass


def test_micropython_commands_go_to_the_attached_board(pair):
    twin, coder = pair
    assert "micropython_command" not in twin.capabilities()["task_types"]
    board = FakeBoard([b'{"ok": true, "temp_c": 21.5}\n'])
    twin.attach_micropython(MicroPythonSerial("COM9", connection=board))
    assert "micropython_command" in twin.capabilities()["task_types"]
    task_id = ask(coder, twin, "TASK_REQUEST", {"task_type": "micropython_command", "description": "read temp",
                                                "parameters": {"command": "status"}})["payload"]["task_id"]
    task = twin.decide(task_id, approve=True)
    assert task.status == "completed" and task.result["reply"]["temp_c"] == 21.5
    assert json.loads(board.written[0]) == {"command": "status"}
    silent = twin.run_local("micropython_command", "", {"command": "status"})
    assert silent.status == "failed" and "no reply" in silent.result["error"]


def test_micropython_without_pyserial_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "serial", None)
    with pytest.raises(SensorUnavailable, match="pyserial"):
        MicroPythonSerial("COM9")


# -- the sensing loop ----------------------------------------------------------------------------------
def test_a_state_change_is_proposed_not_acted_on(pair):
    twin, _ = pair
    source = Scripted("eeg", steady(25) + [30.0] * 5)
    states = twin.sense([source], steps=30, interval=0, estimator=StateEstimator(warmup=10))
    assert sum(len(s.changes) for s in states) == 1
    [proposed] = twin.tasks.waiting()
    assert proposed.task_type == "update_context" and proposed.source_agent == twin.identity.agent_id
    assert "eeg signals deviated" in proposed.parameters["summary"]
    assert not twin.context_path.exists()                       # nothing written until the owner approves
    twin.decide(proposed.task_id, approve=True)
    assert "state_change" in twin.context_path.read_text()
    kinds = [e["kind"] for e in twin.ledger().entries]
    assert kinds.count("state_change") == 1 and twin.ledger().verify()[0]


def test_sense_and_learn_commands(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("twinos.node.Paths", lambda: make_paths(tmp_path))
    home = str(tmp_path / "cli")
    assert main(["--home", home, "sense", "--eeg", "none", "--seconds", "0.3", "--hz", "10"]) == 0
    out = capsys.readouterr().out
    assert "eeg unavailable" in out and "rf unavailable" in out and "confidence 0.00" in out
    assert main(["--home", home, "sense", "--rf", "no.such.module:Driver", "--seconds", "0.1"]) == 1
    assert main(["--home", home, "learn", "--device", "cpu"]) == 1
    assert "no recorded sessions" in capsys.readouterr().out
    assert main(["--home", home, "context"]) == 0
