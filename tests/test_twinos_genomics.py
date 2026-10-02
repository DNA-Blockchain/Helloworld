"""TwinOS genomics: the public dataset catalogue and its access tiers, variant reading and comparison,
candidate Cas9 guide design, and the research_search task. Everything here is computation on public data;
the tests also pin the disclaimers, so the tool can't quietly become a treatment claim."""
import json

import pytest

from tests.test_twinos import ask, make_paths
from twinos import genomics as g
from twinos.__main__ import main
from twinos.node import AgentNode

VCF_HEADER = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"


def vcf(path, rows):
    path.write_text(VCF_HEADER + "".join(
        f"{c}\t{p}\t.\t{r}\t{a}\t.\tPASS\tGENE={gene};AF={f}\n" for c, p, r, a, gene, f in rows))
    return path


# -- the catalogue -------------------------------------------------------------------------------------
def test_the_catalogue_is_valid_and_its_tiers_decide_what_the_twin_may_download():
    entries = g.catalogue()
    assert len(entries) >= 10
    for e in entries:
        assert e["access"] in g.TIERS and isinstance(e["personal_data"], bool) and e["license"] and e["url"]
        if e["personal_data"]:
            assert e["redistribute"] is False, f"{e['name']}: personal data must never be redistributable"
    # Known tiers from the research: DepMap open, GENIE registered and non-redistributable, TRACERx controlled.
    assert g.dataset("depmap-crispr-gene-effect")["access"] == "open"
    assert g.dataset("aacr-genie")["redistribute"] is False
    assert g.dataset("tracerx-421")["access"] == "controlled"
    with pytest.raises(KeyError, match="no dataset"):
        g.dataset("not-a-dataset")


def test_controlled_and_registered_datasets_are_never_downloaded_by_the_twin():
    allowed, why = g.fetch_plan(g.dataset("tracerx-421"))
    assert not allowed and "data access committee" in why
    allowed, why = g.fetch_plan(g.dataset("aacr-genie"))
    assert not allowed and "your own account" in why
    allowed, why = g.fetch_plan(g.dataset("depmap-crispr-gene-effect"))
    assert not allowed and "no direct file URL" in why          # open, but nothing to download yet
    with_file = {**g.dataset("depmap-crispr-gene-effect"), "files": ["https://example.org/x.csv"]}
    allowed, why = g.fetch_plan(with_file)
    assert allowed and "open" in why


