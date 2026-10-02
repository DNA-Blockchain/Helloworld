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


def test_test_fixtures_in_the_supervisors_scratch_folder_are_not_checked(tmp_path):
    paths = make_os(tmp_path, time.time())
    fixture = tmp_path / "autonomous" / "pytest-tmp" / "test_a_tampered_maxwell_chain_0" / "maxwell_chain.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("not json")                  # broken on purpose, like the real test fixtures
    assert integrity.maxwell_chains(paths).status == integrity.SKIPPED
    real = tmp_path / "autonomous" / "maxwell" / "maxwell_chain.json"
    real.parent.mkdir(parents=True)
    _maxwell_chain(real)
    check = integrity.maxwell_chains(paths)
    assert check.status == integrity.OK and len(check.lines) == 1


def _saved_report(paths):
    report = {"schema": "rabbitsoft-integrity.v1", "created_at": "2026-10-01T08:00:00+00:00", "ok": True, "checks": []}
    json_path, _, fingerprint = integrity.write_report(report, paths.autonomous / "integrity")
    return json_path, fingerprint


def test_a_reports_fingerprint_goes_on_the_chain_only_after_a_yes(tmp_path):
    from audit_trail import AuditTrail
    from research_provenance import ResearchProvenanceQueue, validate_public_provenance

    paths = make_os(tmp_path, time.time())
    s = Session(paths, ai=FakeAI())
    assert "no integrity report yet" in s.handle("publish the integrity fingerprint").text
    json_path, fingerprint = _saved_report(paths)
    assert 'say "publish the integrity fingerprint"' in s.handle("show the latest integrity report").text
    ask = s.handle("publish the integrity fingerprint")
    outbox = ResearchProvenanceQueue(paths.autonomous / "research-outbox")
    assert ask.confirm and "only the SHA-256" in ask.text and outbox.peek() is None
    assert s.handle("yes").text.startswith("Queued the fingerprint")
    event, _ = outbox.peek()
    validate_public_provenance(event)
    assert event["data_kind"] == "integrity_report" and event["data_sha256"] == fingerprint
    entry = [e for e in AuditTrail(str(paths.audit)).read_all() if e["action"] == "integrity_fingerprint_queued"][-1]
    assert entry["details"]["sha256"] == fingerprint and entry["details"]["report"] == json_path.name


def test_publishing_every_day_is_a_choice_kept_on_this_pc(tmp_path, monkeypatch):
    from research_provenance import ResearchProvenanceQueue

    paths = make_os(tmp_path, time.time())
    s = Session(paths, ai=FakeAI())
    assert not integrity.publishing_daily(paths)
    assert s.handle("keep integrity reports on this pc").text == "Integrity reports already stay on this PC."
    ask = s.handle("publish integrity fingerprints daily")
    assert ask.confirm and not integrity.publishing_daily(paths)
    assert s.handle("yes").text.startswith("On.") and integrity.publishing_daily(paths)
    _saved_report(paths)
    assert "also published to the shared chain" in s.handle("show the latest integrity report").text

    # The daily run (python -m rabbitsoft.integrity --daily) publishes only while it's on.
    monkeypatch.setattr(integrity, "Paths", lambda: paths)
    monkeypatch.setattr(integrity, "run_all", lambda paths, run_tests: {
        "schema": "rabbitsoft-integrity.v1", "created_at": "2026-10-02T08:00:00+00:00", "ok": True, "checks": []})
    outbox = ResearchProvenanceQueue(paths.autonomous / "research-outbox")
    assert integrity.main(["--no-tests", "--daily"]) == 0 and outbox.peek() is not None
    assert s.handle("stop publishing integrity fingerprints").text.startswith("Off.")
    assert not integrity.publishing_daily(paths)
    for queued in (paths.autonomous / "research-outbox").glob("*.json"):
        queued.unlink()
    integrity.main(["--no-tests", "--daily"])
    assert outbox.peek() is None


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
