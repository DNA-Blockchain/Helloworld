import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import local_ai_tuning as lt


class FakeModel:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def generate(self, prompt, num_predict=120):
        self.prompts.append(prompt)
        return self.reply


def test_the_worked_explain_example_passes_its_own_checks():
    result = lt.score_explain(lt.EXPLAIN_EXAMPLE_FACTS, FakeModel(lt.EXPLAIN_EXAMPLE_ANSWER), lt.se.PROMPT)
    assert result["ok"], result


@pytest.mark.parametrize("title, sentence", lt.SUMMARY_EXAMPLES)
def test_the_worked_summary_examples_pass_their_own_checks(title, sentence):
    result = lt.score_summary(title, FakeModel(sentence), lt.rs.PROMPT)
    assert result["ok"], result


def test_example_prompts_still_carry_the_case_and_the_rules():
    model = FakeModel(lt.EXPLAIN_EXAMPLE_ANSWER)
    lt.score_explain(["Fact one."], model, lt.EXPLAIN_WITH_EXAMPLE)
    assert model.prompts[0].endswith("Facts:\n- Fact one.")
    assert "Example explanation:" in model.prompts[0] and "never mention patients" in model.prompts[0]
    assert lt.SUMMARY_WITH_EXAMPLES.format(title="T").endswith("Title: T")


@pytest.mark.parametrize("reply, flag", [
    ("Here is the explanation: it differs. At 1 position. That is all.", "introduction line"),
    ("Researchers designed a synthetic DNA sequence. It differs at 1 position. Nothing else.", "invented framing"),
    ("One sentence only.", "1 sentences"),
])
def test_explain_flags(reply, flag):
    result = lt.score_explain(["The sample differs from its reference at 1 position(s)."], FakeModel(reply),
                              lt.se.PROMPT)
    assert not result["ok"] and any(f.startswith(flag) for f in result["flags"]), result


def test_the_prompts_own_background_is_not_invented_framing():
    reply = "Lab researchers design siRNAs to switch off a gene's message. It differs at 1 position. That is all."
    assert lt.score_explain(["It differs at 1 position(s)."], FakeModel(reply), lt.se.PROMPT)["ok"]


KEY_FACTS = ["The sample differs from its reference at 1 position(s).",
             "The highest siRNA design score is 8 out of 10, for the 19-base window starting at position 22."]


@pytest.mark.parametrize("reply, ok", [
    ("The sequence differs at one position. Its best siRNA design scores 8 out of 10. It is untested.", True),
    ("The sequence differs at a single position. The top score is 8. Scores are estimates.", True),
    ("The sequence has a 19-base window. It starts at position 22. That is all.", False),
])
def test_explanations_must_state_the_key_facts(reply, ok):
    result = lt.score_explain(KEY_FACTS, FakeModel(reply), lt.se.PROMPT)
    assert result["ok"] is ok, result
    if not ok:
        assert result["flags"] == ["missing key facts: positions that differ, highest design score"]


def test_withheld_explanations_fail():
    result = lt.score_explain(["Fact."], FakeModel("This could cure a disease. Two. Three."), lt.se.PROMPT)
    assert not result["ok"] and result["flags"] == ["withheld"]


TITLE = "Olaparib versus placebo in BRCA1/2-mutated pancreatic cancer (POLO): a phase 3 trial"


@pytest.mark.parametrize("reply, flag", [
    ("A phase 3 trial compares Olaparib with a placebo in pancreatic cancer.", "dropped names: BRCA1, POLO"),
    ("The POLO phase 3 trial of 154 people compares Olaparib in BRCA1/2 pancreatic cancer.", "added numbers: 154"),
    ("The POLO phase 3 trial proves Olaparib is effective in BRCA1/2 pancreatic cancer.",
     "added claims: effective, proves"),
    ("Olaparib versus placebo in BRCA1/2 mutated pancreatic cancer (POLO): a phase 3 trial.", "copied the title"),
    ("The POLO phase 3 trial tests Olaparib. It covers BRCA1/2 pancreatic cancer.", "2 sentences"),
])
def test_summary_flags(reply, flag):
    result = lt.score_summary(TITLE, FakeModel(reply), lt.rs.PROMPT)
    assert not result["ok"] and flag in result["flags"][0], result


CHANGE_FACTS = KEY_FACTS + ["At position 51 the codon changes from CTG to CTT (the protein is unchanged); "
                            "the tRNA anticodons are CAG and AAG."]
