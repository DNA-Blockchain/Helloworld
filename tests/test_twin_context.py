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

"""ClinVar's attributed classifications and local-only clinical context."""

import json

import pytest

import dna_twin_viewer as twin
import twin_context as ctx
from public_variant_sources import _clinvar_classification

CLINVAR_SUMMARY = {
    "accession": "VCV000017661",
    "title": "NM_007294.4(BRCA1):c.441+1G>T",
    "obj_type": "single nucleotide variant",
    "protein_change": "",
    "genes": [{"symbol": "BRCA1", "geneid": "672"}],
    "variation_set": [{"variant_type": "single nucleotide variant",
                       "canonical_spdi": "NC_000017.11:43104120:C:A"}],
    "germline_classification": {
        "description": "Likely pathogenic",
        "review_status": "criteria provided, single submitter",
        "last_evaluated": "2021/06/03 00:00",
        "trait_set": [{"trait_name": "BRCA1-related disorder"}],
    },
}


def fake_fetcher(records):
    def fetch(gene, *, max_results=10, significance=None):
        fetch.calls.append((gene, max_results, significance))
        return records
    fetch.calls = []
    return fetch


# ------------------------------------------------------------------ ClinVar

def test_a_clinvar_summary_keeps_clinvars_own_words_and_attribution():
    record = _clinvar_classification("17661", CLINVAR_SUMMARY, "BRCA1")
    assert record["clinvar_classification"] == "Likely pathogenic"
    assert record["clinvar_review_status"] == "criteria provided, single submitter"
    assert record["clinvar_last_evaluated"] == "2021/06/03 00:00"
    assert record["conditions"] == ["BRCA1-related disorder"]
    assert record["accession"] == "VCV000017661" and record["gene_symbols"] == ["BRCA1"]
    assert record["source_url"] == "https://www.ncbi.nlm.nih.gov/clinvar/variation/17661/"
    assert "not this project" in record["asserted_by"]
    assert record["classification"] == "public"


def test_a_summary_without_a_classification_says_so():
    record = _clinvar_classification("1", {"title": "x"}, "TP53")
    assert record["clinvar_classification"] == "not provided"
    assert record["conditions"] == [] and record["gene_symbols"] == ["TP53"]


def test_clinvar_is_cached_then_read_offline(tmp_path):
    record = _clinvar_classification("17661", CLINVAR_SUMMARY, "BRCA1")
    fetch = fake_fetcher([record])
    cached = ctx.fetch_clinvar(tmp_path, "brca1", max_results=5, fetcher=fetch)
    assert fetch.calls == [("brca1", 5, None)]
    assert cached["gene"] == "BRCA1" and cached["record_count"] == 1
    assert "ClinVar" in cached["attribution"]

    reloaded = ctx.load_clinvar(tmp_path, "BRCA1")            # no network
    assert reloaded["records"] == [record]
    assert ctx.load_clinvar(tmp_path, "TP53") is None
    assert ctx.clinvar_for_genes(tmp_path, ["BRCA1", "TP53"]) == [record]


def test_a_corrupt_cache_is_ignored(tmp_path):
    path = ctx.clinvar_cache_path(tmp_path, "BRCA1")
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    assert ctx.load_clinvar(tmp_path, "BRCA1") is None
    path.write_text(json.dumps({"schema": "something-else"}), encoding="utf-8")
    assert ctx.load_clinvar(tmp_path, "BRCA1") is None


def test_clinvar_cli_needs_a_cache_or_fetch(tmp_path, capsys):
    assert ctx.main(["clinvar", "BRCA1", "--base-dir", str(tmp_path)]) == 1
    assert "Run with --fetch" in capsys.readouterr().out


# ------------------------------------------------------------------ context

def test_context_accepts_reported_annotations():
    context = ctx.validate_context(["ER+", "her2-", "G2", "III"])
    assert context["markers"] == ["ER+", "HER2-"]
    assert context["grade"] == "G2" and context["stage"] == "III"
    assert context["published"] is False
    assert "never published" in context["note"]
    assert "not which DNA bases" in context["note"]


@pytest.mark.parametrize("entry", ["cured", "ER", "stage 9", "G9", "remission", "high risk", ""])
def test_unknown_context_is_refused_rather_than_guessed(entry):
    with pytest.raises(ValueError, match="unknown clinical context"):
        ctx.validate_context([entry])


def test_too_much_context_is_refused():
    with pytest.raises(ValueError, match="at most"):
        ctx.validate_context(["ER+"] * 13)


