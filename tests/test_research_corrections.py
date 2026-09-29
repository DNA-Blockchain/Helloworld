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

"""The kernel text-decoding audit and public_research_correction events."""

import json

import pytest

import research_corrections
import research_viewer
from research_ledger import ResearchLedger, published_corrections
from research_provenance import (
    create_public_research_correction_event,
    create_public_research_records_event,
    validate_public_provenance,
)

THETA = {"source": "europe_pmc", "external_id": "PPR1", "title": "Targeting Polθ Helicase",
         "abstract": "", "source_url": "https://example.invalid/ppr1", "published_at": "2026",
         "classification": "public"}
BETA = {"source": "pubmed", "external_id": "42", "title": "p53 and beta-Catenin Signatures",
        "abstract": "β-catenin values ≥ 5 were kept.", "source_url": "https://example.invalid/42",
        "published_at": "2025", "classification": "public"}
PLAIN = {"source": "pubmed", "external_id": "7", "title": "BRCA1 carriers", "abstract": "",
         "source_url": "https://example.invalid/7", "published_at": "2024", "classification": "public"}


def as_published(raw, faulty):
    record = research_corrections.faulty_kernel_record(raw) if faulty else \
        research_corrections.research_analysis.validate_record(raw)
    return {"source": record["source"], "external_id": record["external_id"], "title": record["title"][:160],
            "source_url": record["source_url"], "published_at": record["published_at"],
            "record_sha256": research_corrections.record_hash(record)}


def records_event(*published):
    ranking = {"schema": "research-ranking.v1", "query": "Ovarian Neoplasms BRCA1", "all_records_sha256": "a" * 64,
               "ranked": list(published)}
    return create_public_research_records_event(ranking, confirm_publication=True)


def test_faulty_kernel_keeps_only_the_low_byte():
    text = research_corrections.faulty_kernel_text
    assert text("Polθ") == "Pol\xb8"
    assert text("45‑Year") == "45\x11Year"
    assert text("≥ 5") == "e 5"                    # invisible damage: U+2265 -> 'e'
    assert text("café") == "café"            # Latin-1 survived
    assert text("\U0001f9ec") == ">\xec"               # surrogate pair D83E DDEC


def test_audit_classifies_every_published_record():
    event = records_event(as_published(THETA, True), as_published(BETA, True), as_published(PLAIN, True),
                          dict(as_published(PLAIN, False), external_id="8", record_sha256="f" * 64),
                          dict(as_published(PLAIN, False), external_id="9"))
    fresh = {(r["source"], r["external_id"]): r for r in (THETA, BETA, PLAIN, dict(PLAIN, external_id="8"))}
    corrected = {(event["event_id"], "pubmed", "9")}
    findings = research_corrections.audit_event(event, fresh, corrected)
    assert [(f.external_id, f.status) for f in findings] == [
        ("PPR1", "damaged"), ("42", "damaged"), ("7", "ok"), ("8", "unverified"), ("9", "corrected")]
    theta, beta = findings[0], findings[1]
    assert theta.published_title == "Targeting Pol\xb8 Helicase" and theta.title == THETA["title"]
    assert beta.published_title == beta.title  # title intact; the abstract was damaged
    assert beta.record_sha256 != beta.published_sha256


def test_correction_events_name_the_hashes_they_replace():
    event = records_event(as_published(THETA, True), as_published(PLAIN, True))
    findings = research_corrections.audit_event(event, {("europe_pmc", "PPR1"): THETA, ("pubmed", "7"): PLAIN}, set())
    [correction] = research_corrections.correction_events(findings)
    validate_public_provenance(correction)
    assert correction["corrects_event_id"] == event["event_id"]
    assert correction["reason"] == "kernel-text-decoding" and correction["record_count"] == 1
    [record] = correction["records"]
    assert record["title"] == THETA["title"]
    assert record["published_record_sha256"] == event["records"][0]["record_sha256"]


