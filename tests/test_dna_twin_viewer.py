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

"""The DNA digital twin page: built from a local run or rebuilt from the chain."""

import json
import re

import pytest

import dna_twin_viewer as twin
import remission_core
import research_crispr_link as link
from research_ledger import ResearchLedger

BRCA1_FRAGMENT = (
    "ATGGATTTATCTGCTCTTCGCGTTGAAGAAGTACAAAATGTCATTAATGCTATGCAGAAA"
    "ATCTTAGAGTGTCCCATCTGTCTGGAGTTGATCAAGGAACCTGTCTCCACAAAGTGTGAC"
)
VARIANT = BRCA1_FRAGMENT[:40] + "A" + BRCA1_FRAGMENT[41:]


def run_result(reference=BRCA1_FRAGMENT, sample=VARIANT, **extra):
    return remission_core.run({"reference": reference, "sample": sample,
                               "case_label": "synthetic BRCA1 variant", **extra})


def page_data(html):
    match = re.search(r"const DATA = (\{.*?\});\nconst T", html, re.S)
    return json.loads(match.group(1))


def test_twin_reads_the_sequences_and_differences_from_a_local_run():
    data = twin.twin_from_run(run_result())
    assert data["reference"] == BRCA1_FRAGMENT and data["sample"] == VARIANT
    assert data["edited"] == BRCA1_FRAGMENT                  # the model's substitution restores it
    assert [(m["position"], m["reference"], m["observed"]) for m in data["mutations"]] == [(41, "T", "A")]
    assert data["modeled_status"] == "MODELED_REFERENCE_MATCH"
    assert data["clinical_status"] == "NOT_CLINICALLY_CONFIRMED"
    assert data["verification"]["different_positions"] == 0
    assert [s["kind"] for s in data["stage_ledger"]][:2] == ["REFERENCE", "CANCER_SAMPLE"]
    assert data["ledger_verified"] is True


def test_binary_matches_the_projects_own_two_bit_code():
    assert twin.binary_of("ACGT") == ["00", "01", "10", "11"]
    data = twin.twin_from_run(run_result())
    assert twin.binary_of(data["sample"])[40] == "00"        # A at the varied position
    assert twin.binary_of(data["reference"])[40] == "11"      # T in the reference


def test_differences_are_positions_where_the_sample_disagrees():
    assert twin.differences("ACGT", "ACGT") == []
    [one] = twin.differences("ACGT", "ACAT")
    assert (one["position"], one["reference"], one["observed"]) == (3, "G", "A")
    assert (one["reference_bits"], one["observed_bits"]) == ("10", "00")


def test_a_run_without_its_sequences_is_refused():
    result = run_result()
    result["records"] = {}
    result["before"] = result["after"] = {}
    with pytest.raises(ValueError, match="reference, sample and edited"):
        twin.twin_from_run(result)
    with pytest.raises(ValueError, match="remission-model.v1"):
        twin.twin_from_run({"schema": "other"})


def test_guides_are_only_offered_near_a_difference():
    data = twin.twin_from_run(run_result())
    guides = twin.guides_near_mutations(BRCA1_FRAGMENT, data["mutations"], window=30)
    assert guides and all(g["distance"] <= 30 or g["position"] + 1 <= 41 for g in guides)
    assert all(0 <= g["score"] <= 1 for g in guides)
    assert twin.guides_near_mutations(BRCA1_FRAGMENT, []) == []
    far = twin.guides_near_mutations(BRCA1_FRAGMENT, [{"position": 1}], window=1)
    assert all(g["distance"] <= 1 or g["position"] + 1 <= 1 for g in far)


def test_page_is_self_contained_and_carries_the_model_only_note(tmp_path):
    data = twin.twin_from_run(run_result())
    html = twin.build_page(data, [], twin.guides_near_mutations(BRCA1_FRAGMENT, data["mutations"]))
    assert "__TWIN_DATA__" not in html
    assert "<script src" not in html and "http://" not in html and "https://" not in html
    assert twin.MODEL_NOTE in json.dumps(page_data(html))
    assert "not clinical remission" in html
    embedded = page_data(html)
    assert embedded["twin"]["sample"] == VARIANT
    assert len(embedded["sample_bits"]) == len(VARIANT)


