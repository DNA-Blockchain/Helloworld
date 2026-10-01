"""Command line for the neurovisual system.

    python -m neurovisual run --profile research            # simulated session, recorded
    python -m neurovisual run --sensor brainflow --board-id -1 --generator comfyui --workflow wf.json
    python -m neurovisual run --predictor neurovisual.examples.torch_predictor:GRUPredictor
    python -m neurovisual sessions                          # recorded datasets
    python -m neurovisual export --format npz --out train.npz
    python -m neurovisual train --predictor neurovisual.examples.torch_predictor:GRUPredictor

`run` without arguments is a simulated development session: two memories, memory mode, imagination mode,
a rating for each, a learning burst, and the provenance ledger checked.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .datasets import SessionRecorder, export_jsonl, export_npz, read_session, train_from_sessions
from .generators import (AsyncRenderer, Automatic1111Generator, ComfyUIGenerator, DiffusersGenerator,
                         HTTPGenerator, PlaceholderGenerator)
from .interfaces import load_plugin
from .model import VisualMode
from .profiles import PROFILES, profile
from .provenance import ProvenanceLedger, load_or_create_key
from .signals import BANDS, SimulatedPhysiology
from .stream import LatentStream
from .system import NeurovisualSystem

STORE = Path(__file__).resolve().parent.parent / "autonomous" / "neurovisual"


def ask(question: str) -> bool:
    return input(f"{question} ").strip().lower() in ("y", "yes")


def feature_dim() -> int:
    return len(BANDS) + len(SimulatedPhysiology().read().values)


def make_sensor(a):
    if a.sensor == "brainflow":
        from .sensors import BrainFlowEEG
        return BrainFlowEEG(board_id=a.board_id, serial_port=a.serial_port)
    if a.sensor == "lsl":
        from .sensors import LSLEEG
        return LSLEEG(stream_type=a.lsl_type)
    return None                                          # the simulated sensor


def make_generator(a):
    out = Path(a.output_dir)
    if a.generator == "comfyui":
        if not a.workflow:
            sys.exit("--generator comfyui needs --workflow (a workflow exported from ComfyUI in API format)")
        return ComfyUIGenerator(a.workflow, url=a.generator_url or "http://127.0.0.1:8188", consent=ask)
    if a.generator == "automatic1111":
        return Automatic1111Generator(url=a.generator_url or "http://127.0.0.1:7860", out_dir=out, consent=ask)
    if a.generator == "diffusers":
        if not a.diffusers_model:
            sys.exit("--generator diffusers needs --diffusers-model (a local path or Hugging Face model id)")
        return DiffusersGenerator(a.diffusers_model, out_dir=out)
    if a.generator == "http":
        if not a.generator_url:
            sys.exit("--generator http needs --generator-url")
        return HTTPGenerator(a.generator_url, api_key_env=a.api_key_env, consent=ask)
    return None


def run(a) -> int:
    p = profile(a.profile, **({"record": a.record} if a.record is not None else {}))
    ledger = None if a.no_ledger else ProvenanceLedger(load_or_create_key(STORE / "ledger.key"), STORE / "provenance.jsonl")
    predictor = load_plugin(a.predictor, feature_dim=feature_dim()) if a.predictor else None
    generator = make_generator(a)
    recorder = SessionRecorder(STORE / "datasets", load_or_create_key(STORE / "dataset.key"),
                               feature_names=list(BANDS) + list(SimulatedPhysiology().read().values), profile=p.name,
                               include_raw=p.include_raw or a.include_raw) if p.record else None
    system = NeurovisualSystem(eeg=make_sensor(a), ledger=ledger, seed=a.seed, learn_interval=float("inf"),
                               predictor=predictor, recorder=recorder,
                               renderer=AsyncRenderer(generator, min_interval=p.render_interval) if generator else None,
                               stream=LatentStream(port=a.stream_port) if p.stream else None)
    if recorder:
        recorder.header["model_fingerprint"] = system.model.fingerprint()
    system.add_memory("event_001", "Outdoor event near sunset with several familiar people.",
                      {"environment": "outdoor", "time": "sunset", "event_type": "social"})
    system.add_memory("event_002", "A trip through a familiar landscape.", {"environment": "landscape"})
    print(f"profile {p.name}: {p.hz:g} Hz, model {type(system.model).__name__} {system.model.version_text}, "
          f"generator {type(generator or PlaceholderGenerator()).__name__}, "
          f"recording {'on' + (' with raw EEG' if recorder and recorder.include_raw else '') if recorder else 'off'}, "
          f"stream {'udp://127.0.0.1:' + str(a.stream_port) if p.stream else 'off'}")
    for mode, rating in ((VisualMode.MEMORY, 0.8), (VisualMode.IMAGINATION, 0.6)):
        system.set_mode(mode, "event_001")
        timing = system.run(a.seconds, hz=p.hz)
        s = system.states[-1].summary()
        print(f"{mode.value:<11} {timing['steps']} steps, latency mean {timing['mean_latency_ms']:.2f} ms "
              f"max {timing['max_latency_ms']:.2f} ms, {timing['deadline_misses']} missed deadlines; evidence "
              f"{s['evidence']} inference {s['inference']} generative {s['generative']}, confidence {s['confidence']}")
        system.rate(rating, "simulated rating")
    system.maybe_learn(force=True)
    system.wait_for_learning()
    for burst in system.bursts:
        if "skipped" in burst:
            print(f"learning burst skipped: {burst['skipped']}")
        else:
            print(f"learning burst: {burst['records']} ratings, {burst['epochs']} epochs, {burst['seconds']} s; "
                  f"objective {burst['objective_before']} -> {burst['objective_after']}; "
                  f"model {burst['old_version']} -> {burst['new_version']}")
    summary = system.close()
    if "renderer" in summary:
        print(f"generator: {summary['renderer']}")
    if "dataset" in summary:
        d = summary["dataset"]
        print(f"dataset: {d['steps']} steps, {d['ratings']} ratings, {d['frames']} encrypted frames -> {d['path']}")
    if ledger:
        ok, problems = ledger.verify()
        print(f"provenance ledger: {len(ledger.entries)} entries, {'verified' if ok else 'BROKEN: ' + '; '.join(problems)}")
    return 0


def session_paths(names: list[str]) -> list[Path]:
    paths = [Path(n) for n in names] if names else sorted((STORE / "datasets").glob("*.nvds"))
    if not paths:
        sys.exit("no recorded sessions (record with: python -m neurovisual run --profile research)")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m neurovisual", description=__doc__.strip().split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    r = sub.add_parser("run", help="a session (simulated unless a sensor is chosen)")
    r.add_argument("--profile", choices=list(PROFILES), default="development")
    r.add_argument("--seconds", type=float, default=3.0, help="seconds per mode (default 3)")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--sensor", choices=["simulated", "brainflow", "lsl"], default="simulated")
    r.add_argument("--board-id", type=int, default=-1, help="BrainFlow board id (-1: synthetic board, no hardware)")
    r.add_argument("--serial-port", default="", help="BrainFlow serial port, e.g. COM3")
    r.add_argument("--lsl-type", default="EEG")
    r.add_argument("--predictor", help="an external model, package.module:Class (gets feature_dim=)")
    r.add_argument("--generator", choices=["placeholder", "comfyui", "automatic1111", "diffusers", "http"], default="placeholder")
    r.add_argument("--generator-url")
    r.add_argument("--workflow", help="ComfyUI workflow (API format) with {{prompt}}, {{seed}}... placeholders")
    r.add_argument("--diffusers-model")
    r.add_argument("--api-key-env", help="environment variable holding the HTTP generator's API key")
    r.add_argument("--output-dir", default=str(STORE / "output"))
    r.add_argument("--record", action=argparse.BooleanOptionalAction, default=None, help="override the profile")
    r.add_argument("--include-raw", action="store_true", help="also record raw EEG windows")
    r.add_argument("--stream-port", type=int, default=9555)
    r.add_argument("--no-ledger", action="store_true")
    sub.add_parser("sessions", help="list recorded session datasets")
    e = sub.add_parser("export", help="decrypt sessions into a training file (plaintext: keep it where you train)")
    e.add_argument("sessions", nargs="*")
    e.add_argument("--format", choices=["npz", "jsonl"], default="npz")
    e.add_argument("--out", required=True)
    t = sub.add_parser("train", help="train a model on the ratings in recorded sessions")
    t.add_argument("sessions", nargs="*")
    t.add_argument("--predictor", help="package.module:Class (default: the built-in model)")
    a = parser.parse_args(argv or ["run"])
    if a.command == "run":
        return run(a)
    key = load_or_create_key(STORE / "dataset.key")
    if a.command == "sessions":
        for path in session_paths([]):
            header, rows = read_session(path, key)
            steps = sum(r["type"] == "step" for r in rows)
            ratings = sum(r["type"] == "rating" for r in rows)
            print(f"{header['session_id']}  profile {header['profile'] or '-'}  {steps} steps  {ratings} ratings  "
                  f"raw EEG {'yes' if header['include_raw'] else 'no'}  {path.stat().st_size / 1e6:.2f} MB")
        return 0
    paths = session_paths(a.sessions)
    if a.command == "export":
        result = (export_npz if a.format == "npz" else export_jsonl)(paths, key, Path(a.out))
        print(f"exported {result} (plaintext; delete it after training)")
        return 0
    from .model import TemporalPredictor

    model = load_plugin(a.predictor, feature_dim=feature_dim()) if a.predictor else TemporalPredictor(feature_dim())
    _, metrics = train_from_sessions(model, paths, key)
    print(f"trained {type(model).__name__} on {metrics['records']} ratings from {len(paths)} sessions: "
          f"objective {metrics['objective_before']} -> {metrics['objective_after']}, "
          f"model {metrics['old_version']} -> {metrics['new_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
