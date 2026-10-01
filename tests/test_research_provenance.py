import asyncio
import hashlib
import json

import pytest

import dna_shell
import local_ai_retrieval
from research_provenance import (
    ResearchProvenanceQueue,
    create_public_data_hash_event,
    create_public_provenance,
    validate_public_provenance,
)
from research_catalog import ResearchCatalog


def test_provenance_contains_only_hashes_and_public_source_metadata():
    event = create_public_provenance(
        "private-looking but explicitly public query",
        [{"title": "record text", "abstract": "sequence or content stays local"}],
        ["pubmed"],
        "answer text",
        model="llama3.2",
    )

    assert event["classification"] == "public"
    assert event["sources"] == ["pubmed"]
    assert event["record_count"] == 1
    assert event["model"] == "llama3.2"
    assert all(len(event[name]) == 64 for name in (
        "query_sha256", "records_sha256", "answer_sha256"
    ))
    assert not {"query", "records", "abstract", "sequence", "answer"} & set(event)
    validate_public_provenance(event)


def test_provenance_queue_round_trips_then_acknowledges(tmp_path):
    queue = ResearchProvenanceQueue(tmp_path / "outbox")
    event = create_public_provenance("gene", [], ["ensembl"], "No records")

    queued_path = queue.enqueue(event)
    loaded, loaded_path = queue.peek()

    assert loaded == event
    assert queued_path == loaded_path
    assert queue.acknowledge(loaded_path, event["event_id"]) is None
    assert queue.peek() is None


def test_provenance_queue_rejects_content_fields(tmp_path):
    queue = ResearchProvenanceQueue(tmp_path / "outbox")
    event = create_public_provenance("query", [], ["pubmed"], "answer")
    event["abstract"] = "must not be published"

    with pytest.raises(ValueError, match="unsupported fields"):
        queue.enqueue(event)


def test_public_data_hash_events_are_confirmed_and_strict(tmp_path):
    digest = hashlib.sha256(b"synthetic public test data").hexdigest()
    with pytest.raises(PermissionError, match="explicit confirmation"):
        create_public_data_hash_event(
            data_sha256=digest,
            data_kind="dataset",
            classification="public",
        )
    with pytest.raises(PermissionError, match="classified public"):
        create_public_data_hash_event(
            data_sha256=digest,
            data_kind="dataset",
            classification="restricted",
            confirm_hash_publication=True,
        )

    event = create_public_data_hash_event(
        data_sha256=digest,
        data_kind="biological_sequence",
        classification="public",
        confirm_hash_publication=True,
    )
    queue = ResearchProvenanceQueue(tmp_path / "outbox")
    queue.enqueue(event)
    queued, _ = queue.peek()

    assert queued == event
    assert set(event) == {
        "schema_version", "event_type", "event_id", "created_at",
        "classification", "data_kind", "data_sha256",
    }
    validate_public_provenance(event)


