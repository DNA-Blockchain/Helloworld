"""Training pipeline with provenance: datasets -> training sets -> training runs -> model versions.

One pipeline run writes this chain of blocks to the provenance ledger:

    dataset            "personal" v1: which sessions (keyed digest), steps, ratings, raw EEG or not
      training_set     per mode: SHA-256 of the exact training arrays (context, shown output, rating)
        training_run   memory-model training, then imagination-model training (or "all"): the
                       predictor, epochs, objective before/after, and the compute it ran on
                       (device, GPU or CPU, seconds, samples/s, peak GPU memory)
          model_version  v1.N: fingerprint, checkpoint file and its SHA-256, linked to its runs

Each run starts from the latest model_version of the same predictor (its checkpoint, verified against
the fingerprint in the ledger) unless told to start from scratch. So v1.1 -> v1.2 -> v1.3 builds a
lineage that ledger.lineage() can trace back to the data.

Modes: the training data is split by the mode a rating was given in. With the built-in predictors one
network serves both modes, so "memory-model training" means training on memory-mode ratings.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import numpy as np

from .compute import compute_info, measure, resolve_device
from .datasets import read_session, training_records
from .provenance import ProvenanceLedger


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def training_set_sha256(records: list[dict]) -> str:
    digest = hashlib.sha256()
    for r in records:
        for array in (r["context"], r["neural"], np.asarray([r["rating"]])):
            digest.update(np.ascontiguousarray(array, dtype="<f8").tobytes())
    return digest.hexdigest()


class TrainingPipeline:
    def __init__(self, ledger: ProvenanceLedger, dataset_key: bytes, model_dir: Path):
        self.ledger, self.key, self.model_dir = ledger, dataset_key, Path(model_dir)

    # -- datasets ----------------------------------------------------------------------------------------
    def register_dataset(self, sessions: list[Path], name: str = "personal") -> dict:
        """A dataset block for this exact set of sessions; the same sessions return the existing block."""
        summaries = []
        for path in sorted(sessions):
            header, rows = read_session(path, self.key)
            summaries.append({"session_id": header["session_id"], "sha256": _file_sha256(path),
                              "steps": sum(r["type"] == "step" for r in rows),
                              "ratings": sum(r["type"] == "rating" for r in rows), "raw": header["include_raw"]})
        identity = hashlib.sha256("".join(s["sha256"] for s in summaries).encode()).hexdigest()
        for entry in self.ledger.entries:
            if entry["kind"] == "dataset" and entry["metrics"].get("identity") == identity:
                return entry
        version = 1 + sum(e["kind"] == "dataset" and e["metrics"].get("name") == name for e in self.ledger.entries)
        return self.ledger.append("dataset", data=summaries, model_sha256="", config={"schema": "rabbitsoft-neurovisual-dataset.v1"},
                                  metrics={"name": name, "version": version, "identity": identity,
                                           "sessions": len(summaries), "steps": sum(s["steps"] for s in summaries),
                                           "ratings": sum(s["ratings"] for s in summaries),
                                           "raw_eeg": any(s["raw"] for s in summaries)})

    # -- models ------------------------------------------------------------------------------------------
    def latest_model(self, predictor_class):
        """(model, its model_version block) for the newest checkpoint of this predictor, verified; or (None, None)."""
        entry = self.ledger.latest("model_version", predictor=predictor_class.__name__)
        if entry is None:
            return None, None
        path = self.model_dir / entry["metrics"]["checkpoint"]
        if _file_sha256(path) != entry["metrics"]["checkpoint_sha256"]:
            raise ValueError(f"checkpoint {path.name} doesn't match its SHA-256 in the ledger (changed or replaced)")
        model = predictor_class.load(path)
        if model.fingerprint() != entry["model_sha256"]:
            raise ValueError(f"model loaded from {path.name} doesn't match its fingerprint in the ledger")
        return model, entry

    def train(self, predictor, sessions: list[Path], modes: tuple[str, ...] = ("memory", "imagination"),
              device: str = "auto", dataset_name: str = "personal", start: str = "latest") -> dict:
        """Registers the dataset, trains once per mode, releases one new model version. Returns a summary."""
        device = resolve_device(device)
        accepts_device = "device" in inspect.signature(predictor.trained).parameters
        if device == "cuda" and not accepts_device:
            raise RuntimeError(f"{type(predictor).__name__} trains on the CPU only; use a PyTorch model for GPU training")
        parent = None
        if start == "latest" and hasattr(type(predictor), "load"):
            loaded, parent = self.latest_model(type(predictor))
            predictor = loaded or predictor
        base_version = getattr(predictor, "version", None)
        dataset = self.register_dataset(sessions, dataset_name)
        sessions_rows = [read_session(path, self.key)[1] for path in sorted(sessions)]   # step numbers are per session
        context = getattr(predictor, "context", None)
        runs, model = [], predictor
        for mode in modes:
            records = [rec for rows in sessions_rows for rec in training_records(rows, context, None if mode == "all" else mode)]
            if not records:
                runs.append({"mode": mode, "skipped": "no ratings in this mode"})
                continue
            training_set = self.ledger.append(
                "training_set", data=None, model_sha256="", config={"mode": mode}, links=[dataset["hash"]],
                metrics={"mode": mode, "records": len(records), "sha256": training_set_sha256(records)})
            with measure(device, len(records)) as timing:
                model, metrics = model.trained(records, **({"device": device} if accepts_device else {}))
            compute = {**compute_info(device), **timing}
            run = self.ledger.append(
                "training_run", data=None, model_sha256=model.fingerprint(),
                config={"predictor": type(model).__name__, "mode": mode, "epochs": metrics.get("epochs"),
                        "learning_rate": metrics.get("learning_rate")},
                links=[training_set["hash"]] + ([parent["hash"]] if parent else []),
                metrics={"mode": mode, "predictor": type(model).__name__, "records": len(records),
                         "epochs": metrics.get("epochs"), "objective_before": metrics.get("objective_before"),
                         "objective_after": metrics.get("objective_after"), "compute": compute})
            runs.append({"mode": mode, "block": run["index"], **{k: run["metrics"][k] for k in
                                                                  ("records", "objective_before", "objective_after")},
                         "compute": compute})
        trained_runs = [r for r in runs if "block" in r]
        if not trained_runs:
            raise ValueError("no ratings to train on in the chosen modes")
        if base_version is not None:                      # one release per pipeline run: v1.N -> v1.N+1
            model.version = (base_version[0], base_version[1] + 1, 0)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".pt" if type(model).__module__.endswith("torch_predictor") else ".npz"
        checkpoint = self.model_dir / f"{type(model).__name__}-{model.version_text}-{model.fingerprint()[:12]}{suffix}"
        model.save(checkpoint)
        release = self.ledger.append(
            "model_version", data=None, model_sha256=model.fingerprint(),
            config={"predictor": type(model).__name__}, links=[self.ledger.entries[r["block"]]["hash"] for r in trained_runs],
            metrics={"version": model.version_text, "predictor": type(model).__name__, "checkpoint": checkpoint.name,
                     "checkpoint_sha256": _file_sha256(checkpoint), "dataset": dataset["metrics"]["version"],
                     "parent_version": parent["metrics"]["version"] if parent else None})
        return {"dataset": dataset["index"], "runs": runs, "model_version": model.version_text,
                "model_block": release["index"], "checkpoint": str(checkpoint), "model": model}
