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

import json
import sys

MAX_INPUT_BYTES = 65536
MAX_SOURCES = 16

if len(sys.argv) != 2:
    raise SystemExit("usage: research_result_summary.py <research-tool-response.json>")

with open(sys.argv[1], "rb") as source_file:
    raw = source_file.read(MAX_INPUT_BYTES + 1)

if len(raw) > MAX_INPUT_BYTES:
    raise SystemExit("research response exceeds the 64-KiB pilot limit")

response = json.loads(raw.decode("utf-8"))
if not isinstance(response, dict) or response.get("ok") is not True:
    raise SystemExit("input is not a successful research-tool response")
if response.get("action") != "research":
    raise SystemExit("input action must be research")

result = response.get("result")
if not isinstance(result, dict):
    raise SystemExit("research response result must be an object")
topic = result.get("topic")
sources = result.get("sources")
if not isinstance(topic, dict) or not isinstance(sources, dict):
    raise SystemExit("research response topic and sources must be objects")
if len(sources) > MAX_SOURCES:
    raise SystemExit("research response contains too many sources")

summary_sources = []
total_records = 0
for name in sorted(sources):
    source = sources[name]
    if not isinstance(name, str) or not isinstance(source, dict):
        raise SystemExit("research source entries must be named objects")
    status = source.get("status")
    if not isinstance(status, dict) or not isinstance(status.get("status"), str):
        raise SystemExit("research source status must contain a status string")
    count = source.get("record_count")
    ids = source.get("ids")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise SystemExit("research source record_count must be a nonnegative integer")
    if not isinstance(ids, list) or count != len(ids):
        raise SystemExit("research source record_count does not match its ID list")
    total_records += count
    summary_sources.append(
        {"source": name, "status": status["status"], "record_count": count}
    )

new_ids = result.get("new_ids")
if not isinstance(new_ids, list) or len(new_ids) > 10000:
    raise SystemExit("research response new_ids must be an array of at most 10000 items")

output = {
    "schema": "blockchain-dna.host-pilot-summary.v1",
    "topic": topic,
    "sources": summary_sources,
    "total_records": total_records,
    "new_id_count": len(new_ids),
    "chain_write": "disabled",
    "interpretation": "counts and statuses only; no scientific conclusions",
}
print(json.dumps(output))
