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
