import hashlib
import json
import sys
import time

from rabbitsoft import integrity, tools
from rabbitsoft.assistant import Session
from tests.test_rabbitsoft import FakeAI, make_os, wait_for


def test_a_tampered_activity_log_is_caught(tmp_path):
    from audit_trail import AuditTrail

    paths = make_os(tmp_path, time.time())
    trail = AuditTrail(str(paths.audit))
    trail.log("test", "first", "local", {"n": 1})
    trail.log("test", "second", "local", {"n": 2})
    assert integrity.activity_log(paths).status == integrity.OK
    paths.audit.write_text(paths.audit.read_text().replace('"n": 1', '"n": 9'))
    check = integrity.activity_log(paths)
    assert check.status == integrity.PROBLEM and "BROKEN" in check.lines[0]


def _maxwell_chain(path):
    from maxwell_chain_agent import MaxwellChainAgent

    agent = MaxwellChainAgent([], difficulty=1)
    blocks, previous = [], "0" * 64
    for number in range(2):
        data = {"event": f"block {number}"}
        digest = agent._calculate_hash(number, 1790000000.0 + number, "research_event", data, previous, 0, None)
        blocks.append({"block_number": number, "timestamp": 1790000000.0 + number, "block_type": "research_event",
                       "data": data, "previous_hash": previous, "nonce": 0, "hash": digest})
        previous = digest
    path.write_text(json.dumps(blocks))


def test_a_tampered_maxwell_chain_is_caught(tmp_path):
    paths = make_os(tmp_path, time.time())
    assert integrity.maxwell_chains(paths).status == integrity.SKIPPED
    chain = tmp_path / "maxwell_chain.json"
    _maxwell_chain(chain)
    assert integrity.maxwell_chains(paths).status == integrity.OK
    chain.write_text(chain.read_text().replace("block 1", "block X"))
    check = integrity.maxwell_chains(paths)
    assert check.status == integrity.PROBLEM and "does NOT check out" in check.lines[0]


def _relay_block(number, previous, data, nonce):
    digest = hashlib.sha256(f"{number}{previous}{data}{nonce}".encode()).hexdigest()
    return {"block_number": number, "previous_hash": previous, "data": data, "nonce": nonce, "hash": digest,
            "mined_by": "maxwell_relay_node", "data_type": "packet_capture", "is_valid": True,
            "created_date": "2026-08-09T18:39:10.981000"}


def test_a_maxwell_web_app_export_is_checked_by_its_links(tmp_path):
    paths = make_os(tmp_path, time.time())
    genesis = _relay_block(0, "0x" + "0" * 64, "Maxwell Blockchain Genesis Block", 0)
    a = _relay_block(1, genesis["hash"], '{"packet_id":"p1"}', 1)
    fork = _relay_block(1, genesis["hash"], '{"packet_id":"p1"}', 2)  # same record, another branch
    b = _relay_block(2, a["hash"], '{"packet_id":"p2"}', 3)
    export = tmp_path / "autonomous" / "maxwell" / "maxwell_blockchain_20260810_190910.json"
    export.parent.mkdir(parents=True)
    export.write_text(json.dumps([genesis, a, fork, b]))
    check = integrity.maxwell_chains(paths)
    assert check.status == integrity.OK
    assert "4 blocks, every one links back" in check.lines[0] and "2 branches; the longest is 3 blocks" in check.lines[0]
    assert "2 different records" in check.lines[0] and "Hashes weren't recomputed" in check.lines[0]

    b["previous_hash"] = "f" * 64  # a block whose parent is gone
    export.write_text(json.dumps([genesis, a, fork, b]))
    check = integrity.maxwell_chains(paths)
    assert check.status == integrity.PROBLEM and "1 don't link to a parent" in check.lines[0]

    export.write_text("not json")
    check = integrity.maxwell_chains(paths)
    assert check.status == integrity.PROBLEM and "can't be read as a Maxwell chain" in check.lines[0]


def test_code_fingerprints_are_checked_on_the_real_project():
    check = integrity.code_fingerprints(tools.Paths())
    assert check.role == "code enforcement" and check.lines[0].startswith("Code fingerprint now: ")


def test_a_report_is_saved_with_its_fingerprint(tmp_path):
    paths = make_os(tmp_path, time.time())
    report = integrity.run_all(paths, run_tests=False)
    assert {c["name"] for c in report["checks"]} >= {"Node chains", "Shared research chain", "Activity log",
                                                     "Maxwell chain", "Dataset files", "Code fingerprints"}
    json_path, md_path, fingerprint = integrity.write_report(report, tmp_path / "reports")
    assert fingerprint == hashlib.sha256(json_path.read_bytes()).hexdigest()
    page = md_path.read_text(encoding="utf-8")
    assert f"`{fingerprint}`" in page and "## Records and data" in page and "## Code enforcement" in page


def test_integrity_runs_in_the_background_from_chat(tmp_path):
    paths = make_os(tmp_path, time.time())
    latest = paths.rabbit / "integrity-latest.json"
    report = {"ok": False, "checks": [
        {"role": "records and data", "name": "Node chains", "status": "ok", "lines": ["intact"]},
        {"role": "records and data", "name": "Activity log", "status": "problem", "lines": ["hash chain BROKEN."]}]}
    fake = [sys.executable, "-c", f"import json,sys; json.dump({report!r}, open(sys.argv[1], 'w'))", str(latest)]
    s = Session(paths, ai=FakeAI(), integrity_command=fake)
    ask = s.handle("is everything still true?")
    assert ask.confirm and "only reads" in ask.text and "nothing leaves this PC" in ask.text
    assert s.handle("yes").text.startswith("Started the integrity check.")
    assert wait_for(lambda: s.jobs.items and s.jobs.items[0].finished is not None)
    done = s.handle("tokens").text
    assert done.startswith("Done: The integrity check: finished. Problems found. 1 checks passed, 1 found problems")
    assert "Activity log: hash chain BROKEN." in done
    assert "integrity_check_started" in paths.audit.read_text()


def test_the_latest_report_can_be_read_in_chat(tmp_path):
    paths = make_os(tmp_path, time.time())
    s = Session(paths, ai=FakeAI())
    assert s.handle("show the integrity report").text.startswith("There's no integrity report yet.")
    integrity.write_report(integrity.run_all(paths, run_tests=False), paths.autonomous / "integrity")
    text = s.handle("show the latest integrity report").text
    assert text.startswith("Latest integrity report (") and "## Records and data" in text
