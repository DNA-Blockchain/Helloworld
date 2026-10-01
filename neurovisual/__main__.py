"""A simulated session: memories, memory mode, imagination mode, ratings, a learning burst, provenance."""
from __future__ import annotations

import argparse
from pathlib import Path

from .model import VisualMode
from .provenance import ProvenanceLedger, load_or_create_key
from .system import NeurovisualSystem

STORE = Path(__file__).resolve().parent.parent / "autonomous" / "neurovisual"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Simulated PNV-MIM session (no hardware, no image generator).")
    p.add_argument("--seconds", type=float, default=3.0, help="seconds per mode (default 3)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-ledger", action="store_true", help="don't write the provenance ledger")
    a = p.parse_args(argv)

    ledger = None if a.no_ledger else ProvenanceLedger(load_or_create_key(STORE / "ledger.key"),
                                                       STORE / "provenance.jsonl")
    system = NeurovisualSystem(ledger=ledger, seed=a.seed, learn_interval=float("inf"))
    system.add_memory("event_001", "Outdoor event near sunset with several familiar people.",
                      {"environment": "outdoor", "time": "sunset", "event_type": "social"})
    system.add_memory("event_002", "A trip through a familiar landscape.", {"environment": "landscape"})

    for mode, rating in ((VisualMode.MEMORY, 0.8), (VisualMode.IMAGINATION, 0.6)):
        system.set_mode(mode, "event_001")
        timing = system.run(a.seconds)
        state = system.states[-1].summary()
        print(f"{mode.value:<11} {timing['steps']} steps, latency mean {timing['mean_latency_ms']:.2f} ms "
              f"max {timing['max_latency_ms']:.2f} ms, {timing['deadline_misses']} missed deadlines; "
              f"evidence {state['evidence']} inference {state['inference']} generative {state['generative']}, "
              f"confidence {state['confidence']}")
        system.rate(rating, "simulated rating")

    system.maybe_learn(force=True)
    system.wait_for_learning()
    for burst in system.bursts:
        print(f"learning burst: {burst['records']} ratings, {burst['epochs']} epochs, {burst['seconds']} s; "
              f"objective {burst['objective_before']} -> {burst['objective_after']}; "
              f"model {burst['old_version']} -> {burst['new_version']}")
    if ledger:
        ok, problems = ledger.verify()
        print(f"provenance ledger: {len(ledger.entries)} entries, {'verified' if ok else 'BROKEN: ' + '; '.join(problems)}"
              f" ({ledger.path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
