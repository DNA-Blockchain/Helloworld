"""RabbitSoftware.inc model gateway: the public front door to the hosted model.

Downloads of RabbitSoftware.inc send questions here, never straight to the Hugging Face endpoint, because
the endpoint needs the owner's access key and that key must never ship in a public download. This
gateway runs as a Hugging Face Space, holds the key as a Space secret, and forwards each question to
the endpoint with limits so strangers can't run up the bill:

  - each person (by network address) gets at most PER_CLIENT_PER_HOUR questions an hour,
  - everyone together gets at most DAILY_LIMIT questions a day (the spending cap),
  - a question is at most MAX_PROMPT_CHARS long and an answer at most MAX_TOKENS tokens.

It speaks the same OpenAI-compatible API it forwards to (POST /v1/chat/completions), so the client in
hosted_ai.py works against either. Questions and answers are never written down: only counts are kept,
in memory.

Space secrets / variables:
    HF_TOKEN        a Hugging Face token allowed to call the endpoint (secret)
    ENDPOINT_URL    the Inference Endpoint's URL, e.g. https://xxxx.us-east-1.aws.endpoints.huggingface.cloud
    DAILY_LIMIT, PER_CLIENT_PER_HOUR, MAX_TOKENS, MAX_PROMPT_CHARS   (optional; defaults below)
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError

MODEL_NAME = "rabbitsoftware"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Limits:
    def __init__(self, per_client_per_hour: int, daily_limit: int, clock=time.time):
        self.per_client_per_hour = per_client_per_hour
        self.daily_limit = daily_limit
        self.clock = clock
        self.lock = threading.Lock()
        self.recent: dict[str, deque] = defaultdict(deque)
        self.day, self.today = "", 0

    def allow(self, client: str) -> str:
        """"" if this question may go through (and counts it), else why not."""
        now = self.clock()
        with self.lock:
            day = time.strftime("%Y-%m-%d", time.gmtime(now))
            if day != self.day:
                self.day, self.today = day, 0
                self.recent.clear()
            if self.today >= self.daily_limit:
                return "the model has answered all the questions it can today; try again tomorrow (UTC)"
            times = self.recent[client]
            while times and now - times[0] > 3600:
                times.popleft()
            if len(times) >= self.per_client_per_hour:
                return "too many questions this hour; try again later"
            times.append(now)
            self.today += 1
            return ""


def clean_request(body: dict, max_prompt_chars: int, max_tokens: int) -> dict:
    """Only what the model needs goes on: the messages (checked) and a capped answer length."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages or len(messages) > 8:
        raise ValueError("send 1 to 8 messages")
    kept, total = [], 0
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant") \
                or not isinstance(m.get("content"), str):
            raise ValueError("each message needs a role (system, user or assistant) and text content")
        total += len(m["content"])
        kept.append({"role": m["role"], "content": m["content"]})
    if total > max_prompt_chars:
        raise ValueError(f"the question is too long (at most {max_prompt_chars} characters)")
    try:
        wanted = int(body.get("max_tokens") or max_tokens)
        temperature = float(body.get("temperature", 0.2))
    except (TypeError, ValueError):
        raise ValueError("max_tokens and temperature must be numbers") from None
    return {"model": MODEL_NAME, "messages": kept, "max_tokens": max(1, min(wanted, max_tokens)),
            "temperature": max(0.0, min(temperature, 1.5)), "stream": False}


def forward(endpoint_url: str, token: str, payload: dict, timeout: float = 300) -> tuple[int, bytes]:
    url = endpoint_url.rstrip("/")
    url = f"{url}/chat/completions" if url.endswith("/v1") else f"{url}/v1/chat/completions"
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(1024 * 1024)
    except HTTPError as error:
        # A sleeping endpoint answers 503 while it wakes; pass that on so the client can say "try again".
        return (503 if error.code in (502, 503, 504) else 502), json.dumps(
            {"error": f"the model returned HTTP {error.code}"}).encode()
    except (URLError, OSError, TimeoutError):
        return 503, json.dumps({"error": "the model couldn't be reached; it may be waking up"}).encode()


def make_handler(limits: Limits, send=forward, endpoint_url: str = "", token: str = "",
                 max_prompt_chars: int = 12_000, max_tokens: int = 400):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, data) -> None:
            body = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _client(self) -> str:
            # Hugging Face's proxy puts the caller's address first in X-Forwarded-For.
            forwarded = self.headers.get("X-Forwarded-For", "")
            return forwarded.split(",")[0].strip() or self.client_address[0]

        def do_GET(self):
            if self.path in ("/", "/health"):
                return self._json(200, {"service": "RabbitSoftware.inc model gateway", "ok": True,
                                        "api": "POST /v1/chat/completions"})
            self._json(404, {"error": "not found"})

        def do_POST(self):
            length = min(int(self.headers.get("Content-Length") or 0), max_prompt_chars * 4 + 4096)
            raw = self.rfile.read(length)
            if self.path != "/v1/chat/completions":
                return self._json(404, {"error": "not found"})
            try:
                payload = clean_request(json.loads(raw or b"{}"), max_prompt_chars, max_tokens)
            except (ValueError, AttributeError) as error:
                return self._json(400, {"error": str(error)})
            refused = limits.allow(self._client())
            if refused:
                return self._json(429, {"error": refused})
            status, body = send(endpoint_url, token, payload)
            self._json(status, body)

        def log_message(self, format, *args):
            pass            # questions and addresses are never written down

    return Handler


def main() -> None:
    endpoint_url, token = os.environ.get("ENDPOINT_URL", ""), os.environ.get("HF_TOKEN", "")
    if not endpoint_url or not token:
        raise SystemExit("set the ENDPOINT_URL variable and the HF_TOKEN secret in the Space settings")
    limits = Limits(_int_env("PER_CLIENT_PER_HOUR", 20), _int_env("DAILY_LIMIT", 500))
    handler = make_handler(limits, endpoint_url=endpoint_url, token=token,
                           max_prompt_chars=_int_env("MAX_PROMPT_CHARS", 12_000), max_tokens=_int_env("MAX_TOKENS", 400))
    port = _int_env("PORT", 7860)
    print(f"gateway listening on :{port} -> {endpoint_url.split('//')[-1].split('/')[0]}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), handler).serve_forever()


if __name__ == "__main__":
    main()
