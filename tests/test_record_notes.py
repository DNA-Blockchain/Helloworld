"""Record notes: challenges, improvements and replies about chain entries, and the personal-information
rule every node enforces on them."""
import pytest

import research_ledger
import research_provenance as rp
import research_viewer

ABOUT = "aa11bb22cc33dd44ee55ff6677889900"


def note(text="The title leaves out that this is a phase 2 trial.", kind="challenge", record=None):
    return rp.create_public_record_note_event(note_kind=kind, about_event_id=ABOUT, text=text,
                                              about_record=record, confirm_publication=True)


def test_a_note_is_created_and_validated():
    event = note(record={"source": "pubmed", "external_id": "111"})
    assert event["event_type"] == "public_record_note" and event["about_record"] == {"source": "pubmed", "external_id": "111"}
    rp.validate_public_provenance(event)
    with pytest.raises(PermissionError):
        rp.create_public_record_note_event(note_kind="challenge", about_event_id=ABOUT, text="x")


@pytest.mark.parametrize("change, message", [
    ({"note_kind": "delete"}, "unknown kind"),
    ({"text": "x" * 1001}, "1-1000 characters"),
    ({"text": " padded "}, "1-1000 characters"),
    ({"text": "line one\x07bell"}, "control characters"),
    ({"about_event_id": "not-an-id"}, "invalid about_event_id"),
    ({"about_record": {"source": "somewhere", "external_id": "1"}}, "allowed public source"),
    ({"extra": 1}, "unsupported fields"),
])
def test_invalid_notes_are_refused(change, message):
    event = note() | change
    with pytest.raises(ValueError, match=message):
        rp.validate_public_provenance(event)


def test_a_note_cannot_be_about_itself():
    event = note()
    with pytest.raises(ValueError, match="about itself"):
        rp.validate_public_provenance(event | {"about_event_id": event["event_id"]})


@pytest.mark.parametrize("text, found", [
    ("Contact me at jane.doe@example.org about this.", "an email address"),
    ("Call +1 (918) 555-0140 for the data.", "a phone number"),
    ("My SSN is 123-45-6789.", "an ID number"),
    ("The patient's date of birth is in the file.", "a date of birth"),
    ("Samples were kept at 1200 Oak Ridge Road until May.", "a street address"),
    ("My sequence is ACGTTGCAACGTTGCAACGTTGCAACGTTGCAAC.", "a DNA or RNA sequence"),
])
def test_personal_information_is_refused_by_every_node(text, found):
    assert found in rp.personal_information(text)          # "123-45-6789" also reads as a phone number
    event = note() | {"text": text}
    with pytest.raises(ValueError, match="personal information"):
        rp.validate_public_provenance(event)


@pytest.mark.parametrize("text", [
    "PMID 42760781 reports the same result as NCT00897455.",
    "Published 2026-09-29; see rs123456789 and BRCA1/2 p.R175H.",
    "DOI 10.1038/s41586-020-2649-2 has the full table of 12,345 samples.",
    "Between 2019 and 2021 the trial enrolled 480 people.",
])
def test_ordinary_research_text_is_not_mistaken_for_personal_information(text):
    assert rp.personal_information(text) == []
    rp.validate_public_provenance(note() | {"text": text})


def _ledger_with(tmp_path, *events):
    path = tmp_path / "node-0" / "research_ledger_node-0.json"
    path.parent.mkdir()
    ledger = research_ledger.ResearchLedger(str(path))
    for index, event in enumerate(events, start=1):
        assert ledger.add_block({"origin": 0, "index": index, "hash_hex": f"{index:064x}",
                                 "research_provenance": event})
    return tmp_path


def test_nodes_store_notes_but_not_ones_with_personal_information(tmp_path):
    good = note()
    bad = dict(note(), text="Email me: a@b.co")
    assert research_ledger.event_of({"research_provenance": good})[0] == "public_record_note"
    assert research_ledger.event_of({"research_provenance": bad}) is None


def test_the_viewer_shows_notes_beside_the_record_they_are_about(tmp_path):
    ranking = {"schema": "research-ranking.v1", "query": "brca1", "all_records_sha256": "a" * 64, "ranked": [
        {"source": "pubmed", "external_id": "111", "title": "BRCA1 carriers", "source_url": "https://example.org/1",
         "published_at": "2026", "record_sha256": "1" * 64},
        {"source": "pubmed", "external_id": "222", "title": "Other paper", "source_url": "https://example.org/2",
         "published_at": "2026", "record_sha256": "2" * 64}]}
    records = rp.create_public_research_records_event(ranking, confirm_publication=True)
    about_one = rp.create_public_record_note_event(
        note_kind="improvement", about_event_id=records["event_id"], text="Add the trial phase to the title.",
        about_record={"source": "pubmed", "external_id": "111"}, confirm_publication=True)
    about_all = rp.create_public_record_note_event(
        note_kind="challenge", about_event_id=records["event_id"], text="This batch mixes two topics.",
        confirm_publication=True)
    data = research_viewer.collect(str(_ledger_with(tmp_path, records, about_one, about_all)))
    by_id = {r["external_id"]: r for r in data["records"]}
    assert [n["text"] for n in by_id["111"]["notes"]] == ["Add the trial phase to the title.", "This batch mixes two topics."]
    assert [n["text"] for n in by_id["222"]["notes"]] == ["This batch mixes two topics."]
    assert by_id["111"]["title"] == "BRCA1 carriers"                      # a note never changes the record
