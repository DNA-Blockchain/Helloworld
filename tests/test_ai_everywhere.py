"""The AI everywhere: "always use the model server" (no yes/no each time), AI summaries on status answers
(exact figures kept, nothing personal sent, never the slow local model), and AI answers to anything else."""
import time
from pathlib import Path

import hosted_ai
from audit_trail import AuditTrail
from rabbitsoft import words as words_module
from rabbitsoft.assistant import Session
from tests.test_hosted_ai import FakeServer
from tests.test_rabbitsoft import RECORDS, FakeAI, make_os


class Summarizer(FakeServer):
    def generate(self, prompt, num_predict=220):
        if self.broken:
            raise RuntimeError("the model server rabbit.example.org returned HTTP 503 (it's starting up)")
        self.prompts.append(prompt)
        if prompt.startswith("You are RabbitSoftware.inc, the operator assistant"):
            return "All 3 nodes are running and their chains are intact; nothing needs attention."
        if "Question: how should I name branches" in prompt:
            return "Use short, descriptive branch names such as feature-x."
        return "The server says base editing worked [1]."


def session(tmp_path, server, always=True, ai=None):
    paths = make_os(tmp_path, time.time())
    s = Session(paths, ai=ai or FakeAI(), hosted=server, search=lambda q: RECORDS)
    s._catalog().add_records(RECORDS)
    if always:
        hosted_ai.set_always_use(paths.rabbit / "settings.json", True)
    return s


def used(s):
    return [e["details"] for e in AuditTrail(str(s.paths.audit)).read_all() if e["action"] == "model_server_used"] \
        if s.paths.audit.exists() else []


def test_always_on_sends_research_to_the_server_without_asking(tmp_path):
    server = Summarizer()
    s = session(tmp_path, server)
    reply = s.handle("base editing sickle cell")
    assert not reply.confirm and reply.text.startswith("The server says base editing worked [1].")
    assert "Written by your model on rabbit.example.org" in reply.text and len(server.prompts) == 1
    assert used(s) == [{"host": "rabbit.example.org", "fell_back": False}]
    hosted_ai.set_always_use(s.paths.rabbit / "settings.json", False)
    assert s.handle("base editing sickle cell").confirm                       # off again: asks each time


def test_status_answers_get_a_summary_with_the_exact_figures_kept(tmp_path):
    server = Summarizer()
    s = session(tmp_path, server)
    reply = s.handle("how are the nodes")
    summary, figures = reply.text.split("\n\nFigures (computed on this PC):\n")
    assert summary == "AI summary: All 3 nodes are running and their chains are intact; nothing needs attention."
    assert figures.startswith("3 nodes. All are running.") and "node-0: 100 blocks" in figures
    assert figures.endswith("the figures were computed on this PC and are exact.")
    prompt = server.prompts[-1]
    assert "Quote every number exactly" in prompt and "node-0: 100 blocks" in prompt
    assert {"host": "rabbit.example.org", "purpose": "status", "topic": "how the nodes are doing"} in used(s)
    assert s.handle("pipeline report").text.startswith("AI summary: All 3 nodes")     # every status answer


def test_status_stays_instant_and_local_when_always_is_off_or_the_server_fails(tmp_path):
    off = session(tmp_path / "off", Summarizer(), always=False)
    assert off.handle("how are the nodes").text.startswith("3 nodes. All are running.")
    assert used(off) == []                                                          # nothing sent, nothing asked
    broken = session(tmp_path / "broken", Summarizer(broken=True))
    reply = broken.handle("how are the nodes")
    assert reply.text.startswith("(Your model didn't answer: the model server rabbit.example.org returned HTTP 503")
    assert "3 nodes. All are running." in reply.text


def test_nothing_personal_or_from_the_user_folder_is_sent(tmp_path, monkeypatch):
    server = Summarizer()
    s = session(tmp_path, server)
    s._summarize_status("x", f"report at {Path.home()}\\reports\\a.md, 3 nodes")
    assert str(Path.home()) not in server.prompts[-1] and "~\\reports\\a.md" in server.prompts[-1]
    before = len(server.prompts)
    assert s._summarize_status("x", "contact me at someone@example.org").startswith("(AI summary held back")
    assert s._summarize_status("x", "call 555-123-4567 tomorrow").startswith("(AI summary held back")
    assert len(server.prompts) == before
    assert s._summarize_status("x", "newest entry 2026-09-30 17:13, last retrieval 2026-10-01 07:50") != ""
    assert len(server.prompts) == before + 1                                            # timestamps aren't phones


