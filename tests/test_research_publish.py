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