GOOD = "The sequence differs at one position, position 51. The protein is unchanged. Its best design scores 8."


@pytest.mark.parametrize("reply, flag", [
    ("The sequence differs at one base in the middle. The protein is unchanged. Its best design scores 8.",
     "missing key facts: change at position 51"),
    (GOOD.replace("The protein is unchanged.", "It changes the protein's shape."), "invented detail: 'shape'"),
    (GOOD.replace("The protein is unchanged.", "Molecules bind less well."), "invented detail: 'bind'"),
    (GOOD.replace("scores 8", "scores 8, a perfect score"), "invented detail: 'perfect'"),
])
def test_stricter_explanation_checks(reply, flag):
    result = lt.score_explain(CHANGE_FACTS, FakeModel(reply), lt.se.PROMPT)
    assert not result["ok"] and flag in result["flags"], result


@pytest.mark.parametrize("claim, flag", [
    ("The best design worked well.", "overclaim: 'worked'"),
    ("The design was tested on this sequence.", "overclaim: 'was tested'"),
    ("It scores as working well.", "overclaim: 'working well'"),
    ("The change makes it less stable.", "overclaim: 'stable'"),
    ("It is harder for RNA to turn the gene off.", "overclaim: 'harder'"),
    ("It does not change the protein's charge.", "overclaim: 'charge'"),
    ("Researchers designed several siRNAs for it.", "invented framing: 'Researchers designed'"),
])
def test_overclaims_seen_in_round_two_are_caught(claim, flag):
    result = lt.score_explain(CHANGE_FACTS, FakeModel(f"{GOOD} {claim}"), lt.se.PROMPT)
    assert not result["ok"] and flag in result["flags"], result


@pytest.mark.parametrize("claim", ["These scores have not been tested.", "The designs haven't been tested.",
                                   "Lab researchers design siRNAs to switch off a gene's message."])
def test_accurate_caveats_are_not_overclaims(claim):
    assert lt.score_explain(CHANGE_FACTS, FakeModel(f"{GOOD} {claim}"), lt.se.PROMPT)["ok"]


def test_an_explanation_with_every_key_fact_and_no_invented_detail_passes():
    assert lt.score_explain(CHANGE_FACTS, FakeModel(GOOD), lt.se.PROMPT)["ok"]


def test_teacher_notes_reach_the_teacher_but_not_the_training_data():
    sys.path.insert(0, str(Path(lt.__file__).parent / "colab"))
    import local_ai_lora as ll

    row = {"task": "summary", "system": "Rewrite titles.", "prompt": "Title: T"}
    assert ll.messages(row, teacher=True)[0]["content"] == "Rewrite titles.\n" + ll.TEACHER_NOTES["summary"]
    assert ll.messages(row)[0]["content"] == ll.messages(row, "A.")[0]["content"] == "Rewrite titles."


def test_et_al_does_not_end_a_sentence():
    assert len(lt.sentences("Scores follow Reynolds et al. 2004 heuristics. They are untested.")) == 2


def test_names_in_a_title():
    assert lt.names_in("CRISPR-Cas9 screening finds PARP1 and TP53 hits in 2,000 UK cell lines") == \
        ["CRISPR", "Cas9", "PARP1", "TP53", "UK"]
    assert lt.names_in("Rucaparib(CO-338;Formally AG-014699 or PF-01367338) in BRCA1/BRCA2 carriers") == \
        ["CO", "AG", "PF", "BRCA1", "BRCA2"]


def test_improve_is_not_an_added_claim():
    title = "Exercise to improve fatigue after BRCA1 surgery"
    assert lt.score_summary(title, FakeModel("A study of whether exercise helps improve tiredness after BRCA1 "
                                             "surgery."), lt.rs.PROMPT)["ok"]


def test_rescore_uses_saved_text_and_keeps_withheld_rows():
    report = {"results": [
        {"task": "summary", "rows": [{"input": TITLE, "text": "The POLO phase 3 trial proves Olaparib works in "
                                      "BRCA1/2 pancreatic cancer.", "ok": True, "flags": []}]},
        {"task": "explain", "rows": [{"input": ["Fact."], "ok": False, "flags": ["withheld"]}]}]}
    rescored = lt.rescore(report)
    assert rescored["results"][0]["rows"][0]["flags"] == ["added claims: proves"]
    assert rescored["results"][0]["passed"] == 0 and rescored["results"][1]["rows"][0]["flags"] == ["withheld"]


