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

"""CRISPR relevance tags and modeled-run provenance on the chain."""

import json

import pytest

import remission_core
import research_analysis
import research_crispr_link as link
import research_fetch
from research_ledger import ResearchLedger, published_events
from research_provenance import (
    MODEL_RUN_DISCLAIMER,
    create_public_crispr_relevance_event,
    create_public_model_run_event,
    create_public_research_records_event,
    create_public_sequence_event,
    validate_public_provenance,
)

# A real public BRCA1 exon fragment (NCBI RefSeq), long enough to contain
# guide candidates; the same fragment crispr_guide_design.py demos with.
BRCA1_FRAGMENT = (
    "ATGGATTTATCTGCTCTTCGCGTTGAAGAAGTACAAAATGTCATTAATGCTATGCAGAAA"
    "ATCTTAGAGTGTCCCATCTGTCTGGAGTTGATCAAGGAACCTGTCTCCACAAAGTGTGAC"
    "CACATATTTTGCAAATTTTGCATGCTGAAACTTCTCAACCAGAAGAAAGGGCCTTCACAG"
)
STAGES = link.stage_ledger(remission_core.run({"reference": "ACGTACGTACGT", "sample": "ACGTACATACGT"}))
DEMO = {"reference": "ACGTACGTACGT", "sample": "ACGTACATACGT", "case_label": "synthetic demo"}


def ledger(tmp_path, *events):
    (tmp_path / "node-0").mkdir(exist_ok=True)
    book = ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json"))
    for event in events:
        index = len(book) + 1
        assert book.add_block({"origin": 0, "index": index, "hash_hex": f"{index:02x}",
                               "research_provenance": event})
    return book


def records_event():
    ranking = research_analysis.run(json.loads(json.dumps(research_fetch.FIXTURE_REQUEST)))
    ranking["query"] = "breast cancer BRCA1"
    return create_public_research_records_event(ranking, confirm_publication=True)


# ----------------------------------------------------------------- tagging

@pytest.mark.parametrize("title, expected", [
    ("CRISPR base editing of a G>A cancer variant", ["base_editing", "crispr"]),
    ("Prime editing corrects a BRCA1 frameshift", ["prime_editing"]),
    ("sgRNA design for genome editing in solid tumours", ["guide_rna", "knockout"]),
    ("Genome-wide screen identifies PARP dependencies", ["screen"]),
    ("Lipid nanoparticle delivery of Cas9", ["cas9", "delivery"]),
    ("Gene therapy for inherited blindness", ["gene_therapy"]),
    ("Survey of chemotherapy outcomes", []),
    ("A discussion of crisprs in agriculture", []),      # word boundaries, not substrings
])
def test_tags_describe_the_title_only(title, expected):
    assert link.tags_for_title(title) == expected


def test_genes_come_from_the_title_or_its_publishing_query():
    assert link.genes_for_record({"title": "BRCA1 and TP53", "query": "x"}) == ["BRCA1", "TP53"]
    assert link.genes_for_record({"title": "no genes here", "query": "ovarian cancer BRCA2"}) == ["BRCA2"]
    assert link.genes_for_record({"title": "BRCA10 and XBRCA1 are not symbols", "query": ""}) == []
    assert link.genes_for_record({"title": "the ATM pathway", "query": ""}) == ["ATM"]


def test_tagging_skips_untagged_records_and_records_already_tagged(tmp_path):
    ledger(tmp_path, records_event())
    records = link.published_records(tmp_path)
    planned = link.plan_tags(records, {})
    by_id = {p["external_id"]: p for p in planned}
    assert by_id["SYNTH-PM-1"]["tags"] == ["base_editing", "crispr"]
    assert by_id["SYNTH-CT-1"]["tags"] == ["crispr"]                   # "CRISPR-edited T cells"
    assert by_id["SYNTH-PM-2"]["tags"] == ["gene_therapy"]              # no CRISPR, still gene therapy
    assert by_id["SYNTH-PM-1"]["genes"] == ["BRCA1"]                    # from its publishing query

    [event] = link.tag_events(planned)
    validate_public_provenance(event)
    assert event["method"] == link.CRISPR_TAG_METHOD
    ledger(tmp_path, event)
    assert link.plan_tags(records, link.already_tagged(tmp_path)) == []

    changed = [dict(records[0], title="CRISPR base editing corrected", record_sha256="a" * 64)]
    assert len(link.plan_tags(changed, link.already_tagged(tmp_path))) == 1   # a new hash is re-tagged


