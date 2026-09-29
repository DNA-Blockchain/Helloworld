#!/usr/bin/env python3
# ============================================================================
#  SPDX-License-Identifier: UPL-1.0
#
#  Copyright (c) 2026 Chase Allen Ringquist
#
#  This file is part of an operating system, software, and network Work
#  conceived and authored by Chase Allen Ringquist. The Author retains
#  copyright and authorship. Use of this file is licensed as follows.
#
#  ----------------------------------------------------------------------------
#  The Universal Permissive License (UPL), Version 1.0
#
#  Subject to the condition set forth below, permission is hereby granted to
#  any person obtaining a copy of this software, associated documentation
#  and/or data (collectively the "Software"), free of charge and under any
#  and all copyright rights in the Software, and any and all patent rights
#  owned or freely licensable by each licensor hereunder covering either
#  (i) the unmodified Software as contributed to or provided by such
#  licensor, or (ii) the Larger Works (as defined below), to deal in both
#
#  (a) the Software, and
#
#  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
#  if one is included with the Software (each a "Larger Work" to which the
#  Software is contributed by such licensors),
#
#  without restriction, including without limitation the rights to copy,
#  create derivative works of, display, perform, and distribute the Software
#  and make, use, sell, offer for sale, import, export, have made, and have
#  sold the Software and the Larger Work(s), and to sublicense the foregoing
#  rights on either these or other terms.
#
#  This license is subject to the following condition:
#
#  The above copyright notice and either this complete permission notice or
#  at a minimum a reference to the UPL must be included in all copies or
#  substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#  ----------------------------------------------------------------------------
#
#  Do not remove or alter this notice or any record of origin.
#  See NOTICE.md in the project root for authorship and ownership terms.
#
#  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
#            Bixby, OK, United States
# ============================================================================

"""
live_feed.py — a loopback-only HTTP server that streams live_store.py's
database as things happen.

It reads the SQLite file directly rather than an in-memory queue, so one
feed sees writes from every process sharing the database (all three
node_supervisor.py nodes, or run_all.py's node + agents).

ENDPOINTS
--------------
    GET /                                    endpoint list + current last seq
    GET /events?after=SEQ&stream=S&limit=N   JSON: events with seq > SEQ
    GET /stream?after=SEQ&stream=S           Server-Sent Events, live; each event's
                                             `id:` is its seq, so a reconnecting
                                             EventSource resumes via Last-Event-ID
    GET /snapshots?stream=S                  JSON: snapshot keys + updated_at + sha256
    GET /snapshot?stream=S&key=K             JSON: one snapshot's full data

`stream` is one of: chain, audit, ledger, network_ledger, dna, research,
corpus, status, supervisor. Omit it for all streams.

LOOPBACK ONLY, DELIBERATELY
--------------------------------
The database includes the personal DNA strand state, so this server
refuses to bind anything but 127.0.0.1 / ::1 / localhost. For another
device, use a private VPN or SSH tunnel to this host (see README's
"Local-first alternative to Supabase"), not a public bind.

Usage
-----
    python live_feed.py                                   # live_store.db, port 8790
    python live_feed.py --db autonomous/live_store.db     # the supervisor's nodes
    curl -N http://127.0.0.1:8790/stream?stream=chain     # watch blocks arrive

    # browser / Node:
    new EventSource("http://127.0.0.1:8790/stream").onmessage = e => console.log(JSON.parse(e.data))
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from live_store import LiveStore

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
DEFAULT_PORT = 8790
POLL_INTERVAL_S = 0.25
KEEPALIVE_S = 15.0


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def make_handler(store: LiveStore, stop_event: threading.Event):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):   # quiet; the node logs are noisy enough
            pass

        def _json(self, status: int, body) -> None:
            raw = json.dumps(body, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            stream = q.get("stream") or None

            if url.path == "/":
                self._json(200, {
                    "db": store.path, "last_seq": store.last_seq(),
                    "endpoints": ["/events?after=&stream=&limit=", "/stream?after=&stream=",
                                  "/snapshots?stream=", "/snapshot?stream=&key="],
                })
            elif url.path == "/events":
                limit = max(1, min(_int(q.get("limit"), 500), 5000))
                self._json(200, store.events_after(_int(q.get("after"), 0), stream=stream, limit=limit))
            elif url.path == "/snapshots":
                self._json(200, store.list_snapshots(stream))
            elif url.path == "/snapshot":
                if not stream or "key" not in q:
                    self._json(400, {"error": "stream and key are required"})
                    return
                snap = store.get_snapshot(stream, q["key"])
                self._json(200 if snap else 404, snap or {"error": "no such snapshot"})
            elif url.path == "/stream":
                after = _int(self.headers.get("Last-Event-ID") or q.get("after"), store.last_seq())
                self._sse(after, stream)
            else:
                self._json(404, {"error": "unknown path"})

        def _sse(self, after: int, stream: str | None) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            last_write = time.monotonic()
            try:
                while not stop_event.is_set():
                    events = store.events_after(after, stream=stream, limit=500)
                    for ev in events:
                        self.wfile.write(f"id: {ev['seq']}\ndata: {json.dumps(ev, default=str)}\n\n".encode("utf-8"))
                        after = ev["seq"]
                    if events:
                        self.wfile.flush()
                        last_write = time.monotonic()
                    elif time.monotonic() - last_write > KEEPALIVE_S:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last_write = time.monotonic()
                    else:
                        time.sleep(POLL_INTERVAL_S)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass   # client went away
            self.close_connection = True

    return Handler


class LiveFeedServer:
    """The HTTP server on a background thread. start() returns once it's listening."""

    def __init__(self, db_path: str, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        if host not in LOOPBACK_HOSTS:
            raise ValueError(f"live_feed binds loopback only (got {host!r}); "
                             "use a VPN or SSH tunnel for remote access")
        self.store = LiveStore(db_path)
        self._stop = threading.Event()
        self.httpd = ThreadingHTTPServer((host, port), make_handler(self.store, self._stop))
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def start(self) -> "LiveFeedServer":
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="live_feed", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stream live_store.py's database over loopback HTTP / SSE.")
    p.add_argument("--db", default="live_store.db", help="SQLite file written by live_store.py")
    p.add_argument("--host", default="127.0.0.1", help="loopback address to bind (non-loopback is refused)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = p.parse_args(argv)
    try:
        server = LiveFeedServer(args.db, args.host, args.port)
    except ValueError as e:
        p.error(str(e))
    print(f"[live_feed] serving {args.db} on http://{args.host}:{server.port}  (Ctrl+C to stop)")
    try:
        server.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
