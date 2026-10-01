import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import hosted_ai
from hosted_ai import HostedAI, check_url, configured_url, from_settings, save_url
from rabbitsoft.assistant import Session
from tests.test_rabbitsoft import RECORDS, FakeAI, make_os


@pytest.fixture
def server():
    """An OpenAI-compatible model server on this PC, like the gateway in front of the hosted model."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            if self.headers.get("Authorization") != "Bearer k1":
                self.send_response(401)
                self.end_headers()
                return
            reply = json.dumps({"choices": [{"message": {"role": "assistant", "content": " From the server [1]. "}}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(reply.encode())

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", seen
    httpd.shutdown()


def test_only_https_leaves_this_pc():
    assert check_url("https://rabbit.example.org/") == "https://rabbit.example.org"
    assert check_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    for bad in ("http://rabbit.example.org", "ftp://x.org", "https://x.org/?key=1", "https://user:pw@x.org", "x.org"):
        with pytest.raises(ValueError):
            check_url(bad)


def test_the_model_is_asked_like_any_other_llm(server):
    url, seen = server
    assert HostedAI(url, key="k1", model="nos").generate("Hello?", num_predict=50) == "From the server [1]."
    assert seen[0]["path"] == "/v1/chat/completions" and seen[0]["auth"] == "Bearer k1"
    assert seen[0]["body"]["messages"] == [{"role": "user", "content": "Hello?"}]
    assert seen[0]["body"]["model"] == "nos" and seen[0]["body"]["max_tokens"] == 50
    assert HostedAI(url + "/v1", key="k1").generate("Hi") and seen[1]["path"] == "/v1/chat/completions"
    with pytest.raises(RuntimeError, match="HTTP 401 .*RABBIT_MODEL_KEY"):
        HostedAI(url).generate("Hi")
    with pytest.raises(RuntimeError, match="couldn't be reached"):
        HostedAI("http://127.0.0.1:9", timeout=2).generate("Hi")


def test_the_server_is_saved_and_the_environment_wins(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"notes": True}))
    assert configured_url(settings) == "" and from_settings(settings) is None
    assert save_url(settings, "https://rabbit.example.org/") == "https://rabbit.example.org"
    assert json.loads(settings.read_text()) == {"notes": True, "model_server": "https://rabbit.example.org"}
    assert from_settings(settings).host == "rabbit.example.org"
    monkeypatch.setenv("RABBIT_MODEL_URL", "https://other.example.org")
    assert configured_url(settings) == "https://other.example.org"
    monkeypatch.setenv("RABBIT_MODEL_URL", "http://not-encrypted.example.org")
    assert from_settings(settings) is None                         # refused, not used
    monkeypatch.delenv("RABBIT_MODEL_URL")
    save_url(settings, None)
    assert json.loads(settings.read_text()) == {"notes": True}


def test_a_private_hugging_face_endpoint_uses_this_pcs_login_and_nothing_else_does(tmp_path, monkeypatch):
    import sys
    import types

    fake = types.ModuleType("huggingface_hub")     # GitHub's test machine doesn't install huggingface_hub
    fake.get_token = lambda: "hf_login"
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    settings = tmp_path / "settings.json"
    save_url(settings, "https://abc.endpoints.huggingface.cloud")
    assert from_settings(settings).key == "hf_login"
    save_url(settings, "https://gateway.example.org")
    assert from_settings(settings).key == ""                       # the login never goes to other servers
    monkeypatch.setenv("RABBIT_MODEL_KEY", "k1")
    assert from_settings(settings).key == "k1"


class FakeServer:
    host = "rabbit.example.org"

    def __init__(self, broken=False):
        self.prompts, self.broken = [], broken

    def generate(self, prompt, num_predict=220):
        if self.broken:
            raise RuntimeError("the model server rabbit.example.org returned HTTP 503 (it's starting up)")
        self.prompts.append(prompt)
        return "The server says base editing worked [1]."


def _session(tmp_path, server, searched=None):
    s = Session(make_os(tmp_path, time.time()), ai=FakeAI(), hosted=server,
                search=lambda q: (searched.append(q) if searched is not None else None) or RECORDS)
    s._catalog().add_records(RECORDS)
    return s


def test_every_ai_answer_asks_before_going_to_the_server(tmp_path):
    from audit_trail import AuditTrail

    server = FakeServer()
    s = _session(tmp_path, server)
    ask = s.handle("base editing sickle cell")
    assert ask.confirm and "model server rabbit.example.org" in ask.text and "Nothing personal" in ask.text
    assert server.prompts == []
    yes = s.handle("yes")
    assert yes.text.startswith("The server says base editing worked [1].") and len(server.prompts) == 1
    assert "Written by your model on rabbit.example.org" in yes.text
    assert "base editing sickle cell" in server.prompts[0]
    entry = [e for e in AuditTrail(str(s.paths.audit)).read_all() if e["action"] == "model_server_used"][-1]
    assert entry["details"] == {"host": "rabbit.example.org", "fell_back": False}

    assert s.handle("base editing sickle cell").confirm              # asked again: every time, not once
    no = s.handle("no")
    assert no.text.startswith("Base editing changed blood cells") and len(server.prompts) == 1   # this PC's model

    assert not s.handle("how are the nodes").confirm                  # no AI needed, nothing asked


def test_a_server_that_doesnt_answer_falls_back_to_this_pc(tmp_path):
    s = _session(tmp_path, FakeServer(broken=True))
    s.handle("base editing sickle cell")
    reply = s.handle("yes")
    assert reply.text.startswith("(The model server didn't answer: the model server rabbit.example.org returned "
                                 "HTTP 503 (it's starting up). This PC's model answered instead.)")
    assert "Base editing changed blood cells" in reply.text and "Written by the local AI" in reply.text


def test_a_public_search_is_never_repeated_by_the_model_question(tmp_path):
    searched = []
    s = Session(make_os(tmp_path, time.time()), ai=FakeAI(), hosted=FakeServer(),
                search=lambda q: searched.append(q) or RECORDS)
    s.handle("sikle cel")                      # no saved records: suggesting search words needs the AI
    s.handle("no")                             # ... so it asked; answer on this PC
    s.handle("1")                              # search for "sickle cell"
    s.handle("yes")                            # send the search
    assert searched == ["sickle cell"]
    reply = s.handle("yes")                    # now the answer asks about the model server
    assert searched == ["sickle cell"] and reply.text.startswith("Found 1 records")


def test_the_model_server_command(tmp_path, capsys):
    import rabbit

    settings = tmp_path / "settings.json"
    assert rabbit.model_server(None, False, settings) == 0 and "No model server" in capsys.readouterr().out
    assert rabbit.model_server("http://remote.example.org", False, settings) == 1
    assert "must use https" in capsys.readouterr().out
    assert rabbit.model_server("https://rabbit.example.org", False, settings) == 0
    assert "asks before each question" in capsys.readouterr().out
    assert rabbit.model_server(None, False, settings) == 0
    assert capsys.readouterr().out.strip() == "Model server: https://rabbit.example.org"
    assert rabbit.model_server(None, True, settings) == 0 and configured_url(settings) == ""


def test_the_client_uses_certifi_for_https():
    assert hosted_ai.SSL_CONTEXT.verify_mode.name == "CERT_REQUIRED"