def test_tagging_splits_into_events_of_twenty(tmp_path):
    records = [{"source": "pubmed", "external_id": str(i), "record_sha256": f"{i:064d}",
                "title": "CRISPR editing study", "query": "breast cancer BRCA1"} for i in range(25)]
    planned = link.plan_tags(records, {})
    events = link.tag_events(planned)
    assert [e["record_count"] for e in events] == [20, 5]
    for event in events:
        validate_public_provenance(event)


@pytest.mark.parametrize("change", [
    lambda e: e["records"][0].update(tags=["cure"]),
    lambda e: e["records"][0].update(tags=[]),
    lambda e: e["records"][0].update(tags=["crispr", "base_editing"]),      # unsorted
    lambda e: e["records"][0].update(genes=["not a gene"]),
    lambda e: e["records"][0].update(title="titles are not republished here"),
    lambda e: e.update(method="hand-picked"),
    lambda e: e.update(records=e["records"] * 2, record_count=2),
])
def test_invalid_tag_events_are_refused(change):
    event = create_public_crispr_relevance_event(
        [{"source": "pubmed", "external_id": "1", "record_sha256": "b" * 64,
          "tags": ["crispr"], "genes": ["BRCA1"]}], confirm_publication=True)
    change(event)
    with pytest.raises(ValueError):
        validate_public_provenance(event)


def test_tags_need_explicit_confirmation():
    with pytest.raises(PermissionError):
        create_public_crispr_relevance_event([])


# -------------------------------------------------------------- model runs

def test_model_run_event_carries_hashes_and_never_genomic_data(tmp_path):
    result = remission_core.run(dict(DEMO))
    assert result["assessment"]["modeled_status"] == "MODELED_REFERENCE_MATCH"

    ledger(tmp_path, records_event())
    tagged = link.tag_events(link.plan_tags(link.published_records(tmp_path), {}))
    ledger(tmp_path, *tagged)
    records = link.related_records(tmp_path, ["BRCA1"])
    assert {r["external_id"] for r in records} == {"SYNTH-PM-1", "SYNTH-CT-1", "SYNTH-PM-2"}
    only_editing = link.related_records(tmp_path, ["BRCA1"], ["base_editing"])
    assert [r["external_id"] for r in only_editing] == ["SYNTH-PM-1"]
    assert link.related_records(tmp_path, ["KRAS"]) == []

    guide = link.guide_summary(BRCA1_FRAGMENT)
    event = link.model_run_event(result, records, guide_design=guide)
    validate_public_provenance(event)

    payload = json.dumps(event)
    assert result["after"]["sequence"] not in payload and DEMO["sample"] not in payload
    assert "ACGT" not in payload                        # no sequence, in any field
    # No field carries a mutation position or base change: the schema has no
    # room for one, and mutation_count is the only per-mutation number.
    assert set(event) == {
        "schema_version", "event_type", "event_id", "created_at", "classification", "model_schema",
        "run_sha256", "modeled_status", "longitudinal_trend", "clinical_status", "mutation_count",
        "stage_ledger", "sequence_event_ids", "guide_design", "record_count", "records", "disclaimer",
    }
    assert [s["kind"] for s in event["stage_ledger"]] == [b["kind"] for b in result["ledger"]["blocks"]]
    assert all(set(s) == {"index", "kind", "payload_sha256", "block_hash", "previous_hash"}
               for s in event["stage_ledger"])
    assert event["sequence_event_ids"] == []
    assert all(set(r) == {"source", "external_id", "record_sha256"} for r in event["records"])
    mutation = result["mutations"][0]
    assert mutation["reference"] + ">" + mutation["observed"] not in payload
    assert event["mutation_count"] == 1
    assert event["clinical_status"] == "NOT_CLINICALLY_CONFIRMED"
    assert event["disclaimer"] == MODEL_RUN_DISCLAIMER
    assert event["guide_design"]["candidate_count"] > 0
    assert 0 <= event["guide_design"]["top_score"] <= 1000
    assert event["run_sha256"] == link.run_digest(result)