def test_cli_writes_a_page_for_a_local_run(tmp_path, capsys):
    result_path = tmp_path / "run.json"
    result_path.write_text(json.dumps(run_result()), encoding="utf-8")
    out = tmp_path / "twin.html"
    assert twin.main([str(result_path), "--output", str(out), "--base-dir", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "1 difference(s)" in printed and "NOT_CLINICALLY_CONFIRMED" in printed
    assert "not clinical remission" in printed
    data = page_data(out.read_text(encoding="utf-8"))
    assert data["twin"]["case_label"] == "synthetic BRCA1 variant"


def test_cli_needs_exactly_one_source(tmp_path):
    with pytest.raises(SystemExit):
        twin.main([])
    with pytest.raises(SystemExit):
        twin.main(["run.json", "--from-chain", "a" * 32])


def test_cli_reports_a_bad_run_file(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "nope"}), encoding="utf-8")
    assert twin.main([str(bad), "--output", str(tmp_path / "t.html")]) == 2
    assert "Could not build the twin" in capsys.readouterr().out


# ----------------------------------------------------- rebuilt from the chain

def publish_run(tmp_path, origin="synthetic"):
    """A run whose sequences and provenance are on a test chain."""
    (tmp_path / "node-0").mkdir(exist_ok=True)
    book = ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json"))
    result = run_result()
    sequences = link.sequence_events(result, origin=origin, label="BRCA1 synthetic case",
                                     accession="NM_007294.4" if origin == "public_reference" else None,
                                     source="ncbi_nuccore" if origin == "public_reference" else None)
    run_event = link.model_run_event(result, [], sequence_event_ids=[s["event_id"] for s in sequences])
    for event in [*sequences, run_event]:
        index = len(book) + 1
        assert book.add_block({"origin": 0, "index": index, "hash_hex": f"{index:02x}",
                               "research_provenance": event})
    return result, run_event


def test_twin_is_rebuilt_from_the_chain_alone(tmp_path):
    result, run_event = publish_run(tmp_path)
    rebuilt = twin.twin_from_chain(tmp_path, run_event["event_id"])
    local = twin.twin_from_run(result)
    assert rebuilt["reference"] == local["reference"] and rebuilt["sample"] == local["sample"]
    assert rebuilt["edited"] == local["edited"]
    # the differences are recomputed from the published sequences, not copied
    assert [(m["position"], m["reference"], m["observed"]) for m in rebuilt["mutations"]] == \
           [(m["position"], m["reference"], m["observed"]) for m in local["mutations"]]
    assert [e["to"] for e in rebuilt["modeled_edit"]] == [e["to"] for e in local["modeled_edit"]]
    assert rebuilt["modeled_status"] == local["modeled_status"]
    assert rebuilt["sequence_origin"] == "synthetic"
    assert rebuilt["run_sha256"] == link.run_digest(result)
    assert rebuilt["source"].startswith("chain:")


def test_a_public_reference_run_rebuilds_too(tmp_path):
    _, run_event = publish_run(tmp_path, origin="public_reference")
    rebuilt = twin.twin_from_chain(tmp_path, run_event["event_id"])
    assert rebuilt["sequence_origin"] == "public_reference"
    assert rebuilt["sample"] == VARIANT


def test_a_hash_only_run_cannot_be_rebuilt_from_the_chain(tmp_path):
    (tmp_path / "node-0").mkdir()
    book = ResearchLedger(str(tmp_path / "node-0" / "research_ledger_node-0.json"))
    event = link.model_run_event(run_result(), [])          # no sequences published
    assert book.add_block({"origin": 0, "index": 1, "hash_hex": "01", "research_provenance": event})
    with pytest.raises(ValueError, match="not on the chain"):
        twin.twin_from_chain(tmp_path, event["event_id"])
    with pytest.raises(ValueError, match="no published model run"):
        twin.twin_from_chain(tmp_path, "b" * 32)


def test_cli_builds_from_the_chain(tmp_path, capsys):
    _, run_event = publish_run(tmp_path)
    out = tmp_path / "twin.html"
    assert twin.main(["--from-chain", run_event["event_id"], "--base-dir", str(tmp_path),
                      "--output", str(out)]) == 0
    assert "chain: run event" in capsys.readouterr().out
    data = page_data(out.read_text(encoding="utf-8"))
    assert data["twin"]["sample"] == VARIANT