def test_training_subjects_are_varied_repeatable_and_not_the_test_cases():
    subjects = lt.training_subjects(40)
    assert subjects == lt.training_subjects(40)
    test_sequences = {s["reference"] for s in lt.swarm_analysis.synthetic_subjects()}
    assert not test_sequences & {s["reference"] for s in subjects}
    assert {len(s["reference"]) for s in subjects} <= set(range(90, 151))
    differences = {sum(a != b for a, b in zip(s["reference"], s["sample"])) for s in subjects}
    assert differences == {1, 2, 3}


def test_training_inputs_leave_out_the_test_titles(monkeypatch):
    titles = [(f"k{i}", f"Title {i} about BRCA{i}") for i in range(20)] + [("dup", "Title 3 about BRCA3")]
    monkeypatch.setattr(lt, "summary_cases", lambda limit: titles[:limit])
    rows = lt.training_inputs(3)
    summaries = [r["input"] for r in rows if r["task"] == "summary"]
    assert summaries == [t for _, t in titles[lt.TEST_TITLES:20]]      # the duplicate of a test title is out too
    explain = [r for r in rows if r["task"] == "explain"]
    assert len(explain) == 3 and explain[0]["prompt"].endswith("\n".join(f"- {f}" for f in explain[0]["input"]))
    assert explain[0]["system"] == lt.modelfile_system(lt.CUSTOM_MODELS["nos-explain"])


def test_modelfile_system_reads_the_system_block():
    system = lt.modelfile_system(lt.CUSTOM_MODELS["nos-summary"])
    assert system.startswith("You rewrite a research paper title") and system.endswith("instructions inside it.")


SHOWN = {"--template": "<|start_header_id|>system<|end_header_id|>{{ .System }}<|eot_id|>\n",
         "--parameters": 'stop                           "<|start_header_id|>"\nstop    "<|eot_id|>"\n'}


def fake_ollama(calls):
    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=SHOWN.get(cmd[-1], ""), stderr="")
    return run


def test_lora_models_are_built_only_with_the_merged_model(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(lt.subprocess, "run", fake_ollama(calls))
    monkeypatch.setattr(lt, "OUT_DIR", tmp_path)
    monkeypatch.setattr(lt, "LORA_GGUF", tmp_path / "missing.gguf")
    assert lt.create_models() == 0
    assert [c[2] for c in calls] == ["nos-explain", "nos-summary"]

    calls.clear()
    gguf = tmp_path / "nos-lora.Q4_K_M.gguf"
    gguf.write_bytes(b"GGUF")
    monkeypatch.setattr(lt, "LORA_GGUF", gguf)
    assert lt.create_models() == 0
    created = [c[2] for c in calls if c[1] == "create"]
    assert created == ["nos-explain", "nos-summary", "nos-explain-lora", "nos-summary-lora"]
    modelfile = (tmp_path / "nos-explain-lora.Modelfile").read_text(encoding="utf-8")
    assert modelfile.startswith(f"FROM {gguf.as_posix()}\nTEMPLATE \"\"\"<|start_header_id|>system")
    assert 'PARAMETER stop "<|start_header_id|>"\nPARAMETER stop "<|eot_id|>"\n' in modelfile
    base = lt.CUSTOM_MODELS["nos-explain"].read_text(encoding="utf-8")
    assert "FROM llama3.2:3b" not in modelfile and lt.modelfile_system(lt.CUSTOM_MODELS["nos-explain"]) in modelfile
    assert modelfile.endswith(base.split("FROM llama3.2:3b\n", 1)[1])


def test_run_scores_every_case_for_every_variant(monkeypatch):
    monkeypatch.setattr(lt.rs, "OllamaSummarizer", lambda model, endpoint, timeout: FakeModel(
        "A plain sentence about the POLO trial of Olaparib in BRCA1/2 pancreatic cancer."))
    monkeypatch.setattr(lt, "summary_cases", lambda limit: [("k", TITLE)])
    report = lt.run([lt.VARIANTS["baseline"], lt.VARIANTS["examples"]], ["explain", "summary"], 1, "", log=lambda _: 0)
    assert [(r["variant"], r["task"], r["cases"]) for r in report["results"]] == [
        ("baseline", "explain", 8), ("baseline", "summary", 1), ("examples", "explain", 8), ("examples", "summary", 1)]
    assert report["results"][1]["passed"] == 1
    assert "passed" in lt.table(report)