def test_research_ask_requires_public_query_confirmation(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        dna_shell, "search_public_sources",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(SystemExit) as error:
        dna_shell.main([
            "research-ask", "query", "--model", "local-model",
            "--catalog", str(tmp_path / "catalog.sqlite3"),
        ])

    assert error.value.code == 2
    assert calls == []
    assert not (tmp_path / "catalog.sqlite3").exists()


def test_research_ask_searches_catalogs_answers_and_queues_hashes_only(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(dna_shell, "search_public_sources", lambda query, sources, max_results: [{
        "source": "clinvar",
        "external_id": "VCV000001",
        "title": "BRCA1 synthetic public record",
        "abstract": "synthetic local test evidence",
        "source_url": "https://example.org/VCV000001",
        "classification": "public",
        "rights_status": "unknown",
        "terms_url": "https://example.org/terms",
    }])

    class Response:
        status = 200

        def read(self):
            return b'{"response":"The catalog record reports synthetic evidence [1]."}'

    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "127.0.0.1"

        def request(self, method, path, body, headers):
            payload = json.loads(body)
            assert payload["model"] == "local-model"
            assert "synthetic local test evidence" in payload["prompt"]

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(local_ai_retrieval.http.client, "HTTPConnection", Connection)
    catalog_path = tmp_path / "catalog.sqlite3"
    outbox = tmp_path / "outbox"
    assert dna_shell.main([
        "research-ask", "BRCA1", "--sources", "clinvar", "--model", "local-model",
        "--confirm-public-query", "--publish-provenance", "--catalog", str(catalog_path),
        "--provenance-outbox", str(outbox),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    event, event_path = ResearchProvenanceQueue(outbox).peek()
    assert output["answer"] == "The catalog record reports synthetic evidence [1]."
    assert output["records_fetched"] == 1
    assert output["provenance_queued"] is True
    assert output["on_chain"] is False
    assert ResearchCatalog(catalog_path).count(classification="public") == 1
    assert event_path.exists()
    assert event["sources"] == ["clinvar"]
    assert not {"query", "records", "answer", "abstract"} & set(event)


def test_network_consumes_queued_hash_provenance_without_record_content(tmp_path):
    from digital_dna import DigitalDNA
    from network_node import NetworkNode
    from token_ledger import TokenLedger

    queue = ResearchProvenanceQueue(tmp_path / "outbox")
    event = create_public_provenance(
        "query", [{"abstract": "private source content"}], ["pubmed"], "answer"
    )
    path = queue.enqueue(event)
    dna = DigitalDNA(seed_label="provenance-test", dna_path=str(tmp_path / "dna.json"))
    node = NetworkNode(
        91, 19691, [], dna, "identity", TokenLedger(store_path=str(tmp_path / "ledger.json")),
        str(tmp_path), provenance_queue=queue,
    )
    node.peers = [("127.0.0.1", 19692)]
    mined = []

    async def fake_start_server():
        node.server = type("Server", (), {
            "close": lambda self: None,
            "wait_closed": lambda self: asyncio.sleep(0),
        })()

    async def fake_mine_and_gossip(extra=None, run_enrichers=True):
        mined.append((extra, run_enrichers))
        stop_event.set()
        return True

    node.start_server = fake_start_server
    node.mine_and_gossip = fake_mine_and_gossip
    stop_event = asyncio.Event()
    asyncio.run(node.run(stop_event))

    assert mined == [({"research_provenance": event}, False)]
    assert not path.exists()


def test_legacy_network_enrichers_publish_digests_not_provider_records(monkeypatch):
    import run_consolidated_network as runner

    class TrialResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"studies": [{
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT00000000"}
                }
            }]}

    monkeypatch.setattr(runner.requests, "get", lambda *args, **kwargs: TrialResponse())
    research = asyncio.run(runner.research_enricher(81000))
    assert research["research_provenance"]["record_id_sha256"] == hashlib.sha256(
        b"NCT00000000"
    ).hexdigest()
    assert "NCT00000000" not in json.dumps(research)

    snapshot = {"price": 42, "transaction": "sensitive-looking fixture"}
    monkeypatch.setattr(runner, "build_external_info_snapshot", lambda: snapshot)
    external = asyncio.run(runner.external_info_enricher(81004))
    assert external["external_info_provenance"]["snapshot_sha256"] == hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert "42" not in json.dumps(external)
    assert "sensitive-looking fixture" not in json.dumps(external)


def test_node_cli_keeps_provenance_local_when_no_peers_are_configured(tmp_path):
    import run_node_cli

    outbox = ResearchProvenanceQueue(tmp_path / "outbox")
    event = create_public_provenance(
        "BRCA1", [{"abstract": "record abstract stays local"}], ["clinvar"],
        "model answer stays local", model="llama3.2",
    )
    outbox.enqueue(event)
    workdir = tmp_path / "node"

    result = asyncio.run(run_node_cli.main([
        "--id", "73",
        "--port", "19693",
        "--duration", "0.2",
        "--workdir", str(workdir),
        "--provenance-queue", str(tmp_path / "outbox"),
    ]))

    assert result == 0
    chain = json.loads((workdir / "chain_node-73.json").read_text(encoding="utf-8"))
    blocks = chain["blocks"]
    provenance_blocks = [
        block["payload"]["research_provenance"]
        for block in blocks
        if "research_provenance" in block["payload"]
    ]
    assert provenance_blocks == []
    queued, _ = outbox.peek()
    assert queued == event


def test_node_cli_keeps_hash_event_queued_until_peer_accepts_it(tmp_path):
    import run_node_cli

    queue = ResearchProvenanceQueue(tmp_path / "outbox")
    digest = hashlib.sha256(b"public dataset payload").hexdigest()
    event = create_public_data_hash_event(
        data_sha256=digest,
        data_kind="dataset",
        classification="public",
        confirm_hash_publication=True,
    )
    queue.enqueue(event)
    workdir = tmp_path / "hash-node"

    result = asyncio.run(run_node_cli.main([
        "--id", "74",
        "--port", "19694",
        "--duration", "0.2",
        "--workdir", str(workdir),
        "--provenance-queue", str(tmp_path / "outbox"),
        "--peers", "127.0.0.1:19695",
        "--tofu",
    ]))

    assert result == 0
    chain = json.loads((workdir / "chain_node-74.json").read_text(encoding="utf-8"))
    blocks = chain["blocks"]
    hash_events = [
        block["payload"]["research_provenance"]
        for block in blocks
        if "research_provenance" in block["payload"]
    ]
    assert hash_events == [event]
    assert digest in json.dumps(hash_events)
    queued, _ = queue.peek()
    assert queued == event