# ------------------------------------------------------- the double helix

def test_the_second_strand_is_a_real_complement_and_a_bitwise_not():
    pair = twin.strand_pair("ACGTACGT")
    assert pair["complement"] == "TGCATGCA"
    assert pair["pairs_watson_crick"] and pair["complement_is_bitwise_not"]
    # A=00/T=11 and C=01/G=10, so complementing flips both bits of each code
    assert pair["forward_bits"][:4] == ["00", "01", "10", "11"]
    assert pair["complement_bits"][:4] == ["11", "10", "01", "00"]
    for forward, complement in zip(pair["forward_bits"], pair["complement_bits"]):
        assert complement == "".join("1" if b == "0" else "0" for b in forward)


def test_every_strand_in_the_page_verifies_as_double(tmp_path):
    data = twin.twin_from_run(run_result())
    html = twin.build_page(data, [], [])
    embedded = page_data(html)
    assert embedded["helix_verified"] is True
    for part in ("reference", "sample", "edited"):
        pair = embedded["strands"][part]
        assert pair["forward"] == data[part]
        assert len(pair["complement"]) == len(pair["forward"])
        assert pair["pairs_watson_crick"] and pair["complement_is_bitwise_not"]
    # the page draws the complement it was given, rather than deriving its own
    assert "DATA.strands[view].complement" in html


def test_the_complement_comes_from_the_projects_codec():
    from dna_binary_codec import complement_strand

    for sequence in ("A", "ACGT", VARIANT):
        assert twin.strand_pair(sequence)["complement"] == complement_strand(sequence)


# --------------------------------------------- binary dataset for the OS

def test_packing_is_four_bases_per_byte_and_round_trips():
    assert twin.pack_bases("AAAA") == b"\x00"
    assert twin.pack_bases("TTTT") == b"\xff"
    for sequence in ("ACGT", VARIANT, BRCA1_FRAGMENT):
        packed = twin.pack_bases(sequence)
        assert len(packed) == (len(sequence) + 3) // 4
        assert twin.unpack_bases(packed, len(sequence)) == sequence


def test_padding_does_not_change_the_recovered_sequence():
    for sequence in ("A", "AC", "ACG", "ACGTA"):
        packed = twin.pack_bases(sequence)
        assert twin.unpack_bases(packed, len(sequence)) == sequence


def test_dataset_carries_each_strand_with_hashes_and_an_os_task_input(tmp_path):
    data = twin.twin_from_run(run_result())
    written = twin.write_dataset(tmp_path, data)
    assert set(written) == {"REFDNA.BIN", "SAMPDNA.BIN", "EDITDNA.BIN", "TWINMETA.JSON", "SAMPLE.JSON"}

    manifest = json.loads((tmp_path / "TWINMETA.JSON").read_text(encoding="utf-8"))
    assert manifest["schema"] == twin.DATASET_SCHEMA
    assert manifest["encoding"]["map"] == {"A": "00", "C": "01", "G": "10", "T": "11"}
    assert manifest["difference_positions"] == [41]
    assert manifest["modeled_status"] == "MODELED_REFERENCE_MATCH"
    assert twin.MODEL_NOTE in manifest["note"]

    import hashlib
    for part, strand in manifest["strands"].items():
        packed = (tmp_path / strand["file"]).read_bytes()
        assert len(packed) == strand["packed_bytes"] == (strand["base_count"] + 3) // 4
        assert hashlib.sha256(packed).hexdigest() == strand["packed_sha256"]
        recovered = twin.unpack_bases(packed, strand["base_count"])
        assert recovered == data[part]
        assert hashlib.sha256(recovered.encode("utf-8")).hexdigest() == strand["bases_sha256"]


def test_the_os_task_input_reproduces_the_same_model_result(tmp_path):
    result = run_result()
    twin.write_dataset(tmp_path, twin.twin_from_run(result))
    task_input = json.loads((tmp_path / "SAMPLE.JSON").read_text(encoding="utf-8"))
    assert sorted(task_input) == ["case_label", "reference", "sample"]
    rerun = remission_core.run(task_input)
    assert rerun["assessment"]["modeled_status"] == result["assessment"]["modeled_status"]
    assert [m["position"] for m in rerun["mutations"]] == [m["position"] for m in result["mutations"]]
    assert rerun["after"]["sequence"] == result["after"]["sequence"]