def test_a_clinical_claim_cannot_be_invented_by_the_model():
    plain = remission_core.run(dict(DEMO))
    assert plain["assessment"]["clinical_status"]["status"] == "NOT_CLINICALLY_CONFIRMED"
    confirmed = remission_core.run(dict(DEMO, clinical_evidence={
        "remission_confirmed": True, "assessed_by": "Dr Example, Example Clinic", "assessed_on": "2026-01-05"}))
    event = link.model_run_event(confirmed, [])
    assert event["clinical_status"] == "CLINICALLY_CONFIRMED_REMISSION"    # only from supplied evidence
    assert event["disclaimer"] == MODEL_RUN_DISCLAIMER


@pytest.mark.parametrize("change", [
    lambda e: e.update(modeled_status="CURED"),
    lambda e: e.update(clinical_status="REMISSION_LIKELY"),
    lambda e: e.update(disclaimer="Validated treatment plan."),
    lambda e: e.update(run_sha256="short"),
    lambda e: e.update(recommended_edit="G>A at 7"),
    lambda e: e.update(guide_design={"method": "guesswork", "sequence_sha256": "c" * 64,
                                     "candidate_count": 1, "top_score": 900}),
    lambda e: e["guide_design"].update(guide_sequence="ACGTACGTACGTACGTACGT"),
    lambda e: e.update(mutation_count=-1),
])
def test_invalid_model_run_events_are_refused(change):
    event = create_public_model_run_event(
        run_sha256="d" * 64, modeled_status="MODELED_REFERENCE_MATCH",
        longitudinal_trend="NO_FOLLOW_UP_DATA", clinical_status="NOT_CLINICALLY_CONFIRMED",
        mutation_count=1, records=[], confirm_publication=True, stage_ledger=STAGES,
        guide_design=link.guide_summary(BRCA1_FRAGMENT))
    change(event)
    with pytest.raises(ValueError):
        validate_public_provenance(event)


def test_model_runs_need_explicit_confirmation():
    with pytest.raises(PermissionError):
        create_public_model_run_event(run_sha256="e" * 64, modeled_status="MODELED_REFERENCE_MATCH",
                                      longitudinal_trend="NO_FOLLOW_UP_DATA",
                                      clinical_status="NOT_CLINICALLY_CONFIRMED",
                                      mutation_count=0, records=[], stage_ledger=STAGES)


def test_cli_tags_then_links_a_run(tmp_path, capsys):
    ledger(tmp_path, records_event())
    outbox = tmp_path / "outbox"
    base = ["--base-dir", str(tmp_path), "--outbox", str(outbox)]
    assert link.main(["tag"] + base) == 0
    assert "3 record(s) to tag" in capsys.readouterr().out and not outbox.exists()
    assert link.main(["tag"] + base + ["--confirm-publication"]) == 0
    [queued] = list(outbox.glob("*.json"))
    tag_event = json.loads(queued.read_text(encoding="utf-8"))
    ledger(tmp_path, tag_event)

    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(remission_core.run(dict(DEMO))), encoding="utf-8")
    sequence = tmp_path / "seq.txt"
    sequence.write_text(">BRCA1 fragment\nATGGATTTATCTGCTCTTCGCGTTGAAGAAGTACAAAATGTCATTAATGCTATGCAGAAA\n",
                        encoding="utf-8")
    assert link.main(["link-run", str(result_path), "--gene", "BRCA1",
                      "--sequence-file", str(sequence)] + base + ["--confirm-publication"]) == 0
    out = capsys.readouterr().out
    assert "MODELED_REFERENCE_MATCH" in out and "NOT_CLINICALLY_CONFIRMED" in out
    assert "not a treatment recommendation" in out
    assert "pubmed:SYNTH-PM-1" in out

    queued_events = [json.loads(p.read_text(encoding="utf-8")) for p in outbox.glob("*.json")]
    [run_event] = [e for e in queued_events if e["event_type"] == "public_model_run_record"]
    validate_public_provenance(run_event)
    ledger(tmp_path, run_event)
    assert link.main(["status"] + base) == 0
    assert "3 of 3 published records tagged" in capsys.readouterr().out
    assert len(published_events(str(tmp_path), "public_model_run_record")) == 1


def test_cli_refuses_a_result_that_is_not_a_model_run(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "something-else"}), encoding="utf-8")
    assert link.main(["link-run", str(bad), "--gene", "BRCA1", "--base-dir", str(tmp_path)]) == 2


# ------------------------------------------------------- sequences on chain

