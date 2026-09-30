"""Swarm verification of the twin's analyses: one node scans, a different node
recomputes, and only results two nodes agree on are accepted."""
import json

import swarm_analysis as swarm
from token_ledger import TokenLedger
from work_sharing import WorkSchedule, WorkTask

from tests.test_work_sharing import FakeClock, _close, _network, _step

BASE = 19760


def test_synthetic_subjects_are_fixed_and_carry_one_difference():
    first, again = swarm.synthetic_subjects(), swarm.synthetic_subjects()
    assert first == again and len(first) == swarm.SYNTHETIC_COUNT
    assert len({s["reference"] for s in first}) == len(first)
    for s in first:
        assert "synthetic" in s["label"] and len(s["reference"]) == swarm.SYNTHETIC_LENGTH
        assert sum(a != b for a, b in zip(s["reference"], s["sample"])) == 1


def test_analysis_digest_is_deterministic_and_subject_specific():
    a, b = swarm.synthetic_subjects()[:2]
    assert swarm.digest(swarm.analyze(a)) == swarm.digest(swarm.analyze(a))
    assert swarm.digest(swarm.analyze(a)) != swarm.digest(swarm.analyze(b))
    analysis = swarm.analyze(a)
    assert analysis["version"] == swarm.ANALYSIS_VERSION and analysis["sirna"]
    json.dumps(analysis)                           # canonical-JSON-able


def test_chain_subjects_are_preferred_when_published(tmp_path):
    assert swarm.all_subjects(tmp_path) == swarm.synthetic_subjects()   # empty chain -> synthetic
    assert swarm.all_subjects(None) == swarm.synthetic_subjects()


def _scan_work(round_no, subject, sha):
    return {"task": f"swarm:{round_no}", "kind": "swarm", "round": round_no,
            "result_provenance": {"summary": {"swarm": {"subject": subject, "analysis_sha256": sha}}}}


def test_check_agrees_with_an_honest_scan_and_catches_a_forged_one():
    task = WorkTask("swarm:3", "swarm", 3, 0.0)
    scanned = swarm.SwarmScan()(task)["swarm"]
    assert scanned["subject"] == "synthetic:3"
    check = swarm.SwarmCheck()
    honest = check(task, _scan_work(3, scanned["subject"], scanned["analysis_sha256"]))
    assert honest["swarm"]["agrees"] is True
    forged = check(task, _scan_work(3, scanned["subject"], "0" * 64))
    assert forged["swarm"]["agrees"] is False
    assert forged["swarm"]["analysis_sha256"] == scanned["analysis_sha256"]
    assert check(task, _scan_work(3, "event:not-on-this-node", "0" * 64)) is None


def test_tally_needs_two_distinct_nodes_and_flags_disagreement():
    tally = swarm.SwarmTally()
    tally.record(_scan_work(1, "synthetic:1", "aa"), 1)
    assert tally.verdict(1)["status"] == "UNCONFIRMED"
    tally.record(_scan_work(1, "synthetic:1", "aa"), 1)      # the same node again is not a second vote
    assert tally.verdict(1)["status"] == "UNCONFIRMED"
    tally.record(_scan_work(1, "synthetic:1", "aa") | {"kind": "swarm_check"}, 2)
    v = tally.verdict(1)
    assert v["status"] == "ACCEPTED" and v["agreeing_nodes"] == ["1", "2"]
    tally.record(_scan_work(1, "synthetic:1", "bb") | {"kind": "swarm_check"}, 3)
    assert tally.verdict(1)["status"] == "DISPUTED"
    tally.record(_scan_work(2, "synthetic:2", "cc"), 1)
    tally.record(_scan_work(2, "synthetic:9", "cc") | {"kind": "swarm_check"}, 2)
    assert tally.verdict(2)["status"] == "DISPUTED"           # same digest, different subject
    assert tally.verdict(99)["status"] == "NOT_SEEN"
    tally.record({"kind": "audit", "round": 5}, 1)            # other work is ignored
    assert 5 not in tally.rounds


def test_check_job_waits_for_the_scan_and_skips_the_scanner():
    sched = WorkSchedule(round_seconds=100, research_every=0, external_every=0, audits=False, swarm_every=1)
    kinds = [t.kind for t in sched.tasks_for_round(4, [1, 2, 3])]
    assert kinds == ["swarm", "swarm_check"]
    assert WorkSchedule().swarm_every == 0                    # off unless asked for


def _swarm_runners(corrupt=False):
    check = swarm.SwarmCheck()
    if corrupt:
        def bad(task, scan_work):
            result = check(task, scan_work)
            return {**result, "swarm": {**result["swarm"], "analysis_sha256": "f" * 64}}
        return {"swarm": swarm.SwarmScan(), "swarm_check": bad}
    return {"swarm": swarm.SwarmScan(), "swarm_check": check}


async def _run_round(tmp_path, runners_for, base):
    clock = FakeClock(1000.0)
    ledger = TokenLedger(store_path=str(tmp_path / "ledger.json"))
    sched = WorkSchedule(round_seconds=100, research_every=0, external_every=0, audits=False, swarm_every=1)
    nodes, managers = _network(tmp_path, 3, clock, ledger, sched=sched, base=base)
    for m in managers:
        m.runners.update(runners_for(m.node.node_id))
        m.swarm = swarm.SwarmTally()
    for nd in nodes:
        await nd.start_server()
    try:
        for offset in (0, 0, 10, 20, 30):
            clock.t = 1000.0 + offset
            await _step(managers, alive={0, 1, 2})
        return managers
    finally:
        await _close(nodes)


async def test_three_nodes_accept_a_result_two_of_them_computed(tmp_path):
    managers = await _run_round(tmp_path, lambda _id: _swarm_runners(), BASE)
    scanner = managers[0].done["swarm:10"]["by"]
    checker = managers[0].done["swarm_check:10"]["by"]
    assert scanner != checker
    for m in managers:
        v = m.swarm.verdict(10)
        assert v["status"] == "ACCEPTED", v
        assert sorted(v["agreeing_nodes"]) == sorted([str(scanner), str(checker)])
        assert v["subject"] == "synthetic:2"                  # round 10 of 8 synthetic subjects
    assert sum(m.stats["work_done:swarm"] for m in managers) == 1
    assert sum(m.stats["work_done:swarm_check"] for m in managers) == 1


async def test_a_node_with_a_corrupted_result_is_caught(tmp_path):
    # Every checker is corrupted, so whichever node checks disagrees with the scan.
    managers = await _run_round(tmp_path, lambda _id: _swarm_runners(corrupt=True), BASE + 10)
    for m in managers:
        v = m.swarm.verdict(10)
        assert v["status"] == "DISPUTED", v
        assert v["digests_seen"] == 2