def test_anything_else_is_answered_by_the_model(tmp_path):
    server = Summarizer()
    s = session(tmp_path, server)
    reply = s.handle("how should I name branches in this repo")
    assert reply.text.startswith("Use short, descriptive branch names such as feature-x.")
    assert "Written by your model on rabbit.example.org" in reply.text
    assert reply.choices == ["Search public research sources for this", "What I can do"]
    assert "RabbitSoftware: a research OS" in server.prompts[-1]
    assert s.handle("sikle cel").text.startswith('I read that as: "sickle cell".')      # research terms: research first
    assert s.handle("zz").choices                                                      # too little to ask: the menu


def test_general_answers_ask_first_without_always_and_work_on_this_pc(tmp_path):
    class LocalGeneral(FakeAI):
        def generate(self, prompt, num_predict=220):
            return "A local answer." if "Question:" in prompt and "Answer:" in prompt and "operator" not in prompt \
                and "research records below" not in prompt else super().generate(prompt, num_predict)

    asking = session(tmp_path / "ask", Summarizer(), always=False, ai=LocalGeneral())
    assert asking.handle("how should I name branches in this repo").confirm
    assert asking.handle("no").text.startswith("A local answer.")
    no_server = session(tmp_path / "none", None, always=False, ai=LocalGeneral())
    reply = no_server.handle("how should I name branches in this repo")
    assert reply.text.startswith("A local answer.") and "Written by the local AI" in reply.text

# -- regressions from review --------------------------------------------------------------------------------
def test_personal_words_never_reach_the_server_asked_or_always(tmp_path):
    class Local(FakeAI):
        def generate(self, prompt, num_predict=220):
            return "A local answer." if "Question:" in prompt and "operator" not in prompt \
                and "research records below" not in prompt else super().generate(prompt, num_predict)

    for always in (True, False):
        server = Summarizer()
        s = session(tmp_path / str(always), server, always=always, ai=Local())
        for text in ("my email is jane.doe@example.org, what is a good password manager",
                     "call me on 555-123-4567 about the release plan for the website"):
            reply = s.handle(text)
            assert not reply.confirm and server.prompts == []                       # not sent, not even asked
            assert reply.text.startswith("(Your words look like they include") and "nothing was sent" in reply.text
            assert "A local answer." in reply.text


def test_always_is_cleared_when_the_server_changes_or_is_removed(tmp_path):
    settings = tmp_path / "settings.json"
    hosted_ai.save_url(settings, "https://a.example.org")
    hosted_ai.set_always_use(settings, True)
    hosted_ai.save_url(settings, "https://a.example.org")                          # same server: kept
    assert hosted_ai.always_use(settings)
    hosted_ai.save_url(settings, "https://b.example.org")                          # another server: asks again
    assert not hosted_ai.always_use(settings)
    hosted_ai.set_always_use(settings, True)
    hosted_ai.save_url(settings, None)
    hosted_ai.save_url(settings, "https://b.example.org")
    assert not hosted_ai.always_use(settings)


def test_routing_uses_whole_words_and_keeps_medical_questions_research_first(tmp_path):
    s = session(tmp_path, Summarizer())
    s._catalog().add_records([{"source": "pubmed", "external_id": "9", "title": "Fetal hemoglobin outcomes",
                               "abstract": "Outcomes were reported for every arm of the trial.",
                               "source_url": "https://example.org/9", "published_at": "2026",
                               "classification": "public"}])
    assert not s._has_records("how should I name branches in this repo")           # "repo" isn't "reported"
    reply = s.handle("how should I name branches in this repo")
    assert reply.text.startswith("Use short, descriptive branch names") and "not from research records" in reply.text
    assert words_module.mentions_research("what causes autism") and words_module.mentions_research("chronic gastritis")
    assert not words_module.mentions_research("what causes this error in my code")
    assert "I don't have saved records" in s.handle("what causes autism").text      # research-first: offers a search


def test_a_held_back_status_summary_says_why(tmp_path):
    s = session(tmp_path, Summarizer())
    reply = s._status("x", "contact someone@example.org for node access")
    assert reply.text.startswith("(AI summary held back: the figures include what looks like an email address")
    assert "someone@example.org" in reply.text                                      # the figures are still shown
    assert any(d.get("held_back") for d in used(s))