def test_public_reference_and_synthetic_sequences_may_be_published():
    event = create_public_sequence_event(
        origin="public_reference", bases=BRCA1_FRAGMENT, label="BRCA1 exon fragment",
        accession="NM_007294.4", source="ncbi_nuccore", confirm_publication=True)
    validate_public_provenance(event)
    assert event["sequence"]["bases"] == BRCA1_FRAGMENT            # the sequence itself is on the chain
    assert event["sequence"]["base_count"] == len(BRCA1_FRAGMENT)
    assert event["sequence"]["accession"] == "NM_007294.4"

    synthetic = create_public_sequence_event(origin="synthetic", bases="ACGTACGTACGT",
                                             label="synthetic demo", confirm_publication=True)
    validate_public_provenance(synthetic)
    assert synthetic["sequence"]["accession"] is None


@pytest.mark.parametrize("origin", ["patient_sample", "clinical_sample", "tumour_biopsy", "", "PUBLIC_REFERENCE"])
def test_a_sequence_from_a_person_is_refused(origin):
    with pytest.raises(PermissionError, match="public_reference or synthetic"):
        create_public_sequence_event(origin=origin, bases="ACGTACGTACGT", label="case",
                                     confirm_publication=True)


def test_a_person_sequence_is_refused_even_if_the_event_is_hand_built():
    event = create_public_sequence_event(origin="synthetic", bases="ACGTACGTACGT", label="demo",
                                        confirm_publication=True)
    event["sequence"]["origin"] = "patient_sample"
    with pytest.raises(ValueError, match="must not be published"):
        validate_public_provenance(event)


@pytest.mark.parametrize("change", [
    lambda s: s.update(bases="ACGTX"),
    lambda s: s.update(bases=""),
    lambda s: s.update(base_count=3),
    lambda s: s.update(sequence_sha256="f" * 64),
    lambda s: s.update(label=""),
    lambda s: s.update(accession="not-an-accession"),
    lambda s: s.update(source="some_lab"),
    lambda s: s.update(patient="never"),
])
def test_invalid_sequence_events_are_refused(change):
    event = create_public_sequence_event(
        origin="public_reference", bases=BRCA1_FRAGMENT, label="BRCA1 fragment",
        accession="NM_007294.4", source="ncbi_nuccore", confirm_publication=True)
    change(event["sequence"])
    with pytest.raises(ValueError):
        validate_public_provenance(event)


def test_a_long_sequence_is_refused():
    with pytest.raises(ValueError, match="exceeds"):
        create_public_sequence_event(origin="synthetic", bases="ACGT" * 501, label="too long",
                                     confirm_publication=True)


def test_synthetic_run_publishes_its_sequences_and_links_them(tmp_path, capsys):
    ledger(tmp_path, records_event())
    outbox = tmp_path / "outbox"
    base = ["--base-dir", str(tmp_path), "--outbox", str(outbox)]
    assert link.main(["tag"] + base + ["--confirm-publication"]) == 0
    for queued in list(outbox.glob("*.json")):
        ledger(tmp_path, json.loads(queued.read_text(encoding="utf-8")))
        queued.unlink()

    result_path = tmp_path / "result.json"
    result = remission_core.run(dict(DEMO))
    result_path.write_text(json.dumps(result), encoding="utf-8")
    assert link.main(["link-run", str(result_path), "--gene", "BRCA1", "--publish-sequences", "synthetic"]
                     + base + ["--confirm-publication"]) == 0
    assert "sequences on chain (synthetic)" in capsys.readouterr().out

    events = [json.loads(p.read_text(encoding="utf-8")) for p in outbox.glob("*.json")]
    sequences = [e for e in events if e["event_type"] == "public_sequence_record"]
    [run] = [e for e in events if e["event_type"] == "public_model_run_record"]
    assert len(sequences) == 3                                    # reference, sample, modeled edit
    assert {s["sequence"]["bases"] for s in sequences} == {
        DEMO["reference"], DEMO["sample"], result["after"]["sequence"]}
    assert run["sequence_event_ids"] == sorted(s["event_id"] for s in sequences)
    for event in events:
        validate_public_provenance(event)


def test_public_reference_sequences_need_an_accession(tmp_path):
    ledger(tmp_path, records_event())
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(remission_core.run(dict(DEMO))), encoding="utf-8")
    assert link.main(["link-run", str(result_path), "--gene", "BRCA1", "--base-dir", str(tmp_path),
                      "--publish-sequences", "public_reference"]) == 2
