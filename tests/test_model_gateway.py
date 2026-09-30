import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from hosted_ai import HostedAI

_spec = importlib.util.spec_from_file_location(
    "gateway_app", Path(__file__).resolve().parent.parent / "deploy" / "gateway" / "app.py")
gateway = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gateway)


class Clock:
    def __init__(self):
        self.now = 1_790_000_000.0

    def __call__(self):
        return self.now


def test_each_person_and_each_day_are_limited():
    clock = Clock()
    limits = gateway.Limits(per_client_per_hour=2, daily_limit=3, clock=clock)
    assert limits.allow("a") == "" and limits.allow("a") == ""
    assert "too many questions this hour" in limits.allow("a")
    assert limits.allow("b") == ""                                  # someone else still can
    assert "all the questions it can today" in limits.allow("c")    # the day's cap
    clock.now += 86_400                                             # a new day
    assert limits.allow("a") == ""


def test_only_the_messages_and_a_capped_length_go_on():
    cleaned = gateway.clean_request({"model": "anything", "messages": [{"role": "user", "content": "hi", "x": 1}],
                                     "max_tokens": 5000, "temperature": 9, "tools": ["web"]},
                                    max_prompt_chars=100, max_tokens=400)
    assert cleaned == {"model": "rabbitsoftware", "messages": [{"role": "user", "content": "hi"}],
                       "max_tokens": 400, "temperature": 1.5, "stream": False}
    for bad in ({}, {"messages": []}, {"messages": [{"role": "tool", "content": "x"}]},
                {"messages": [{"role": "user", "content": "x" * 101}]}):
        with pytest.raises(ValueError):
            gateway.clean_request(bad, max_prompt_chars=100, max_tokens=400)


@pytest.fixture
def running_gateway():
    sent = []

    def fake_endpoint(url, token, payload):
        sent.append((url, token, payload))
        if payload["messages"][0]["content"] == "wake":
            return 503, json.dumps({"error": "the model couldn't be reached; it may be waking up"}).encode()
        return 200, json.dumps({"choices": [{"message": {"content": "Answer from the endpoint."}}]}).encode()

    limits = gateway.Limits(per_client_per_hour=3, daily_limit=100)
    handler = gateway.make_handler(limits, send=fake_endpoint, endpoint_url="https://endpoint.example", token="secret")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", sent
    httpd.shutdown()


def test_rabbitsoftware_reaches_the_model_through_the_gateway(running_gateway):
    url, sent = running_gateway
    client = HostedAI(url)                                           # no key: the gateway holds it
    assert client.generate("What is base editing?") == "Answer from the endpoint."
    assert sent[0][:2] == ("https://endpoint.example", "secret")
    with pytest.raises(RuntimeError, match="HTTP 503 .*starting up"):
        client.generate("wake")
    client.generate("third")
    with pytest.raises(RuntimeError, match="HTTP 429 .*too many questions"):
        client.generate("fourth")                                    # 3 an hour for this test
    assert len(sent) == 3