def valid_correction():
    return create_public_research_correction_event(
        corrects_event_id="b" * 32, reason="kernel-text-decoding", confirm_publication=True,
        records=[{"source": "pubmed", "external_id": "42", "title": "Fixed", "record_sha256": "c" * 64,
                  "published_record_sha256": "d" * 64}])


@pytest.mark.parametrize("change", [
    lambda e: e.update(reason="typo"),
    lambda e: e.update(corrects_event_id=e["event_id"]),
    lambda e: e.update(corrects_event_id="not-an-id"),
    lambda e: e.update(note="free text"),
    lambda e: e["records"][0].update(record_sha256="d" * 64),
    lambda e: e["records"][0].update(abstract="never on the chain"),
    lambda e: e["records"][0].update(source="hospital_db"),
    lambda e: e["records"][0].update(title=""),
    lambda e: e.update(records=e["records"] * 2, record_count=2),
    lambda e: e.update(record_count=3),
])
def test_invalid_corrections_are_refused(change):
    event = valid_correction()
    change(event)
    with pytest.raises(ValueError):
        validate_public_provenance(event)


def test_corrections_need_explicit_confirmation():
    with pytest.raises(PermissionError):
        create_public_research_correction_event(corrects_event_id="b" * 32, reason="kernel-text-decoding",
                                                records=[])


def ledger_with(tmp_path, *events):
    ledger = ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json"))
    for index, event in enumerate(events, start=1):
        assert ledger.add_block({"origin": 0, "index": index, "hash_hex": f"{index:02x}",
                                 "research_provenance": event})
    return ledger


def test_cli_dry_run_publish_and_rerun(tmp_path, monkeypatch, capsys):
    (tmp_path / "node-0").mkdir()
    event = records_event(as_published(THETA, True), as_published(PLAIN, True))
    ledger = ledger_with(tmp_path, event)
    monkeypatch.setattr(research_corrections, "fetch_records",
                        lambda query, sources, max_results: {("europe_pmc", "PPR1"): THETA, ("pubmed", "7"): PLAIN})
    outbox = tmp_path / "outbox"
    args = ["--ledgers", str(tmp_path), "--outbox", str(outbox)]

    assert research_corrections.main(args) == 0
    out = capsys.readouterr().out
    assert "1 ok, 0 corrected, 1 damaged, 0 unverified" in out and "Dry run" in out and not outbox.exists()

    assert research_corrections.main(args + ["--confirm-publication"]) == 0
    [queued] = list(outbox.glob("*.json"))
    correction = json.loads(queued.read_text(encoding="utf-8"))
    validate_public_provenance(correction)
    assert correction["time_anchor"]["chain"] == "bitcoin"

    ledger.add_block({"origin": 0, "index": 9, "hash_hex": "09", "research_provenance": correction})
    capsys.readouterr()
    assert research_corrections.main(args) == 0
    assert "1 ok, 1 corrected, 0 damaged" in capsys.readouterr().out
    assert set(published_corrections(str(tmp_path))) == {(event["event_id"], "europe_pmc", "PPR1")}


def test_viewer_shows_the_corrected_record_and_what_was_published(tmp_path):
    (tmp_path / "node-0").mkdir()
    event = records_event(as_published(THETA, True), as_published(PLAIN, True))
    findings = research_corrections.audit_event(event, {("europe_pmc", "PPR1"): THETA, ("pubmed", "7"): PLAIN}, set())
    [correction] = research_corrections.correction_events(findings)
    ledger_with(tmp_path, event, correction)

    records = {r["external_id"]: r for r in research_viewer.collect(str(tmp_path))["records"]}
    assert records["PPR1"]["title"] == THETA["title"]
    assert records["PPR1"]["record_sha256"] == correction["records"][0]["record_sha256"]
    assert records["PPR1"]["correction"]["published_title"] == "Targeting Pol\xb8 Helicase"
    assert records["PPR1"]["correction"]["event_id"] == correction["event_id"]
    assert records["7"]["correction"] is None
    assert research_viewer.search_records(list(records.values()), "polθ")[0]["external_id"] == "PPR1"
