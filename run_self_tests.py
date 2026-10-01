#!/usr/bin/env python3
"""
run_self_tests.py — runs every component's own built-in self-test (and the
two live network runs) in one shot, non-interactively, and checks which
components depend on ANTHROPIC_API_KEY.

This is not the pytest suite (python -m pytest) and not run_all.py (the
project's main entry point, which launches the full system). It runs each
file's own `python <file>` self-check in sequence, saves each output to a
log, and prints one summary. node_supervisor.py also runs it for the
daily report.

ANTHROPIC_API_KEY: before running anything, every listed file's source is
scanned for a reference to the key. Only validate_api_key.py (whose job
is checking that key) is expected to reference it; it runs last and
separately, and its result never counts as a failure.

Components listed here that aren't in this project yet are reported as
MISSING, not FAIL, so a missing file doesn't make every run look broken.

Usage:
    python run_self_tests.py
    python run_self_tests.py --skip-network     skip components that open sockets/ports
    python run_self_tests.py --skip-live-data   skip components that call live external APIs
    python run_self_tests.py --json-out FILE    also write the results as JSON
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

WORKDIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG_DIR = os.path.join(WORKDIR, "self_test_logs")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# (label, file, extra_args, needs_network_sockets, needs_live_external_data)
# "{log_dir}" in an argument is replaced with the log directory.
COMPONENTS = [
    ("DNA<->binary codec (self-test)",             "dna_binary_codec.py",          [], False, False),
    ("X25519/AES-GCM crypto layer (self-test)",    "crypto_layer.py",              [], False, False),
    ("Append-only chain store (self-test)",        "chain_store.py",               [], False, False),
    ("Non-monetary token ledger (self-test)",      "token_ledger.py",              [], False, False),
    ("Offline retry outbox (self-test)",           "outbox_queue.py",              [], False, False),
    ("External chain bridge (self-test)",          "external_chain_bridge.py",     [], False, True),
    ("Region-bounded pipeline (self-test)",        "region_bounded_pipeline.py",   [], False, False),
    ("Cancer gene panel advisor (self-test)",      "cancer_panels.py",             [], False, True),
    ("VCF ingestion (self-test)",                  "vcf_ingestion.py",             [], False, False),
    ("Cancer->remission demo (end to end)",        "cancer_remission_demo.py",     [], False, True),
    ("Pathologist viewer agent (self-test)",       "pathologist_agent.py",         [], False, False),
    ("Consolidated 3-node network (~9s live run)", "run_consolidated_network.py",  [], True, True),
    ("Single CLI node (~4s live run, no peers)",   "run_node_cli.py",
     ["--id", "0", "--port", "9799", "--bind", "127.0.0.1", "--duration", "4",
      "--no-research", "--no-external-info", "--workdir", os.path.join("{log_dir}", "cli_node_data")],
     True, False),
]

API_KEY_CHECK = ("ANTHROPIC_API_KEY validator (separate, informational)", "validate_api_key.py", [], False, False)


def scan_for_api_key_usage(files: list[str], workdir: str = WORKDIR) -> dict[str, bool | None]:
    """Which of these files mention ANTHROPIC_API_KEY in their source
    (None = file not present)."""
    results: dict[str, bool | None] = {}
    for fname in files:
        try:
            with open(os.path.join(workdir, fname), encoding="utf-8", errors="replace") as f:
                results[fname] = "ANTHROPIC_API_KEY" in f.read()
        except FileNotFoundError:
            results[fname] = None
    return results


def run_component(label: str, fname: str, args: list[str], log_path: str,
                  timeout: float, workdir: str = WORKDIR) -> tuple[str, float]:
    """Returns ("PASS" | "FAIL" | "MISSING", seconds)."""
    if not os.path.exists(os.path.join(workdir, fname)):
        return "MISSING", 0.0
    start = time.time()
    # UTF-8 for the child's output: redirected to a file, Python on Windows
    # would otherwise encode it as cp1252 and a component printing e.g. a
    # check mark would crash for a reason that has nothing to do with it.
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    with open(log_path, "w", encoding="utf-8") as log_f:
        log_f.write(f"=== {label} ===\ncommand: python {fname} {' '.join(args)}\n\n")
        log_f.flush()
        try:
            proc = subprocess.run([sys.executable, fname, *args], cwd=workdir, stdout=log_f,
                                  stderr=subprocess.STDOUT, timeout=timeout, env=env,
                                  creationflags=NO_WINDOW)
            status = "PASS" if proc.returncode == 0 else "FAIL"
        except subprocess.TimeoutExpired:
            log_f.write(f"\n[run_self_tests.py] TIMED OUT after {timeout:.0f}s\n")
            status = "FAIL"
    return status, time.time() - start


def run_all(log_dir: str, skip_network: bool = False, skip_live_data: bool = False,
            timeout: float = 60.0, components=None, workdir: str = WORKDIR,
            echo=print) -> dict:
    components = COMPONENTS if components is None else components
    os.makedirs(log_dir, exist_ok=True)

    files = [c[1] for c in components] + [API_KEY_CHECK[1]]
    key_usage = scan_for_api_key_usage(files, workdir)
    unexpected = [f for f, used in key_usage.items() if used and f != API_KEY_CHECK[1]]

    echo("--- ANTHROPIC_API_KEY dependency scan ---")
    for fname, used in key_usage.items():
        echo(f"  {fname}: " + ("not present" if used is None else
                               "references it" if used else "does not reference it"))
    if unexpected:
        echo(f"[NOTE] these components reference the key: {unexpected}")

    results = []
    for label, fname, extra, needs_net, needs_live in components:
        args = [a.replace("{log_dir}", log_dir) for a in extra]
        if (skip_network and needs_net) or (skip_live_data and needs_live):
            reason = "--skip-network" if skip_network and needs_net else "--skip-live-data"
            echo(f"[SKIP]    {label} ({reason})")
            results.append({"label": label, "file": fname, "status": "SKIP", "seconds": 0.0})
            continue
        log_path = os.path.join(log_dir, fname.replace(".py", "") + ".log")
        status, secs = run_component(label, fname, args, log_path, timeout, workdir)
        where = "" if status == "MISSING" else f" in {secs:.1f}s - {log_path}"
        echo(f"[{status:<7}] {label}{where}")
        results.append({"label": label, "file": fname, "status": status, "seconds": round(secs, 1),
                        "log": None if status == "MISSING" else log_path})

    key_status, key_secs = run_component(API_KEY_CHECK[0], API_KEY_CHECK[1], [],
                                         os.path.join(log_dir, "validate_api_key.log"), timeout, workdir)
    echo(f"[{'INFO' if key_status == 'FAIL' else key_status:<7}] {API_KEY_CHECK[0]}")

    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("PASS", "FAIL", "MISSING", "SKIP")}
    return {
        "results": results,
        "counts": counts,
        "api_key_validator": key_status,
        "components_referencing_api_key": unexpected,
        "ok": counts["FAIL"] == 0,
        "log_dir": log_dir,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run every component's built-in self-test.")
    parser.add_argument("--skip-network", action="store_true", help="skip components needing sockets/ports")
    parser.add_argument("--skip-live-data", action="store_true", help="skip components calling live external APIs")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, help="where per-component logs go")
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds allowed per component")
    parser.add_argument("--json-out", help="also write the results to this JSON file")
    args = parser.parse_args(argv)

    print("=" * 78)
    print("run_self_tests.py - every component's own self-test, non-interactively")
    print(f"Logs: {args.log_dir}")
    print("=" * 78)
    summary = run_all(args.log_dir, args.skip_network, args.skip_live_data, args.timeout)
    c = summary["counts"]
    print("=" * 78)
    print(f"{c['PASS']} passed, {c['FAIL']} failed, {c['MISSING']} missing, {c['SKIP']} skipped "
          f"(out of {len(summary['results'])} components)")
    if c["MISSING"]:
        print("Missing files: " + ", ".join(r["file"] for r in summary["results"] if r["status"] == "MISSING"))
    print("=" * 78)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