def test_context_chooses_research_tags_not_dna_edits():
    assert ctx.research_tags_for_context(ctx.validate_context(["ER+"])) == ["expression", "hormone_signalling"]
    assert ctx.research_tags_for_context(ctx.validate_context(["HER2-"])) == ["expression"]
    assert ctx.research_tags_for_context(None) == []
    # A context has no field that could carry a base, a position or an edit:
    # its data is markers, a grade and a stage, and nothing else.
    context = ctx.validate_context(["ER+", "PR+", "G3"])
    assert set(context) == {"schema", "markers", "grade", "stage", "recorded_at", "published", "note"}
    assert set(context["markers"]) <= set(ctx.RECEPTOR_MARKERS)
    # every marker maps only to research tags, never to anything sequence-like
    for tags in ctx.RECEPTOR_MARKERS.values():
        from research_provenance import CRISPR_TAGS
        assert set(tags) <= CRISPR_TAGS


def test_context_is_saved_and_reloaded_locally(tmp_path):
    context = ctx.validate_context(["ER+", "G1"])
    path = ctx.save_context(tmp_path, "case A", context)
    assert path.parent.name == "context"
    reloaded = ctx.load_context(tmp_path, "case A")
    assert reloaded["markers"] == ["ER+"] and reloaded["label"] == "case A"
    assert ctx.load_context(tmp_path, "other case") is None


def test_context_labels_cannot_escape_the_context_folder(tmp_path):
    path = ctx.context_path(tmp_path, "../../etc/passwd")
    assert path.parent == tmp_path / "context"
    assert "/" not in path.name and "\\" not in path.name


def test_context_has_no_publish_path():
    import inspect
    source = inspect.getsource(ctx)
    for forbidden in ("ResearchProvenanceQueue", "create_public_", "confirm_publication", "outbox"):
        assert forbidden not in source, forbidden


def test_context_cli_records_and_reports(tmp_path, capsys):
    assert ctx.main(["context", "--set", "ER+", "--set", "G2", "--label", "case A",
                     "--base-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "ER+" in out and "hormone_signalling" in out and "never published" in out
    assert ctx.main(["context", "--set", "cured", "--base-dir", str(tmp_path)]) == 2
    assert ctx.main(["context", "--label", "missing", "--base-dir", str(tmp_path)]) == 1


# --------------------------------------------------------- shown in the twin

BRCA1_FRAGMENT = (
    "ATGGATTTATCTGCTCTTCGCGTTGAAGAAGTACAAAATGTCATTAATGCTATGCAGAAA"
    "ATCTTAGAGTGTCCCATCTGTCTGGAGTTGATCAAGGAACCTGTCTCCACAAAGTGTGAC"
)


def test_the_twin_shows_clinvar_and_context_without_publishing_them(tmp_path):
    import remission_core

    result = remission_core.run({"reference": BRCA1_FRAGMENT,
                                 "sample": BRCA1_FRAGMENT[:40] + "A" + BRCA1_FRAGMENT[41:]})
    data = twin.twin_from_run(result)
    record = _clinvar_classification("17661", CLINVAR_SUMMARY, "BRCA1")
    context = ctx.validate_context(["ER+"])
    html = twin.build_page(data, [], [], 1, [record], context)
    embedded = json.loads(__import__("re").search(r"const DATA = (\{.*?\});\nconst T", html,
                                                  __import__("re").S).group(1))
    assert embedded["clinvar"][0]["clinvar_classification"] == "Likely pathogenic"
    assert embedded["context"]["markers"] == ["ER+"]
    assert "not this project" in html
    assert "never published" in html


def test_context_sorts_matching_research_first_without_dropping_any(tmp_path, monkeypatch):
    records = [
        {"source": "pubmed", "external_id": "1", "record_sha256": "a" * 64,
         "title": "CRISPR editing", "tags": ["crispr"]},
        {"source": "pubmed", "external_id": "2", "record_sha256": "b" * 64,
         "title": "Estrogen receptor signalling", "tags": ["hormone_signalling"]},
    ]
    import research_crispr_link
    monkeypatch.setattr(research_crispr_link, "related_records", lambda *a, **k: records)
    shown = twin.linked_research(tmp_path, ["BRCA1"], ["hormone_signalling"])
    assert [r["external_id"] for r in shown] == ["2", "1"]      # context match first
    assert [r["matches_context"] for r in shown] == [True, False]
    assert len(twin.linked_research(tmp_path, ["BRCA1"], [])) == 2   # none dropped
