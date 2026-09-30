import sys
import time

from rabbitsoft.assistant import Session
from tests.test_corpus_vector_store import FakeEmbedder
from tests.test_rabbitsoft import FakeAI, make_os, wait_for

HEART = {"source": "pubmed", "external_id": "501", "title": "Cardiac neoplasm outcomes after surgery",
         "source_url": "https://example.org/501", "published_at": "2026", "classification": "public"}


def test_a_question_without_the_records_words_is_answered_by_meaning(tmp_path):
    searched = []
    s = Session(make_os(tmp_path, time.time()), ai=FakeAI(), search=lambda q: searched.append(q) or [],
                embedder=FakeEmbedder())
    s._catalog().add_records([HEART])
    reply = s.handle("heart tumor research")
    assert "Cardiac neoplasm outcomes after surgery" in reply.text and searched == []

    word_only = Session(make_os(tmp_path / "b", time.time()), ai=FakeAI(), search=lambda q: [])
    word_only._catalog().add_records([HEART])
    assert "I don't have saved records" in word_only.handle("heart tumor research").text


def test_an_everyday_word_in_a_title_is_not_a_match(tmp_path):
    s = Session(make_os(tmp_path, time.time()), ai=FakeAI(), search=lambda q: [])
    s._catalog().add_records([{**HEART, "external_id": "502", "title": "Sickle cell disease: from ancient origins"}])
    assert "I don't have saved records" in s.handle("heart attack risk from cholesterol").text


def test_the_corpus_status_says_how_it_searches(tmp_path):
    s = Session(make_os(tmp_path, time.time()), ai=FakeAI())
    assert "The research corpus is empty" in s.handle("what is in the corpus").text
    s._catalog().add_records([HEART])
    text = s.handle("corpus status").text
    assert "holds 1 public records" in text and "0 have their abstract" in text
    assert "Search uses word matching" in text and 'say "fill in abstracts"' in text

    meaning = Session(make_os(tmp_path / "m", time.time()), ai=FakeAI(), embedder=FakeEmbedder())
    meaning._catalog().add_records([HEART])
    assert "Search by meaning uses the local model fake-embed" in meaning.handle("corpus status").text


def test_abstracts_are_fetched_only_after_a_yes_and_are_logged(tmp_path):
    from audit_trail import AuditTrail

    paths = make_os(tmp_path, time.time())
    asked = []
    s = Session(paths, ai=FakeAI(), abstract_fetchers={"pubmed": lambda ids: asked.extend(ids) or
                                                       {"501": "Survival improved after surgery."}})
    s._catalog().add_records([HEART])
    confirm = s.handle("fill in the abstracts")
    assert confirm.confirm and "record numbers of 1 saved record (" in confirm.text and "PubMed" in confirm.text
    assert asked == []
    done = s.handle("yes").text
    assert asked == ["501"] and "Filled in 1 of 1 abstracts." in done and "corpus is updated" in done
    assert "1 have their abstract" in s.handle("corpus status").text
    entry = [e for e in AuditTrail(str(paths.audit)).read_all() if e["action"] == "abstracts_fetched"][-1]
    assert entry["details"]["filled"] == 1 and entry["details"]["sources"] == ["pubmed"]
    assert s.handle("fetch abstracts").text == "Every saved record already has its abstract."


def test_the_meaning_model_is_downloaded_only_after_a_yes(tmp_path):
    paths = make_os(tmp_path, time.time())
    s = Session(paths, ai=FakeAI(), embed_model_command=[sys.executable, "-c", "print('pulled')"])
    confirm = s.handle("download the meaning model")
    assert confirm.confirm and "about 270 MB" in confirm.text and "ollama.com" in confirm.text
    assert s.handle("yes").text.startswith("Started the download.")
    assert wait_for(lambda: s.jobs.items[0].finished is not None)
    assert "nomic-embed-text is on this PC" in s.handle("what's running").text
    assert s._corpus is None                                # reopened with the model on the next question

    ready = Session(paths, ai=FakeAI(), embedder=FakeEmbedder())
    assert ready.handle("install the meaning model").text == "The meaning model (fake-embed) is already on this PC."
