"""node_supervisor: report timing, restart backoff, totals across restarts,
report contents, archive rotation/pruning, and a real run of 2 node
processes with one killed and restarted."""
import datetime as dt
import json
import os
import time

import node_supervisor as sup


def test_next_report_time():
    d = dt.datetime(2026, 9, 26, 7, 30)
    assert sup.next_report_time(d, 8, dt.date(2026, 9, 25)) == dt.datetime(2026, 9, 26, 8, 0)
    late = dt.datetime(2026, 9, 26, 9, 15)       # PC was off at 8:00 -> due now
    assert sup.next_report_time(late, 8, dt.date(2026, 9, 25)) == late
    assert sup.next_report_time(late, 8, dt.date(2026, 9, 26)) == dt.datetime(2026, 9, 27, 8, 0)


def test_restart_backoff_grows_and_caps():
    assert [sup.restart_delay(n) for n in (1, 2, 3, 4)] == [5, 10, 20, 40]
    assert sup.restart_delay(20) == 300


def _snap(node_id, boot, mined, audits=(), chain_ok=True, started=0.0, updated=3600.0):
    return {"node_id": node_id, "boot_id": boot, "started_at": started, "updated_at": updated,
            "stats": {"blocks_mined": mined, "blocks_verified": 2 * mined},
            "chain_ok": chain_ok, "chain_msg": "x",
            "work": {"stats": {"work_done:audit": len(audits)}, "recent_audits": list(audits)}}


def test_totals_add_up_across_restarts():
    snaps = {"a": _snap(0, "a", 10), "b": _snap(0, "b", 5), "c": _snap(1, "c", 7)}
    per = sup.merge_totals(snaps)
    assert per[0]["starts"] == 2 and per[0]["stats"]["blocks_mined"] == 15
    assert per[0]["uptime_seconds"] == 7200
    assert per[1]["stats"]["blocks_verified"] == 14


def test_report_ok_and_needs_attention():
    good = {"a": _snap(0, "a", 3, audits=[{"ok": True, "target": 1, "by": 0}]), "b": _snap(1, "b", 3)}
    md, ok, reasons = sup.build_report(dt.date(2026, 9, 26), 0, 3600, good, [], {"ok": True, "summary": "5 passed"},
                                       {}, 2)
    assert ok and "Overall: OK" in md and "| node-0 |" in md and "5 passed" in md

    bad_audit = {"ok": False, "target": 1, "by": 0, "round": 4, "problems": ["block #2: signature invalid"]}
    bad = {"a": _snap(0, "a", 3, audits=[bad_audit]), "b": _snap(1, "b", 3, chain_ok=False)}
    crashes = [{"node": 1, "code": 1, "at": 100.0}] * 3
    md, ok, reasons = sup.build_report(dt.date(2026, 9, 26), 0, 3600, bad, crashes,
                                       {"ok": False, "summary": "1 failed", "failures": ["FAILED t::x"]},
                                       {1: ["Traceback (most recent call last):"]}, 3)
    assert not ok and "NEEDS ATTENTION" in md
    text = " ".join(reasons)
    for expected in ("node-2 never reported", "node-1's own chain failed", "audit", "exited unexpectedly 3",
                     "1 failed"):
        assert expected in text, expected
    assert "signature invalid" in md and "Traceback" in md


def test_rotate_keeps_keys_and_prune_removes_old(tmp_path):
    cfg = sup.Config(base_dir=str(tmp_path), node_count=1, python="python")
    nd = cfg.node_dir(0)
    os.makedirs(os.path.join(nd, "keys"))
    os.makedirs(cfg.logs_dir)
    for name in ("chain_node-0.json", "identity_node-0.dna.json", "tokens_node-0.json", "status.json",
                 os.path.join("keys", "node-0.ed25519.pem")):
        open(os.path.join(nd, name), "w").close()
    open(os.path.join(cfg.logs_dir, "node-0.log"), "w").close()

    dest = sup.rotate(cfg, dt.date(2026, 9, 26))
    assert sorted(os.listdir(os.path.join(dest, "node-0"))) == sorted(
        ["chain_node-0.json", "identity_node-0.dna.json", "tokens_node-0.json", "status.json", "node-0.log"])
    assert os.listdir(nd) == ["keys"] and os.listdir(os.path.join(nd, "keys")) == ["node-0.ed25519.pem"]

    os.makedirs(os.path.join(cfg.archive_dir, "2026-07-01"))
    os.makedirs(os.path.join(cfg.archive_dir, "not-a-date"))
    assert sup.prune_archive(cfg, dt.date(2026, 9, 26)) == ["2026-07-01"]
    assert sorted(os.listdir(cfg.archive_dir)) == ["2026-09-26", "not-a-date"]


def test_single_instance_lock(tmp_path):
    a = sup.SingleInstance(str(tmp_path / "s.lock"))
    b = sup.SingleInstance(str(tmp_path / "s.lock"))
    assert a.acquire() and not b.acquire()
    a.fh.close()
    assert b.acquire()
    b.fh.close()