def test_dataset_file_names_fit_the_os_filesystem_rules():
    import re
    nosfs_name = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,14}$")
    for name in twin.dataset_files(twin.twin_from_run(run_result())):
        assert nosfs_name.match(name), name


def test_cli_exports_the_dataset(tmp_path, capsys):
    result_path = tmp_path / "run.json"
    result_path.write_text(json.dumps(run_result()), encoding="utf-8")
    assert twin.main([str(result_path), "--output", str(tmp_path / "t.html"),
                      "--base-dir", str(tmp_path), "--export-dataset", str(tmp_path / "set")]) == 0
    assert "Binary dataset written" in capsys.readouterr().out
    assert (tmp_path / "set" / "SAMPDNA.BIN").exists()


# ------------------------------------------------ cancer-free baseline twin

def test_baseline_twin_has_no_differences_and_is_the_reference():
    base = twin.twin_from_baseline(BRCA1_FRAGMENT, "BRCA1 cancer-free baseline")
    assert base["is_baseline"] is True
    assert base["reference"] == base["sample"] == base["edited"] == BRCA1_FRAGMENT
    assert base["mutations"] == [] and base["modeled_edit"] == []
    assert base["verification"]["different_positions"] == 0
    assert base["clinical_status"] == "NOT_CLINICALLY_CONFIRMED"
    assert "every modeled edit" in base["note"].lower() or "Every modeled edit" in base["note"]


def test_baseline_accepts_whitespace_and_refuses_non_dna():
    assert twin.twin_from_baseline("ACGT ACGT\n")["reference"] == "ACGTACGT"
    for bad in ("", "ACGU", "hello", "ACGTN"):
        with pytest.raises(ValueError, match="ACGT"):
            twin.twin_from_baseline(bad)


def test_the_baseline_is_what_the_modeled_edit_restores():
    base = twin.twin_from_baseline(BRCA1_FRAGMENT)
    run = twin.twin_from_run(run_result())
    assert run["reference"] == base["reference"]              # same baseline
    assert run["edited"] == base["sample"]                    # the edit restores it exactly
    for edit, difference in zip(run["modeled_edit"], run["mutations"]):
        assert edit["to"] == base["reference"][difference["position"] - 1]


def test_baseline_dataset_and_page(tmp_path, capsys):
    reference = tmp_path / "ref.txt"
    reference.write_text(">BRCA1 fragment\n" + BRCA1_FRAGMENT + "\n", encoding="utf-8")
    out, dataset = tmp_path / "base.html", tmp_path / "set"
    assert twin.main(["--baseline", str(reference), "--label", "BRCA1 baseline", "--output", str(out),
                      "--base-dir", str(tmp_path), "--export-dataset", str(dataset)]) == 0
    assert "0 difference(s)" in capsys.readouterr().out
    manifest = json.loads((dataset / "TWINMETA.JSON").read_text(encoding="utf-8"))
    assert manifest["is_baseline"] is True and manifest["difference_positions"] == []
    assert manifest["case_label"] == "BRCA1 baseline"
    data = page_data(out.read_text(encoding="utf-8"))
    assert data["helix_verified"] is True                     # a baseline is still a double helix
    assert data["twin"]["mutations"] == []


def test_cli_still_needs_exactly_one_source(tmp_path):
    reference = tmp_path / "ref.txt"
    reference.write_text(BRCA1_FRAGMENT, encoding="utf-8")
    with pytest.raises(SystemExit):
        twin.main(["run.json", "--baseline", str(reference)])


# --------------------------------------- the bit template under everything

def test_the_edit_is_an_xor_mask_that_restores_the_baseline():
    plan = twin.bit_edit_plan("ACGTACGTACGT", "ACGTACATACGT")
    assert plan["bases_changed"] == 1 and plan["bits_flipped"] == 1
    assert plan["total_bits"] == 24                       # 2 bits per base
    assert plan["verified"] is True
    [step] = plan["steps"]
    assert (step["position"], step["from_base"], step["to_base"]) == (7, "A", "G")
    assert (step["sample_bits"], step["xor_mask"], step["baseline_bits"]) == ("00", "10", "10")
    assert twin.apply_bit_mask("ACGTACATACGT", plan["mask"]) == "ACGTACGTACGT"


