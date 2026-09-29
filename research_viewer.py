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
research_viewer.py
==================
Local, read-only viewer and JSON API for the replicated research ledgers
(research_ledger.py): every public research record and dataset summary
published on the node network, with how many nodes hold a copy.

    python research_viewer.py            # http://127.0.0.1:8791
    python research_viewer.py --port 8800

Endpoints (all GET, bound to 127.0.0.1 by default):
    /                                   searchable page
    /api/status                         nodes, ledger integrity, counts
    /api/records?q=crispr&source=pubmed published records (newest first)
    /api/records/<source>/<external_id> one record and every event that published it
    /api/datasets                       published dataset summaries
    /api/events                         published events with their replicas
    /api/export                         everything, with the original signed blocks
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from research_ledger import load_all_ledgers

DEFAULT_PORT = 8791
DEFAULT_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autonomous")
MAX_LIMIT = 500


def collect(base_dir: str) -> dict:
    """Merge every node's ledger: each published event once, with the ids of
    the nodes holding a copy, plus flattened records and datasets."""
    ledgers = load_all_ledgers(base_dir)
    nodes = {}
    events: dict[tuple[int, str], dict] = {}
    for node_id, ledger in ledgers.items():
        ok, message = ledger.verify()
        nodes[node_id] = {"entries": len(ledger), "ledger_ok": ok, "ledger_msg": message}
        for entry in ledger.entries():
            key = (entry["origin"], entry["event_id"])
            merged = events.setdefault(key, {
                "event_id": entry["event_id"],
                "kind": entry["kind"],
                "origin": entry["origin"],
                "origin_index": entry.get("origin_index"),
                "block_hash_hex": entry["block"].get("hash_hex"),
                "replicas": [],
                "block": entry["block"],
            })
            merged["replicas"].append(node_id)

    records, datasets = [], []
    for event in events.values():
        block = event["block"]
        if event["kind"] == "public_research_records":
            payload = block["research_provenance"]
            for record in payload["records"]:
                records.append({
                    **record,
                    "event_id": event["event_id"],
                    "published_at": payload["created_at"],
                    "record_published_date": record["published_at"],
                    "query": payload["query"],
                    "origin": event["origin"],
                    "replicas": sorted(event["replicas"]),
                })
        elif event["kind"] == "public_dataset_summary":
            datasets.append({
                **block["public_dataset_summary"],
                "origin": event["origin"],
                "replicas": sorted(event["replicas"]),
            })
    records.sort(key=lambda r: r["published_at"], reverse=True)
    return {
        "nodes": nodes,
        "events": sorted(events.values(), key=lambda e: (e["origin"], e["origin_index"] or 0)),
        "records": records,
        "datasets": datasets,
    }


def _public_event(event: dict, include_block: bool = False) -> dict:
    shown = {key: value for key, value in event.items() if key != "block"}
    shown["replicas"] = sorted(event["replicas"])
    if include_block:
        shown["block"] = event["block"]
    return shown


def search_records(records: list[dict], query: str = "", source: str = "", limit: int = 100) -> list[dict]:
    terms = [term for term in query.lower().split() if term]
    matched = []
    for record in records:
        if source and record["source"] != source:
            continue
        text = f"{record['title']} {record['external_id']} {record['query']}".lower()
        if all(term in text for term in terms):
            matched.append(record)
    return matched[:limit]


