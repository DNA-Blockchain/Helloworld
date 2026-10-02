"""Task handlers that do real work. A node offers a task type only when it has a handler for it.

  status               read_context   this agent's id, type, waiting tasks and the task types it offers
  update_context       write_context  appends {category, summary} to the twin's context
                                      (autonomous/twinos/context.jsonl). A summary that looks like personal
                                      information (research_provenance.personal_information) is refused:
                                      that belongs in the encrypted vault (dna_shell.py data-vault-store).
  run_tests            run_tests      python -m pytest on named test files under tests/, with a time limit
  gpu_training         gpu_compute    neurovisual's training pipeline on the recorded sessions, on CUDA
                                      when available; the training runs and model version go to the
                                      neurovisual provenance ledger with their compute
  micropython_command  micropython    one JSON command to the attached board, and its reply (only offered
                                      when a board is attached)
  research_search      read_context   the project's research reports (rabbitsoft/knowledge.py), by meaning,
                                      with their file and similarity: public research only, nothing personal

Every handler returns {"success": bool, ...}. Only status runs without the owner's approval by default.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from research_provenance import personal_information

CATEGORY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
TEST_TARGET = re.compile(r"^tests/[A-Za-z0-9_/]+\.py(::[A-Za-z0-9_\[\]-]+)*$")
MAX_SUMMARY = 500
MAX_TEST_SECONDS = 900


def update_context(path: Path):
    def handler(task) -> dict:
        category, summary = task.parameters.get("category"), task.parameters.get("summary")
        if not isinstance(category, str) or not CATEGORY.match(category):
            return {"success": False, "error": "category must be lowercase letters, digits and _ (up to 64)"}
        if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY:
            return {"success": False, "error": f"summary must be text of 1 to {MAX_SUMMARY} characters"}
        found = personal_information(f"{category} {summary}")
        if found:
            return {"success": False, "error": "this looks like personal information (" + ", ".join(found) +
                    "); keep it in the encrypted vault, not the twin's context"}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.time(), "category": category, "summary": summary.strip(),
                                "source_agent": task.source_agent, "task_id": task.task_id}) + "\n")
        return {"success": True, "category": category}
    return handler


def research_search(root: Path):
    """The project's own research reports, searched by meaning. Public research only: the reports in
    docs/research/ hold no personal data, so an agent asking a question learns nothing about anyone."""
    def handler(task) -> dict:
        query = task.parameters.get("query") or task.description
        if not isinstance(query, str) or not query.strip():
            return {"success": False, "error": "give something to search for, e.g. {\"query\": \"CRISPR CAR-T remission\"}"}
        try:
            limit = min(10, max(1, int(task.parameters.get("limit", 5))))
        except (TypeError, ValueError):
            return {"success": False, "error": "limit must be a number"}
        from rabbitsoft.assistant import Session
        from rabbitsoft.tools import Paths

        hits = Session(Paths(root=root)).knowledge.search(query.strip())[:limit]
        return {"success": True, "query": query.strip(), "matches": len(hits),
                "sections": [{"title": h["title"], "file": h.get("url", ""), "similarity": round(h["similarity"], 3)}
                             for h in hits],
                "note": "Public research summaries, not medical advice."}
    return handler


def run_tests(root: Path):
    def handler(task) -> dict:
        targets = task.parameters.get("tests", "")
        targets = targets.split() if isinstance(targets, str) else targets
        if not isinstance(targets, list) or not targets or len(targets) > 20:
            return {"success": False, "error": "name 1 to 20 test files, e.g. {\"tests\": \"tests/test_twinos.py\"}"}
        bad = [t for t in targets if not isinstance(t, str) or ".." in t or not TEST_TARGET.match(t)]
        if bad:
            return {"success": False, "error": f"not a test file under tests/: {bad[0]!r}"}
        try:
            seconds = min(MAX_TEST_SECONDS, max(10, int(task.parameters.get("timeout", 600))))
        except (TypeError, ValueError):
            return {"success": False, "error": "timeout must be a number of seconds"}
        command = [sys.executable, "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider"]
        try:
            done = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=seconds)
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"the tests took longer than {seconds} s and were stopped"}
        lines = (done.stdout + done.stderr).strip().splitlines()
        return {"success": done.returncode == 0, "returncode": done.returncode,
                "summary": lines[-1] if lines else "", "tail": lines[-20:]}
    return handler


def gpu_training(store: Path):
    def handler(task) -> dict:
        from neurovisual.model import TemporalPredictor
        from neurovisual.provenance import ProvenanceLedger, load_or_create_key
        from neurovisual.signals import BANDS, SimulatedPhysiology
        from neurovisual.training import TrainingPipeline

        sessions = sorted((store / "datasets").glob("*.nvds"))
        if not sessions:
            return {"success": False, "error": "no recorded sessions (python -m neurovisual run --profile research)"}
        device = task.parameters.get("device", "auto")
        if device not in ("auto", "cpu", "cuda"):
            return {"success": False, "error": "device is auto, cpu or cuda"}
        ledger = ProvenanceLedger(load_or_create_key(store / "ledger.key"), store / "provenance.jsonl")
        model = TemporalPredictor(len(BANDS) + len(SimulatedPhysiology().read().values))
        result = TrainingPipeline(ledger, load_or_create_key(store / "dataset.key"), store / "models").train(
            model, sessions, ("memory", "imagination"), device)
        runs = [{k: r[k] for k in ("mode", "records", "objective_before", "objective_after", "skipped") if k in r}
                | ({"device": r["compute"]["device"], "seconds": r["compute"]["seconds"]} if "compute" in r else {})
                for r in result["runs"]]
        return {"success": True, "model_version": result["model_version"], "sessions": len(sessions), "runs": runs}
    return handler


def micropython_command(device):
    def handler(task) -> dict:
        command = task.parameters.get("command")
        if not isinstance(command, str) or not command:
            return {"success": False, "error": "give the board a command, e.g. {\"command\": \"status\"}"}
        reply = device.send({"command": command, **{k: v for k, v in task.parameters.items() if k != "command"}})
        return {"success": bool(reply.get("ok", True)), "reply": reply}
    return handler