@pytest.mark.parametrize("have, want, bits", [
    ("A", "C", 1), ("A", "G", 1), ("A", "T", 2), ("C", "G", 2), ("C", "T", 1), ("G", "T", 1),
    ("A", "A", 0),
])
def test_how_many_bits_each_substitution_flips(have, want, bits):
    plan = twin.bit_edit_plan(want, have)
    assert plan["bits_flipped"] == bits
    assert plan["verified"] is True
    assert twin.apply_bit_mask(have, plan["mask"]) == want


def test_the_mask_is_verified_not_assumed():
    plan = twin.bit_edit_plan(BRCA1_FRAGMENT, VARIANT)
    assert plan["verified"] is True
    assert twin.apply_bit_mask(VARIANT, plan["mask"]) == BRCA1_FRAGMENT
    # an all-zero mask leaves the sample alone, so it cannot reach the baseline
    assert twin.apply_bit_mask(VARIANT, "0" * plan["total_bits"]) == VARIANT
    with pytest.raises(ValueError, match="one character per bit"):
        twin.apply_bit_mask(VARIANT, "10")


def test_an_identical_sample_needs_no_flips():
    plan = twin.bit_edit_plan(BRCA1_FRAGMENT, BRCA1_FRAGMENT)
    assert plan["steps"] == [] and plan["bits_flipped"] == 0 and plan["verified"] is True
    assert set(plan["mask"]) == {"0"}


def test_the_page_carries_the_verified_bit_plan():
    data = twin.twin_from_run(run_result())
    embedded = page_data(twin.build_page(data, [], []))
    plan = embedded["bit_plan"]
    assert plan["verified"] is True and plan["bases_changed"] == 1
    assert [s["position"] for s in plan["steps"]] == [41]


# ------------------------------------------------- DNA code to protein code

def test_protein_consequence_is_a_genetic_code_lookup():
    # GTC (Val) -> GAC (Asp) at position 41 of the fragment, frame 1
    [entry] = twin.protein_consequences(BRCA1_FRAGMENT, VARIANT, frame=1)
    assert entry["codon_number"] == 14 and entry["codon_start"] == 40
    assert (entry["reference_codon"], entry["sample_codon"]) == ("GTC", "GAC")
    assert (entry["reference_amino_acid"], entry["sample_amino_acid"]) == ("Val", "Asp")
    assert entry["consequence"] == "missense"
    assert entry["restores"] == "Asp → Val"


@pytest.mark.parametrize("reference, sample, consequence", [
    ("AAATTT", "AAGTTT", "synonymous"),      # AAA and AAG are both Lys
    ("AAATTT", "TAATTT", "nonsense"),        # AAA (Lys) -> TAA (stop)
    ("TAATTT", "AAATTT", "stop_lost"),
    ("ATGTTT", "ACGTTT", "start_lost"),
    ("AAATTT", "ACATTT", "missense"),        # Lys -> Thr
])
def test_consequence_classes(reference, sample, consequence):
    [entry] = twin.protein_consequences(reference, sample, frame=1)
    assert entry["consequence"] == consequence


def test_the_genetic_code_table_is_the_standard_one():
    assert len(twin.GENETIC_CODE) == 64
    assert twin.GENETIC_CODE["ATG"] == "Met"
    assert [c for c, aa in twin.GENETIC_CODE.items() if aa == "*"] == ["TAA", "TAG", "TGA"]
    assert twin.GENETIC_CODE["TTT"] == "Phe" and twin.GENETIC_CODE["GGG"] == "Gly"


def test_reading_frame_changes_the_codon_and_must_be_valid():
    shifted = twin.protein_consequences(BRCA1_FRAGMENT, VARIANT, frame=2)
    assert shifted and shifted[0]["codon_start"] != 40
    with pytest.raises(ValueError, match="reading frame"):
        twin.protein_consequences(BRCA1_FRAGMENT, VARIANT, frame=4)


def test_protein_note_states_what_it_does_not_claim():
    assert "reading frame" in twin.PROTEIN_NOTE
    assert "not whether the change causes disease" in twin.PROTEIN_NOTE
