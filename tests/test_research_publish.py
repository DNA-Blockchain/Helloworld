import json

import pytest

import research_analysis
import research_fetch
import research_publish
from research_provenance import (
    ResearchProvenanceQueue,
    create_public_research_records_event,
    validate_public_provenance,
)


def ranking():
    return research_analysis.run(json.loads(json.dumps(research_fetch.FIXTURE_REQUEST)))


def test_event_carries_public_bibliographic_records_without_abstracts():
    event = create_public_research_records_event(ranking(), confirm_publication=True)

    assert event["event_type"] == "public_research_records"
    assert event["record_count"] == 3
    assert event["sources"] == ["clinicaltrials.gov", "pubmed"]
    assert event["ranking_sha256"] == ranking()["all_records_sha256"]
    first = event["records"][0]
    assert set(first) == {"source", "external_id", "title", "source_url", "published_at", "record_sha256"}
    assert first["external_id"] == "SYNTH-PM-1"
    assert "abstract" not in json.dumps(event)


def test_publication_requires_confirmation():
    with pytest.raises(PermissionError):
        create_public_research_records_event(ranking())


@pytest.mark.parametrize("mutate, message", [
    (lambda e: e["records"][0].update(source="hospital_db"), "public source"),
    (lambda e: e["records"][0].update(abstract="text"), "unsupported fields"),
    (lambda e: e["records"][0].update(record_sha256="nothex"), "invalid hash"),
    (lambda e: e.update(record_count=9), "record_count"),
    (lambda e: e.update(sources=["pubmed"]), "sources do not match"),
    (lambda e: e.update(extra="x"), "unsupported fields"),
])
def test_validation_rejects_tampered_events(mutate, message):
    event = create_public_research_records_event(ranking(), confirm_publication=True)
    mutate(event)
    with pytest.raises(ValueError, match=message):
        validate_public_provenance(event)


def test_queue_round_trip(tmp_path):
    queue = ResearchProvenanceQueue(tmp_path / "outbox")
    event = create_public_research_records_event(ranking(), confirm_publication=True)
    path = queue.enqueue(event)
    queued, queued_path = queue.peek()
    assert queued == event and queued_path == path
    queue.acknowledge(path, event["event_id"])
    assert queue.peek() is None


def test_cli_dry_run_queues_nothing_and_confirm_queues(tmp_path, capsys):
    ranked = tmp_path / "RANKED.OUT"
    ranked.write_text(json.dumps(ranking()))
    outbox = tmp_path / "outbox"

    assert research_publish.main([str(ranked), "--outbox", str(outbox)]) == 0
    assert "Dry run" in capsys.readouterr().out
    assert not outbox.exists()

    assert research_publish.main([str(ranked), "--outbox", str(outbox), "--confirm-publication"]) == 0
    assert len(list(outbox.glob("*.json"))) == 1


def test_cli_rejects_non_ranking(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other"}))
    assert research_publish.main([str(bad)]) == 2
