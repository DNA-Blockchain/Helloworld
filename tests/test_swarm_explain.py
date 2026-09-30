"""Local AI explanations of swarm results: only verified results are explained,
facts come from code, and drifting AI output is withheld."""
import json

import pytest

import swarm_analysis
import swarm_explain as se


class FakeModel:
    def __init__(self, reply="A plain explanation of the listed facts."):
        self.reply, self.prompts = reply, []

    def generate(self, prompt, num_predict=120):
        self.prompts.append(prompt)
        return self.reply


def _accepted(subject_id="synthetic:4"):
    subject = swarm_analysis.resolve(subject_id, None)
    return subject_id, swarm_analysis.digest(swarm_analysis.analyze(subject))


def test_only_a_reproduced_digest_is_explained():
    subject_id, sha = _accepted()
    subject, analysis = se.verify(subject_id, sha, None)
    assert subject["id"] == subject_id and analysis["subject"] == subject_id
    se.verify(subject_id, sha[:12], None)                      # a 12-character prefix is enough
    with pytest.raises(ValueError, match="unreproducible"):
        se.verify(subject_id, "0" * 64, None)
    with pytest.raises(ValueError):
        se.verify(subject_id, sha[:6], None)                   # too short to mean anything
    with pytest.raises(LookupError):
        se.verify("event:not-here", sha, None)


def test_facts_are_written_by_code_and_mark_the_heuristic():
    subject_id, sha = _accepted()
    subject, analysis = se.verify(subject_id, sha, None)
    facts = se.facts_for(analysis, subject)
    assert facts[0].startswith("Subject: synthetic swarm subject 4 (not a real gene)")
    assert any("missense" in f and "hydropathy" in f for f in facts)
    assert facts[-1].startswith("siRNA scores are Reynolds")


def test_prompt_carries_the_facts_and_the_rules():
    model = FakeModel()
    assert se.explain(["Fact one.", "Fact two."], model) == "A plain explanation of the listed facts."
    [prompt] = model.prompts
    assert "- Fact one.\n- Fact two." in prompt and "Never call anything a treatment" in prompt


@pytest.mark.parametrize("reply", ["This could treat cancer.", "A therapy for patients.",
                                   "The design would correct this change."])
def test_drifting_ai_output_is_withheld(reply):
    with pytest.raises(ValueError, match="withheld"):
        se.explain(["Fact."], FakeModel(reply))


def test_accepted_rounds_are_read_from_a_status_file(tmp_path):
    status = {"work": {"swarm": {"recent": [
        {"round": 1, "status": "ACCEPTED", "subject": "synthetic:1", "analysis_sha256": "aa"},
        {"round": 2, "status": "DISPUTED", "subject": "synthetic:2", "analysis_sha256": "bb"}]}}}
    path = tmp_path / "status.json"
    path.write_text(json.dumps(status))
    assert [v["round"] for v in se.accepted_from_status(path)] == [1]


def test_cli_prints_facts_without_ai_and_refuses_a_forgery(capsys):
    subject_id, sha = _accepted()
    assert se.main(["--subject", subject_id, "--sha256", sha, "--no-ai"]) == 0
    out = capsys.readouterr().out
    assert "verified here" in out and "FACT  Subject:" in out and "AI " not in out
    assert se.main(["--subject", subject_id, "--sha256", "f" * 64, "--no-ai"]) == 1
    assert "not explaining an unreproducible result" in capsys.readouterr().out