def test_recording_a_dataset_keeps_the_fingerprint_and_marks_what_may_be_published(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("gene,score\nTP53,-1.2\n")
    open_record = g.record_entry(g.dataset("depmap-crispr-gene-effect"), path, "a" * 64)
    assert open_record["publishable"] is True and open_record["sha256"] == "a" * 64
    assert open_record["bytes"] == path.stat().st_size and "score" not in json.dumps(open_record)
    personal = g.record_entry(g.dataset("aacr-genie"), path, "b" * 64)
    assert personal["publishable"] is False and personal["personal_data"] is True


# -- variants ------------------------------------------------------------------------------------------
def test_variants_are_read_from_vcf_and_from_a_maf_table(tmp_path):
    from_vcf = g.read_variants(vcf(tmp_path / "a.vcf", [("17", 7676154, "G", "A", "TP53", 0.62)]))
    assert len(from_vcf) == 1 and from_vcf[0].gene == "TP53" and from_vcf[0].frequency == 0.62
    assert str(from_vcf[0]) == "TP53 17:7676154 G>A"
    maf = tmp_path / "b.maf"
    maf.write_text("Hugo_Symbol\tChromosome\tStart_Position\tReference_Allele\tTumor_Seq_Allele2\tVAF\n"
                   "KRAS\tchr12\t25245350\tC\tT\t41.5\n")
    from_maf = g.read_variants(maf)
    assert from_maf[0].chrom == "12" and from_maf[0].gene == "KRAS" and from_maf[0].frequency == 0.415
    multi = g.read_variants(vcf(tmp_path / "c.vcf", [("1", 100, "A", "G,T", "X", 0.5)]))
    assert {v.alt for v in multi} == {"G", "T"}
    empty = tmp_path / "empty.vcf"
    empty.write_text("")
    assert g.read_variants(empty) == []
    bad = tmp_path / "bad.tsv"
    bad.write_text("gene\tvalue\nTP53\t1\n")
    with pytest.raises(ValueError, match="column"):
        g.read_variants(bad)


def test_comparison_reports_gained_lost_and_shifted(tmp_path):
    cancer = g.read_variants(vcf(tmp_path / "cancer.vcf", [
        ("17", 7676154, "G", "A", "TP53", 0.62), ("7", 140753336, "A", "T", "BRAF", 0.41),
        ("3", 179234297, "A", "G", "PIK3CA", 0.35)]))
    normal = g.read_variants(vcf(tmp_path / "normal.vcf", [
        ("17", 7676154, "G", "A", "TP53", 0.05), ("3", 179234297, "A", "G", "PIK3CA", 0.33),
        ("9", 5073770, "G", "T", "JAK2", 0.49)]))
    result = g.compare(cancer, normal, shift=0.2)
    assert [v.gene for v in result.gained] == ["BRAF"]
    assert [v.gene for v in result.lost] == ["JAK2"]
    assert {v.gene for v in result.shared} == {"TP53", "PIK3CA"}
    assert [(a.frequency, b.frequency) for a, b in result.shifted] == [(0.05, 0.62)]   # PIK3CA moved only 0.02
    assert result.summary(0.2) == {"gained": 1, "lost": 1, "shared": 2, "frequency_shifts": 1,
                                   "shift_threshold": 0.2}
    assert g.compare(cancer, []).lost == [] and len(g.compare(cancer, []).gained) == 3
    assert g.mutational_burden(cancer, 1.0) == 3.0 and g.mutational_burden(cancer, 0) is None


# -- candidate guides ----------------------------------------------------------------------------------
def test_guides_are_found_on_both_strands_and_map_back_to_the_sequence():
    # One known NGG on each strand: "AGG" after a plus protospacer, and "CCT" before a minus one.
    sequence = ("AT" * 20 + "ACGTACGTACGTACGTACGT" + "AGG" + "T" * 37 + "CCT"
                + "GGACTTGACCTTGACCTTGA" + "GC" * 20)
    guides = g.candidate_guides(sequence, target_offset=57, window=60, limit=50)
    assert {x.strand for x in guides} == {"+", "-"}
    for x in guides:
        shown = sequence[x.start:x.start + g.GUIDE_LENGTH]
        assert x.protospacer == (shown if x.strand == "+" else g.reverse_complement(shown))
        assert x.pam.endswith("GG") and 0.0 <= x.gc <= 1.0 and x.hypothesis == g.HYPOTHESIS
    nearest = guides[0]
    assert nearest.strand == "+" and nearest.start == 40 and nearest.distance_to_target == 0
    assert [x.distance_to_target for x in guides] == sorted(x.distance_to_target for x in guides)


def test_guides_respect_the_window_and_reject_bad_input():
    sequence = "ACGTACGTACGTACGTACGT" + "AGG" + "T" * 100
    assert g.candidate_guides(sequence, 17, window=5)                      # the cut is at 17
    assert g.candidate_guides(sequence, 90, window=5) == []                # nothing near the far end
    assert g.candidate_guides("T" * 60, 30) == []                          # no NGG at all
    with pytest.raises(ValueError, match="A, C, G and T"):
        g.candidate_guides("ACGTNNNN", 2)
    with pytest.raises(ValueError, match="inside the sequence"):
        g.candidate_guides("ACGT" * 20, 500)
    assert len(g.candidate_guides("CCACGTACGTACGTACGTACGTAGG" * 8, 100, window=200, limit=3)) == 3


def test_every_guide_and_the_notes_say_it_is_untested():
    for text in (g.HYPOTHESIS, g.edit_outcome_note()):
        assert "not a treatment" in text or "says nothing about whether editing would help" in text
    assert "delivery into tumour cells is unsolved" in g.edit_outcome_note()


# -- the research_search task --------------------------------------------------------------------------
def test_research_search_is_offered_and_runs_without_approval(tmp_path, monkeypatch):
    paths = make_paths(tmp_path)
    twin = AgentNode(home=tmp_path / "twin", paths=paths)
    peer = AgentNode(home=tmp_path / "peer", paths=paths, name="Peer", agent_type="generic_agent")
    twin.trust.pin(peer.identity.agent_id, peer.identity.public_key)
    assert "research_search" in twin.capabilities()["task_types"]
    assert "research_search" in twin.capabilities()["automatic"]          # public research only

    class FakeKnowledge:
        def search(self, query):
            return [{"title": f"Report section for {query}", "url": "docs/research/x.md", "similarity": 0.84}]

    monkeypatch.setattr("rabbitsoft.assistant.Session.knowledge", property(lambda self: FakeKnowledge()))
    reply = ask(peer, twin, "TASK_REQUEST", {"task_type": "research_search", "description": "CRISPR remission",
                                             "parameters": {"query": "CRISPR CAR-T remission", "limit": 3}})
    result = reply["payload"]["result"]
    assert reply["payload"]["status"] == "completed" and result["matches"] == 1
    assert result["sections"][0]["similarity"] == 0.84 and "not medical advice" in result["note"]
    empty = twin.run_local("research_search", "", {"query": "   "})
    assert empty.status == "failed" and "search for" in empty.result["error"]


# -- the commands --------------------------------------------------------------------------------------
def test_the_commands_print_the_tiers_the_differences_and_the_disclaimers(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("twinos.node.Paths", lambda: make_paths(tmp_path))
    home = str(tmp_path / "cli")
    assert main(["--home", home, "datasets"]) == 0
    listed = capsys.readouterr().out
    assert "depmap-crispr-gene-effect" in listed and "tracerx-421" not in listed    # controlled is hidden
    assert main(["--home", home, "datasets", "--all"]) == 0
    assert "tracerx-421" in capsys.readouterr().out

    assert main(["--home", home, "fetch", "tracerx-421"]) == 1
    assert "data access committee" in capsys.readouterr().out

    cancer = vcf(tmp_path / "c.vcf", [("17", 7676154, "G", "A", "TP53", 0.62), ("7", 1, "A", "T", "BRAF", 0.4)])
    normal = vcf(tmp_path / "n.vcf", [("17", 7676154, "G", "A", "TP53", 0.05)])
    assert main(["--home", home, "compare", str(cancer), str(normal), "--megabases", "1.0"]) == 0
    out = capsys.readouterr().out
    assert "BRAF" in out and "0.05 -> 0.62" in out and "mutations per megabase: 2.0" in out
    assert "not a diagnosis" in out and "not medical advice" in out

    sequence = tmp_path / "s.fa"
    sequence.write_text(">region\n" + "ACGTACGTACGTACGTACGT" + "AGG" + "T" * 40 + "\n")
    assert main(["--home", home, "guides", str(sequence), "--at", "17"]) == 0
    out = capsys.readouterr().out
    assert "ACGTACGTACGTACGTACGT AGG" in out and g.HYPOTHESIS in out
    sequence.write_text(">region\n" + "T" * 80 + "\n")
    assert main(["--home", home, "guides", str(sequence), "--at", "40"]) == 0
    assert "No SpCas9 (NGG) site" in capsys.readouterr().out