def make_handler(base_dir: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):   # keep the console quiet
            pass

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, value, status: int = 200, extra: dict | None = None):
            self._send(status, json.dumps(value, indent=1).encode("utf-8"), "application/json", extra)

        def do_GET(self):
            url = urlparse(self.path)
            params = {key: values[-1] for key, values in parse_qs(url.query).items()}
            path = url.path.rstrip("/") or "/"
            data = collect(base_dir)
            if path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/status":
                self._json({
                    "nodes": data["nodes"],
                    "events": len(data["events"]),
                    "records": len(data["records"]),
                    "datasets": len(data["datasets"]),
                })
            elif path == "/api/records":
                try:
                    limit = max(1, min(int(params.get("limit", 100)), MAX_LIMIT))
                except ValueError:
                    return self._json({"error": "limit must be a number"}, 400)
                self._json(search_records(data["records"], params.get("q", ""), params.get("source", ""), limit))
            elif path.startswith("/api/records/"):
                parts = [unquote(part) for part in path[len("/api/records/"):].split("/", 1)]
                if len(parts) != 2:
                    return self._json({"error": "use /api/records/<source>/<external_id>"}, 400)
                hits = [r for r in data["records"] if r["source"] == parts[0] and r["external_id"] == parts[1]]
                if not hits:
                    return self._json({"error": "record not found"}, 404)
                self._json({"record": hits[0], "published_in": [
                    {"event_id": h["event_id"], "published_at": h["published_at"], "replicas": h["replicas"]}
                    for h in hits
                ]})
            elif path == "/api/datasets":
                self._json(data["datasets"])
            elif path == "/api/events":
                self._json([_public_event(event) for event in data["events"]])
            elif path == "/api/export":
                self._json(
                    {"nodes": data["nodes"], "events": [_public_event(e, True) for e in data["events"]]},
                    extra={"Content-Disposition": 'attachment; filename="research-ledger-export.json"'},
                )
            else:
                self._json({"error": "not found"}, 404)

    return Handler


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Research Ledger</title>
<style>
:root{--bg:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e3e8;--accent:#2457c5;--ok:#1d7a3a;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececf0;--muted:#9a9aa3;--line:#2c2c31;--accent:#7aa2ff;--ok:#5fcf85;--bad:#ff8a80}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
.muted{color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}
form{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}
input,select,button{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
input{flex:1;min-width:200px}button{cursor:pointer}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:13px;color:var(--muted);font-weight:600}a{color:var(--accent)}
.scroll{overflow-x:auto}code{font-size:12px}
</style></head><body><main>
<h1>Research Ledger</h1>
<div id="status" class="muted">Loading...</div>
<form id="search"><input id="q" placeholder="Search titles, IDs, queries"><select id="source">
<option value="">All sources</option><option>pubmed</option><option>europe_pmc</option>
<option>clinicaltrials.gov</option><option>nih_reporter</option><option>clinvar</option></select><button>Search</button>
<a href="/api/export" download><button type="button">Export JSON</button></a></form>
<h2>Published records</h2><div class="scroll"><table><thead><tr><th>Record</th><th>Source</th><th>Date</th>
<th>Published</th><th>Copies</th></tr></thead><tbody id="records"></tbody></table></div>
<h2>Datasets</h2><div class="scroll"><table><thead><tr><th>Dataset</th><th>Format</th><th>SHA-256</th>
<th>Copies</th></tr></thead><tbody id="datasets"></tbody></table></div>
<p class="muted">Public bibliographic records and dataset summaries only. Each copy is the original signed block,
re-verified by every node that holds it. Scores and rankings are reading order, not medical evidence.</p>
</main><script>
const cell = (row, text, href) => { const td = row.insertCell(); if (href) { const a = document.createElement('a');
  a.href = href; a.textContent = text; a.rel = 'noopener'; td.append(a); } else { td.textContent = text; } return td; };
async function load() {
  const status = await (await fetch('/api/status')).json();
  const nodes = Object.entries(status.nodes);
  const el = document.getElementById('status'); el.textContent = '';
  el.append(`${status.records} records, ${status.datasets} datasets, ${status.events} events across ${nodes.length} node ledgers: `);
  for (const [id, n] of nodes) { const s = document.createElement('span'); s.className = n.ledger_ok ? 'ok' : 'bad';
    s.textContent = `node-${id} ${n.entries} ${n.ledger_ok ? 'intact' : 'FAILED'}  `; el.append(s); }
  const params = new URLSearchParams({q: document.getElementById('q').value, source: document.getElementById('source').value});
  const records = await (await fetch('/api/records?' + params)).json();
  const body = document.getElementById('records'); body.textContent = '';
  for (const r of records) { const row = body.insertRow(); cell(row, r.title, /^https?:/.test(r.source_url) ? r.source_url : null);
    cell(row, `${r.source}:${r.external_id}`); cell(row, r.record_published_date);
    cell(row, r.published_at.slice(0, 19).replace('T', ' ')); cell(row, `${r.replicas.length} (node ${r.replicas.join(', ')})`); }
  if (!records.length) cell(body.insertRow(), 'No matching records.');
  const datasets = await (await fetch('/api/datasets')).json();
  const dbody = document.getElementById('datasets'); dbody.textContent = '';
  for (const d of datasets) { const row = dbody.insertRow(); cell(row, d.dataset_id); cell(row, d.format || '');
    cell(row, (d.dataset_sha256 || '').slice(0, 16) + '...'); cell(row, `${d.replicas.length}`); }
  if (!datasets.length) cell(dbody.insertRow(), 'No datasets published yet.');
}
document.getElementById('search').addEventListener('submit', e => { e.preventDefault(); load(); });
load();
</script></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-dir", default=DEFAULT_BASE_DIR, help="autonomous/ directory holding node-*/")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.base_dir))
    print(f"Research ledger viewer: http://{args.host}:{args.port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
