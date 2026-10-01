"""Contract tests: real messages from each part of RabbitSoftware, checked against schemas/rabbitsoftware-*.
A change that breaks an API fails here; see docs/api/ and RELEASING.md for how APIs change."""
import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from jsonschema import Draft202012Validator

from rabbitsoft import contracts
from tests.test_rabbitsoft import FakeAI, make_os

ROOT = Path(__file__).resolve().parent.parent


def fits(instance, api, definition=None):
    problems = contracts.errors(instance, api, definition)
    assert not problems, problems


@pytest.mark.parametrize("api", contracts.APIS)
def test_every_schema_is_valid_and_its_definitions_resolve(api):
    schema = json.loads((contracts.SCHEMAS / f"rabbitsoftware-{api}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == contracts._uri(api)
    for name in schema.get("$defs", {}):
        contracts.validator(api, name)          # resolves


def test_a_bad_message_is_reported_clearly():
    problems = contracts.errors({"text": "hi", "choices": "not a list"}, "app-api-v1", "messageReply")
    assert any("confirm" in p for p in problems) and any(p.startswith("choices") for p in problems)
    with pytest.raises(ValueError, match="doesn't fit app-api-v1#messageReply"):
        contracts.validate({}, "app-api-v1", "messageReply")


# -- the local app API and the OS shell API, from the real web server ---------------------------------
@pytest.fixture
def app(tmp_path):
    from rabbitsoft.assistant import Session
    from rabbitsoft.web import serve

    paths = make_os(tmp_path, time.time())
    server = serve(0, paths, factory=lambda: Session(paths, ai=FakeAI(), search=lambda q: []))
    port = server.server_address[1]
    server.server_close()                       # rebind on the real port so the Host check matches
    server = serve(port, paths, factory=lambda: Session(paths, ai=FakeAI(), search=lambda q: []))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}", paths
    server.shutdown()


def call(base, method, path, body=None):
    request = Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                      headers={"X-Rabbit": "1", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except Exception as error:                  # HTTPError carries the JSON error body
        return error.code, json.loads(error.read())


def test_the_app_api_v1_and_its_aliases(app):
    base, _ = app
    session = str(uuid.uuid4())
    request = {"session": session, "text": "hi"}
    fits(request, "app-api-v1", "messageRequest")
    for prefix in ("/api/v1", "/api"):
        status, reply = call(base, "POST", f"{prefix}/message", request)
        assert status == 200
        fits(reply, "app-api-v1", "messageReply")
        status, reply = call(base, "POST", f"{prefix}/poll", {"session": session})
        fits(reply, "app-api-v1", "pollReply")
        status, reply = call(base, "GET", f"{prefix}/status")
        fits(reply, "app-api-v1", "statusReply")
    status, reply = call(base, "POST", "/api/v1/message", {"session": "not-a-uuid", "text": "hi"})
    assert status == 400
    fits(reply, "app-api-v1", "error")


def test_the_shell_api_v1(app):
    from rabbitsoft import integrity
    from hosted_ai import save_url

    base, paths = app
    status, snapshot = call(base, "GET", "/api/v1/shell")
    assert status == 200 and snapshot["integrity"] is None and snapshot["ai"] == {"model_server": None, "account": False}
    fits(snapshot, "shell-api-v1")
    assert [n["id"] for n in snapshot["nodes"]] == ["node-0", "node-1", "node-2"]

    integrity.write_report(integrity.run_all(paths, run_tests=False), paths.autonomous / "integrity")
    save_url(paths.rabbit / "settings.json", "https://rabbit.example.org")
    _, snapshot = call(base, "GET", "/api/v1/shell")
    fits(snapshot, "shell-api-v1")
    assert snapshot["ai"]["model_server"] == "https://rabbit.example.org" and snapshot["integrity"]["ok"] in (True, False)


# -- the node API, from a real node --------------------------------------------------------------------
def test_the_node_api_v1_from_a_real_node(tmp_path):
    from tests.test_network_node import _node
    from token_ledger import TokenLedger

    node = _node(0, 19590, [], tmp_path, TokenLedger(str(tmp_path / "ledger.json")))
    node.chain.append({"origin": 0, "note": "contract test"})
    fits(node.status(), "node-api-v1", "status")
    chain_file = json.loads(Path(node.chain.store_path).read_text(encoding="utf-8"))
    fits(chain_file, "node-api-v1", "chainFile")


def test_research_events_fit_the_node_api():
    import research_provenance as rp

    note = rp.create_public_record_note_event(note_kind="challenge", about_event_id="ab" * 16,
                                              text="The title is missing a word.", confirm_publication=True)
    fits(note, "node-api-v1", "noteEvent")
    fits(note, "node-api-v1", "researchEvent")
    data_hash = rp.create_public_data_hash_event(data_sha256="0" * 64, data_kind="integrity_report",
                                                 classification="public", confirm_hash_publication=True)
    fits(data_hash, "node-api-v1", "dataHashEvent")
    assert contracts.errors({**data_hash, "extra": 1}, "node-api-v1", "dataHashEvent")


def test_every_event_on_this_pcs_research_chain_fits():
    from research_ledger import load_all_ledgers

    ledgers = load_all_ledgers(str(ROOT / "autonomous")) if (ROOT / "autonomous").exists() else {}
    if not ledgers:
        pytest.skip("no research chain on this machine")
    events = [e["block"]["research_provenance"] for e in next(iter(ledgers.values())).entries()
              if isinstance(e["block"].get("research_provenance"), dict)]
    for event in events:
        fits(event, "node-api-v1", "researchEvent")


# -- the model API, from the real client and gateway -----------------------------------------------------
def test_the_model_api_v1(tmp_path):
    from tests.test_model_gateway import gateway
    from hosted_ai import HostedAI

    sent = []

    class Capture(HostedAI):
        def generate(self, prompt, num_predict=220):
            body = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": num_predict, "temperature": 0.2, "stream": False}
            sent.append(body)
            return "ok"

    Capture("https://rabbit.example.org").generate("What is HBB?", num_predict=60)
    fits(sent[0], "model-api-v1", "chatRequest")
    cleaned = gateway.clean_request({"messages": [{"role": "user", "content": "hi"}], "max_tokens": 9999}, 12000, 400)
    fits(cleaned, "model-api-v1", "chatRequest")
    fits({"choices": [{"message": {"role": "assistant", "content": "Answer."}}]}, "model-api-v1", "chatResponse")
    fits({"error": "too many questions this hour; try again later"}, "model-api-v1", "error")


# -- the sync API, recorded from the real client talking to the real Worker code -----------------------------
SYNC_ROUTES = [  # (method, path pattern) -> (request definition, reply definition)
    ("POST", r"^/v1/devices$", "registerRequest", "registerReply"),
    ("GET", r"^/v1/devices$", None, "devicesReply"),
    ("DELETE", r"^/v1/devices/[0-9a-f]{32}$", None, "ok"),
    ("GET", r"^/v1/history$", None, "historyList"),
    ("POST", r"^/v1/corpus$", "corpusUpload", "corpusUploadReply"),
    ("GET", r"^/v1/corpus/batches$", None, "corpusBatchList"),
    ("GET", r"^/v1/corpus/batches/.+$", None, "corpusBatch"),
    ("POST", r"^/v1/training$", "trainingItem", "ok"),
    ("POST", r"^/v1/pairing$", "pairingCreate", "pairingCreated"),
    ("GET", r"^/v1/pairing/[A-Z2-7]{4}$", None, "pairingSlot"),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
def test_the_sync_api_v1_on_the_wire(tmp_path):
    import re
    import subprocess

    from rabbitsoft.sync import SyncClient, _urllib_http
    from research_catalog import ResearchCatalog
    from tests.test_sync_client import RECORD, SERVER

    process = subprocess.Popen(["node", str(SERVER), "0"], stdout=subprocess.PIPE, text=True)
    url = f"http://127.0.0.1:{process.stdout.readline().split()[1]}"
    seen = []

    def recording(method, full_url, headers, body):
        status, raw = _urllib_http(method, full_url, headers, body)
        path = full_url[len(url):]
        seen.append((method, path, headers.get("Content-Type"), body, status, raw))
        return status, raw

    try:
        a = SyncClient(tmp_path / "a", url, http=recording)
        a.create_account("a", "letmein")
        b = SyncClient(tmp_path / "b", url, http=recording)
        b.join_with_code(a.make_pairing_code(), "b")
        catalog = ResearchCatalog(tmp_path / "c.sqlite3")
        catalog.add_records([RECORD])
        a.sync(catalog, [{"time": 1, "question": "q", "answer": "a"}])
        b.sync(ResearchCatalog(tmp_path / "d.sqlite3"), [])
        assert [e["question"] for e in b.pull_history()] == ["q"]
        a.share_training("q", "a", [], rating=1)
        a.devices()
        b.remove_device(a.info()["device"])
    finally:
        process.terminate()

    checked = set()
    for method, path, content_type, body, status, raw in seen:
        if method == "PUT" or path.startswith("/v1/history/"):
            continue                              # encrypted bytes, not JSON
        route = next((r for r in SYNC_ROUTES if r[0] == method and re.match(r[1], path)), None)
        assert route, f"{method} {path} isn't in the sync API"
        if route[2] and content_type == "application/json":
            fits(json.loads(body), "sync-api-v1", route[2])
        fits(json.loads(raw), "sync-api-v1", route[3] if status < 400 else "error")
        checked.add((route[0], route[1]))
    assert len(checked) == len(SYNC_ROUTES)        # every route was exercised


# -- the integrity report and tool survey ------------------------------------------------------------------
def test_the_integrity_report_and_tool_survey_v1(tmp_path):
    from rabbitsoft import integrity, toolchain

    paths = make_os(tmp_path, time.time())
    report = integrity.run_all(paths, run_tests=False)
    fits(report, "integrity-v1", "report")
    json_path, _, _ = integrity.write_report(report, tmp_path / "reports")
    fits(json.loads(json_path.read_text(encoding="utf-8")), "integrity-v1", "report")
    rows = toolchain.survey(here={"python", "git"}, wsl=None)
    fits(toolchain.survey_json(rows), "integrity-v1", "toolSurvey")
    fits(toolchain.survey_json(toolchain.survey(here={"python"}, wsl={"gcc"})), "integrity-v1", "toolSurvey")
