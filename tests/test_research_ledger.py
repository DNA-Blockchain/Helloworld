import asyncio
import hashlib
import json
import os
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import research_analysis
import research_fetch
import research_viewer
from digital_dna import DigitalDNA
from dna_binary_codec import encode_to_dna
from network_node import NetworkNode
from research_ledger import ResearchLedger
from research_provenance import create_public_research_records_event
from token_ledger import TokenLedger

IDENTITY = encode_to_dna(hashlib.sha256(b"test-network-identity").digest())


def research_event():
    ranking = research_analysis.run(json.loads(json.dumps(research_fetch.FIXTURE_REQUEST)))
    return create_public_research_records_event(ranking, confirm_publication=True)


def node(node_id, port, peers, tmp_path, **kwargs):
    directory = tmp_path / f"node-{node_id}"
    directory.mkdir(exist_ok=True)
    dna = DigitalDNA(seed_label=f"rl-{node_id}", dna_path=str(directory / "dna.json"))
    tokens = TokenLedger(store_path=str(tmp_path / f"tokens-{node_id}.json"))
    return NetworkNode(node_id, port, peers, dna, IDENTITY, tokens, str(directory), **kwargs)


async def close(*nodes):
    for n in nodes:
        n.server.close()
        await n.server.wait_closed()


@pytest.mark.asyncio
async def test_published_event_is_replicated_by_gossip_and_by_ledger_sync(tmp_path):
    n0 = node(0, 19701, [19702], tmp_path)
    n1 = node(1, 19702, [19701], tmp_path)
    n2 = node(2, 19703, [19701], tmp_path)   # offline during gossip, catches up later
    for n in (n0, n1, n2):
        await n.start_server()
    try:
        event = research_event()
        assert await n0.mine_and_gossip(extra={"research_provenance": event}, run_enrichers=False)
        await asyncio.sleep(0.4)

        for holder in (n0, n1):
            [entry] = holder.research_ledger.entries()
            assert entry["event_id"] == event["event_id"] and entry["origin"] == 0
            assert entry["block"]["research_provenance"]["records"][0]["external_id"] == "SYNTH-PM-1"
        assert len(n2.research_ledger) == 0

        assert await n2.sync_research_ledger() == 1
        assert n2.research_ledger.entries()[0]["event_id"] == event["event_id"]
        assert await n2.sync_research_ledger() == 0          # nothing new, no duplicates
        assert all(n.research_ledger.verify()[0] for n in (n0, n1, n2))

        # an ordinary block is not a research event
        await n0.mine_and_gossip()
        await asyncio.sleep(0.3)
        assert len(n1.research_ledger) == 1
    finally:
        await close(n0, n1, n2)


@pytest.mark.asyncio
async def test_tampered_ledger_copy_is_rejected(tmp_path):
    n0 = node(0, 19711, [19712], tmp_path)
    n1 = node(1, 19712, [19711], tmp_path)
    await n0.start_server()
    await n1.start_server()
    try:
        await n0.mine_and_gossip(extra={"research_provenance": research_event()}, run_enrichers=False)
        await asyncio.sleep(0.4)
        block = json.loads(json.dumps(n1.research_ledger.entries()[0]["block"]))
        assert n1._block_authentic(block)
        block["research_provenance"]["records"][0]["title"] = "Forged title"
        assert not n1._block_authentic(block)
    finally:
        await close(n0, n1)


def test_restarted_node_backfills_from_current_and_archived_chains(tmp_path):
    key = str(tmp_path / "node-0.pem")
    first = node(0, 19721, [], tmp_path, signing_key_path=key)
    event = research_event()
    asyncio.run(first.mine_and_gossip(extra={"research_provenance": event}, run_enrichers=False))

    # the daily rotation moves the chain into the archive; the ledger stays
    archive = tmp_path / "archive" / "2026-09-28" / "node-0"
    archive.mkdir(parents=True)
    os.replace(tmp_path / "node-0" / "chain_node-0.json", archive / "chain_node-0.json")
    os.remove(tmp_path / "node-0" / "research_ledger_node-0.json")

    restarted = node(0, 19721, [], tmp_path, signing_key_path=key)
    assert restarted.backfill_research_ledger() == 1
    assert restarted.research_ledger.entries()[0]["event_id"] == event["event_id"]
    assert restarted.backfill_research_ledger() == 0


def test_ledger_ignores_ordinary_and_invalid_blocks(tmp_path):
    ledger = ResearchLedger(str(tmp_path / "ledger.json"))
    assert not ledger.add_block({"origin": 0, "index": 1})
    bad = research_event()
    bad["records"][0]["source"] = "hospital_db"
    assert not ledger.add_block({"origin": 0, "index": 2, "research_provenance": bad})
    assert not ledger.add_block({"origin": 0, "index": 3, "public_dataset_summary": {
        "dataset_id": "x", "classification": "private"}})
    good = {"origin": 0, "index": 4, "research_provenance": research_event()}
    assert ledger.add_block(good) and not ledger.add_block(good)
    assert len(ResearchLedger(str(tmp_path / "ledger.json"))) == 1   # persisted


def test_viewer_api_lists_searches_and_exports(tmp_path):
    for node_id in (0, 1):
        directory = tmp_path / f"node-{node_id}"
        directory.mkdir()
        ledger = ResearchLedger(str(directory / f"research_ledger_node-{node_id}.json"))
        ledger.add_block({"origin": 0, "index": 7, "hash_hex": "ab", "research_provenance": research_event_fixed})
        ledger.add_block({"origin": 1, "index": 3, "hash_hex": "cd", "public_dataset_summary": {
            "dataset_id": "3f2a", "format": "FASTA", "classification": "public", "dataset_sha256": "e" * 64}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), research_viewer.make_handler(str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    get = lambda path: json.loads(urllib.request.urlopen(base + path, timeout=5).read())
    try:
        status = get("/api/status")
        assert status == {"nodes": status["nodes"], "events": 2, "records": 3, "datasets": 1}
        assert all(n["ledger_ok"] for n in status["nodes"].values())

        records = get("/api/records?q=base+editing&source=pubmed")
        assert [r["external_id"] for r in records] == ["SYNTH-PM-1"]
        assert records[0]["replicas"] == [0, 1]
        # the publishing query is searchable too: both PubMed records came from it
        assert len(get("/api/records?q=crispr&source=pubmed")) == 2
        one = get("/api/records/clinicaltrials.gov/SYNTH-CT-1")
        assert one["record"]["title"].startswith("Trial of CRISPR")
        assert get("/api/datasets")[0]["dataset_id"] == "3f2a"
        export = get("/api/export")
        assert {e["kind"] for e in export["events"]} == {"public_research_records", "public_dataset_summary"}
        assert all("block" in e for e in export["events"])
        assert b"Research Ledger" in urllib.request.urlopen(base + "/", timeout=5).read()
    finally:
        server.shutdown()
        server.server_close()


research_event_fixed = research_event()
