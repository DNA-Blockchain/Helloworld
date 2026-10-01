"""The RabbitSoftware.inc web page: the same conversation as the terminal, in a browser on this PC.

It listens on 127.0.0.1 only. Requests must carry an X-Rabbit header, which a page on another
website can't add without the browser first asking this server's permission (it never grants
it), and a Host of 127.0.0.1 or localhost, which stops DNS-rebinding tricks. Together those
keep other websites open in the same browser from talking to it.
"""
from __future__ import annotations

import json
import threading
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from . import NAME, tools
from .assistant import Session
from .jobs import Jobs

PAGE = Path(__file__).with_name("page.html")
UI = Path(__file__).resolve().parent.parent / "ui"
# The UI kit's files, served by name only (nothing else under ui/, and no paths).
UI_FILES = {"tokens.css": "text/css; charset=utf-8", "rabbit.js": "text/javascript; charset=utf-8",
            "gallery.html": "text/html; charset=utf-8", "gallery.js": "text/javascript; charset=utf-8"}
DEFAULT_PORT = 8792
MAX_SESSIONS = 20
MAX_TEXT = 4000


class Sessions:
    """One conversation per browser tab, the oldest dropped past MAX_SESSIONS."""

    def __init__(self, factory: Callable[[], Session]):
        self.factory = factory
        self.items: OrderedDict[str, tuple[Session, threading.Lock]] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: str) -> tuple[Session, threading.Lock]:
        with self.lock:
            if key not in self.items:
                self.items[key] = (self.factory(), threading.Lock())
                while len(self.items) > MAX_SESSIONS:
                    self.items.popitem(last=False)
            self.items.move_to_end(key)
            return self.items[key]


def route(path: str) -> str:
    """The API's version-1 routes (schemas/rabbitsoftware-app-api-v1); the older /api/... ones are aliases."""
    return path.replace("/api/v1/", "/api/", 1) if path.startswith("/api/v1/") else path


def make_handler(sessions: Sessions, paths: tools.Paths, port: int, jobs: Jobs | None = None):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = NAME

        def log_message(self, *args):         # keep the terminal quiet; conversations aren't logged
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def _trusted(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            if not self._trusted():
                return self._json(403, {"error": "open this page at http://127.0.0.1:%d" % port})
            if self.path in ("/", "/index.html"):
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if self.path.startswith("/ui/"):
                name = self.path[len("/ui/"):]
                if name in UI_FILES:
                    return self._send(200, (UI / name).read_bytes(), UI_FILES[name])
                return self._json(404, {"error": "not found"})
            path = route(self.path)
            if path in ("/api/status", "/api/shell") and self.headers.get("X-Rabbit") != "1":
                return self._json(403, {"error": "missing X-Rabbit header"})
            if path == "/api/status":
                return self._json(200, {"nodes": tools.nodes(paths)[0], "chain": tools.chain(paths)[0]})
            if path == "/api/shell":
                from .shell_api import snapshot

                return self._json(200, snapshot(paths, jobs))
            self._json(404, {"error": "not found"})

        def do_POST(self):
            # Read the body before any refusal: closing with unread data resets the connection on
            # Windows, and the caller would see an error instead of the refusal.
            try:
                raw = self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 16_384))
            except ValueError:
                raw = b""
            if not self._trusted() or self.headers.get("X-Rabbit") != "1":
                return self._json(403, {"error": "not allowed"})
            path = route(self.path)
            if path not in ("/api/message", "/api/poll"):
                return self._json(404, {"error": "not found"})
            try:
                body = json.loads(raw or b"{}")
                key, text = str(body.get("session", ""))[:64], str(body.get("text", ""))[:MAX_TEXT]
                uuid.UUID(key)
            except (ValueError, TypeError, AttributeError):
                return self._json(400, {"error": "send {\"session\": <uuid>, \"text\": <message>}"})
            session, lock = sessions.get(key)
            with lock:
                if path == "/api/poll":                       # background jobs that finished meanwhile
                    notice = session.poll()
                    return self._json(200, {"text": notice.text if notice else ""})
                reply = session.handle(text)
            self._json(200, {"text": reply.text, "choices": reply.choices, "confirm": reply.confirm})

    return Handler


def serve(port: int = DEFAULT_PORT, paths: tools.Paths | None = None,
          factory: Callable[[], Session] | None = None) -> ThreadingHTTPServer:
    paths = paths or tools.Paths()
    shared_jobs = Jobs(paths.rabbit / "jobs")         # one set of background jobs for every tab
    sessions = Sessions(factory or (lambda: Session(paths, jobs=shared_jobs)))
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(sessions, paths, port, shared_jobs))