def test_real_nodes_restart_after_crash_and_daily_report(tmp_path):
    cfg = sup.Config(base_dir=str(tmp_path / "auto"), node_count=2, base_port=19780,
                     heartbeat_seconds=1, round_seconds=4, takeover_seconds=1,
                     run_tests=False, run_self_tests=False, notify=False)
    s = sup.Supervisor(cfg)
    s.load_keys()
    try:
        s.check_nodes(time.time())                 # starts both
        time.sleep(12)
        s.collect_status()
        victim = s.nodes[1]
        victim.proc.kill()                         # simulate a crash
        victim.proc.wait()
        s.check_nodes(time.time())
        assert victim.proc is None and s.state["crashes"][-1]["node"] == 1
        s.check_nodes(time.time() + 6)             # past the 5s backoff -> restarted
        assert victim.proc is not None and victim.proc.poll() is None
        time.sleep(8)

        path = s.daily(dt.datetime.now())          # stops nodes, reports, rotates
        report = open(path, encoding="utf-8").read()
        assert "| node-0 |" in report and "| node-1 |" in report
        assert "node-1 exited with code" in report
        assert "| node-1 | " in report and "| 2 |" in report.split("| node-1 |")[1].split("\n")[0]
        per = sup.merge_totals(json.load(open(cfg.path("period_totals.json")))["snapshots"])
        assert per == {}                            # period reset after the report
        day = dt.date.today().isoformat()
        archived = os.listdir(os.path.join(cfg.archive_dir, day, "node-0"))
        assert "chain_node-0.json" in archived and "node-0.log" in archived
        assert os.path.exists(os.path.join(cfg.node_dir(0), "keys", "node-0.ed25519.pem"))
        assert all(n.proc is None for n in s.nodes)

        s.check_nodes(time.time())                 # nodes come back after the report
        assert all(n.proc is not None for n in s.nodes)
    finally:
        s.stop_nodes()


def test_keys_read_in_process_match_the_cli(tmp_path):
    import subprocess, sys
    cfg = sup.Config(base_dir=str(tmp_path), node_count=2, python=sys.executable)
    s = sup.Supervisor(cfg)
    s.load_keys()
    out = subprocess.run([sys.executable, os.path.join(sup.PROJECT_DIR, "run_node_cli.py"), "--id", "1",
                          "--workdir", cfg.node_dir(1), "--show-key"], capture_output=True, text=True)
    assert s.keys[1] in out.stdout and s.keys[0] != s.keys[1]


def test_only_node_zero_publishes_the_research_outbox(tmp_path):
    cfg = sup.Config(base_dir=str(tmp_path), node_count=2, python="python")
    s = sup.Supervisor(cfg)
    first, second = s.node_command(0), s.node_command(1)
    assert first[first.index("--provenance-queue") + 1] == cfg.path("research-outbox")
    assert "--work-sharing" in first
    assert "--provenance-queue" not in second


def _loop_supervisor(tmp_path, monkeypatch):
    cfg = sup.Config(base_dir=str(tmp_path), node_count=0, run_tests=False, run_self_tests=False, notify=False)
    s = sup.Supervisor(cfg)
    monkeypatch.setattr(sup.time, "sleep", lambda secs: None)
    monkeypatch.setattr(s, "stop_orphans", lambda: None)
    return cfg, s


def test_loop_survives_an_unexpected_error(tmp_path, monkeypatch, caplog):
    cfg, s = _loop_supervisor(tmp_path, monkeypatch)
    calls = []

    def flaky(now):
        calls.append(now)
        if len(calls) == 1:
            raise OSError("disk hiccup")
        open(cfg.path("supervisor.stop"), "w").close()

    monkeypatch.setattr(s, "check_nodes", flaky)
    monkeypatch.setattr(s, "report_due", lambda now: False)
    with caplog.at_level("INFO", logger="supervisor"):
        assert s.run() == 0
    assert len(calls) == 2
    assert "error in supervisor loop" in caplog.text


def test_failing_report_is_not_retried_in_a_tight_loop(tmp_path, monkeypatch, caplog):
    cfg, s = _loop_supervisor(tmp_path, monkeypatch)
    attempts = []

    def broken_daily(now):
        attempts.append(now)
        raise RuntimeError("report broke")

    ticks = []

    def tick(now):
        ticks.append(now)
        if len(ticks) == 3:
            open(cfg.path("supervisor.stop"), "w").close()

    monkeypatch.setattr(s, "daily", broken_daily)
    monkeypatch.setattr(s, "check_nodes", tick)
    s.state["last_report_date"] = "2000-01-01"
    s.cfg.report_hour = 0
    with caplog.at_level("INFO", logger="supervisor"):
        s.run()
    assert len(attempts) == 1 and "daily report failed" in caplog.text
    assert s.state["last_report_date"] == dt.date.today().isoformat()
