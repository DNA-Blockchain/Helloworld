import http.client
import json
import socket
import threading
import time
import uuid

import pytest

from rabbitsoft import assistant, tools, words
from rabbitsoft.assistant import Session, tidy_answer

VOCAB = words.vocabulary(("hemoglobin",))


# -- understanding what people type -----------------------------------------------------------------

@pytest.mark.parametrize("typed, read", [
    ("crisper sikle cel", "crispr sickle cell"),
    ("how many tokins", "how many tokens"),
    ("is the blokchain ok", "is the blockchain ok"),
    ("BRCA1 and TP53", "BRCA1 and TP53"),               # names with digits are left alone
    ("tell me about it", "tell me about it"),            # ordinary words aren't "corrected"
])
def test_spelling_is_fixed_against_known_words(typed, read):
    assert words.fix_spelling(typed, VOCAB) == read


@pytest.mark.parametrize("text, intent", [
    ("how are the nodes doing", "nodes"),
    ("how many tokens do the nodes have", "ledger"),     # the specific word beats the general one
    ("is the chain ok on every node", "chain"),
    ("what is the research agent doing", "agents"),
    ("show me the daily report", "report"),
    ("help", "help"),
])
def test_requests_go_to_the_right_tool(text, intent):
    assert words.best_intent(text)[0] == intent


def test_a_tie_offers_choices_instead_of_guessing():
    intent, ranked = words.best_intent("tokens and audit")
    assert intent is None and set(ranked) == {"ledger", "chain"}


@pytest.mark.parametrize("text, number", [("2", 2), ("2.", 2), ("number 3", 3), ("the second one", 2),
                                          ("first", 1), ("9", None), ("two apples", None)])
def test_choices_can_be_given_in_several_ways(text, number):
    assert words.choice_number(text, 4) == number


@pytest.mark.parametrize("text, answer", [("yes", True), ("Yes.", True), ("ok", True), ("1", True),
                                          ("no", False), ("cancel", False), ("2", False), ("maybe", None)])
def test_yes_and_no(text, answer):
    assert words.yes_or_no(text) is answer


def test_greetings_and_questions_are_told_apart():
    assert words.is_greeting("hello there") and words.is_greeting("Thanks!")
    assert not words.looks_like_a_question("hello there")
    assert words.looks_like_a_question("sickle cell") and words.looks_like_a_question("gene therapy results")


# -- tools, against a made-up OS on disk --------------------------------------------------------------

def make_os(tmp_path, now, stale_node=None, broken_node=None):
    for n in range(3):
        d = tmp_path / "autonomous" / f"node-{n}"
        d.mkdir(parents=True)
        status = {"updated_at": now - (3600 if n == stale_node else 5), "chain_blocks": 100 + n,
                  "chain_ok": n != broken_node, "connected_peers": [m for m in range(3) if m != n],
                  "research_ledger": {"entries": 40, "ok": True},
                  "work": {"recent_audits": [{"round": 1, "by": n, "target": (n + 1) % 3, "ok": True,
                                               "blocks_checked": 200, "problem_count": 0}]}}
        (d / "status.json").write_text(json.dumps(status))
        others = [m for m in range(3) if m != n]
        (d / f"tokens_node-{n}.json").write_text(json.dumps(
            [{"node_id": f"node-{m}", "amount": 1, "reason": "block verified"} for m in others for _ in range(m + 1)]))
    reports = tmp_path / "autonomous" / "reports"
    reports.mkdir()
    (reports / "2026-09-30.md").write_text("# report\n\nPeriod: yesterday to today\n\n**Overall: OK**\n")
    (tmp_path / "research_store.json").write_text(json.dumps({
        "topics": {"breast cancer|brca1": {"condition": "breast cancer", "biomarker": "BRCA1", "last_checked": now,
                                           "all_ids": {"pubmed": ["1", "2"], "clinicaltrials": ["NCT1"]}}},
        "queue": [["Hereditary Breast Cancer", "BRCA1"]]}))
    return tools.Paths(root=tmp_path, autonomous=tmp_path / "autonomous", audit=tmp_path / "audit.jsonl",
                       research_store=tmp_path / "research_store.json", catalog=tmp_path / "catalog.sqlite3")


def test_node_status_notices_a_stopped_node(tmp_path):
    now = time.time()
    lines = tools.nodes(make_os(tmp_path, now, stale_node=1), now)
    assert lines[0] == "3 nodes. 1 may be stopped (node-1): no update for over 5 minutes."
    assert "node-0: 100 blocks, chain intact, connected to 2 peers" in lines[1]
    assert "node_supervisor.py --status" in lines[-1]


def test_chain_check_reports_a_failure(tmp_path):
    lines = tools.chain(make_os(tmp_path, time.time(), broken_node=2))
    assert lines[0] == "Chain check FAILED on node-2."
    assert "3 audits, 0 found problems" in lines[1] and "40 entries, intact" in lines[2]


def test_ledger_adds_up_what_the_other_nodes_credited(tmp_path):
    lines = tools.ledger(make_os(tmp_path, time.time()))
    # node-m is credited m+1 times by each of the two other nodes
    assert lines[:3] == ["node-2: 6 credits", "node-1: 4 credits", "node-0: 2 credits"]


def test_agents_report_and_swarm(tmp_path):
    paths = make_os(tmp_path, time.time())
    assert tools.agents(paths)[1] == f"breast cancer + BRCA1: 3 records found, last checked {time.strftime('%Y-%m-%d')}."
    assert tools.report(paths)[0] == "Latest daily report: 2026-09-30. Overall: OK"
    assert "haven't recorded swarm rounds" in tools.swarm(paths)[0]


def test_tools_say_so_when_there_is_nothing(tmp_path):
    empty = tools.Paths(root=tmp_path, autonomous=tmp_path / "none", audit=tmp_path / "a.jsonl",
                        research_store=tmp_path / "none.json", catalog=tmp_path / "c.sqlite3")
    for tool in tools.TOOLS.values():
        assert tool(empty)          # a sentence, not an exception


# -- conversations ----------------------------------------------------------------------------------

class FakeAI:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt, num_predict=220):
        self.prompts.append(prompt)
        if prompt.startswith("Someone typed"):
            return "1. sickle cell disease gene therapy\n- Sickle cell CRISPR\n"
        if prompt.startswith("Rewrite this"):
            return "Gene editing fixed blood cells in a study [1]."
        return "**Answer**\nBase editing changed blood cells in a trial [1]. Base editing changed blood cells in a trial [1]. It is new [7]."


RECORDS = [{"source": "pubmed", "external_id": "111", "title": "Base editing for sickle cell disease",
            "abstract": "A base editing trial in sickle cell disease.", "source_url": "https://example.org/111",
            "published_at": "2026", "classification": "public"}]


@pytest.fixture
def session(tmp_path):
    searched = []
    s = Session(make_os(tmp_path, time.time()), ai=FakeAI(),
                search=lambda q: searched.append(q) or RECORDS)
    s.searched = searched
    return s


def test_a_tool_question_is_answered_directly(session):
    reply = session.handle("how are the nodez doing")
    assert reply.text.startswith('I read that as: "how are the node doing".\n3 nodes. All are running.')
    assert not reply.choices and not reply.confirm


def test_a_greeting_gets_the_menu_and_a_number_picks_from_it(session):
    reply = session.handle("hi!")
    assert reply.text.startswith("Hello! I'm RabbitSoftware.inc, the assistant from RabbitSoftware, Inc.")
    assert len(reply.choices) == 10
    assert session.handle("4").text.startswith("node-2: 6 credits")


def test_a_public_search_needs_a_yes_and_logs_only_a_hash(session):
    reply = session.handle("sikle cel")
    assert "I don't have saved records" in reply.text
    assert reply.choices == ['Search for "sickle cell"', 'Search for "sickle cell disease gene therapy"',
                             'Search for "Sickle cell CRISPR"']
    confirm = session.handle("2")
    assert confirm.confirm and '"sickle cell disease gene therapy"' in confirm.text and session.searched == []
    answer = session.handle("yes")
    assert session.searched == ["sickle cell disease gene therapy"]
    assert answer.text.startswith("Found 1 records (1 new, saved on this PC).")
    assert "Base editing changed blood cells in a trial [1]. It is new ." in answer.text   # repeat and [7] gone
    assert "[1] Base editing for sickle cell disease (pubmed, 2026) https://example.org/111" in answer.text
    log = session.paths.audit.read_text()
    assert "public_search" in log and "sickle" not in log


def test_saying_no_sends_nothing(session):
    session.handle("sikle cel")
    session.handle("1")
    assert session.handle("no").text.startswith("OK, I won't do that")
    assert session.searched == [] and not session.paths.audit.exists()


def test_typing_something_else_lets_a_question_lapse(session):
    session.handle("sikle cel")
    session.handle("1")
    assert session.handle("tokens").text.startswith("node-2: 6 credits")
    assert session.handle("yes").text != "" and session.searched == []


def test_saved_records_are_answered_without_searching_and_can_be_simplified(session):
    session._catalog().add_records(RECORDS)
    reply = session.handle("base editing sickle cell")
    assert reply.text.startswith("Base editing changed blood cells") and session.searched == []
    assert reply.choices == ["Explain that more simply", "Search public sources for newer records"]
    assert session.handle("1").text.startswith("Gene editing fixed blood cells in a study [1].")


def test_a_synthetic_subject_is_explained_from_verified_facts(tmp_path):
    class ExplainAI:
        def generate(self, prompt, num_predict=220):
            return "The sequence differs at one position. Its best design scores 9. None of it was tested in a lab."

    s = Session(make_os(tmp_path, time.time()), ai=FakeAI(), explain_ai=ExplainAI())
    reply = s.handle("explain synthetic 3")
    assert reply.text.startswith("Synthetic subject 3, computed on this PC:\n- Subject: synthetic swarm subject 3")
    assert "may be wrong" in reply.text


# -- actions --------------------------------------------------------------------------------------

def wait_for(condition, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.2)
    return False


def test_self_tests_run_in_the_background_and_report_when_done(tmp_path):
    import sys

    paths = make_os(tmp_path, time.time())
    results = paths.rabbit / "self-tests.json"
    fake_run = [sys.executable, "-c",
                "import json, sys; json.dump({'counts': {'PASS': 3, 'FAIL': 1, 'SKIP': 2}, 'results': "
                "[{'file': 'broken.py', 'status': 'FAIL'}]}, open(sys.argv[1], 'w'))", str(results)]
    s = Session(paths, ai=FakeAI(), self_test_command=fake_run)
    ask = s.handle("run the self tests")
    assert ask.confirm and "nothing leaves this PC" in ask.text
    assert s.handle("yes").text.startswith("Started the self-tests.")
    assert wait_for(lambda: s.jobs.items[0].finished is not None)
    reply = s.handle("tokens")
    assert reply.text.startswith("Done: The self-tests: finished. 3 passed, 1 failed, 2 skipped (sites outside this PC). Failed: broken.py.")
    assert "Done:" not in s.handle("tokens").text                       # mentioned once
    assert "self_tests_started" in paths.audit.read_text()


def test_the_research_agent_starts_and_stops_only_after_a_yes(tmp_path):
    import sys

    from rabbitsoft.jobs import Service

    paths = make_os(tmp_path, time.time())
    agent = Service("research-agent", paths.rabbit, [sys.executable, "-c", "import time; time.sleep(120)"],
                    tmp_path, marker="time.sleep(120)")
    s = Session(paths, ai=FakeAI(), agent=agent)
    assert "isn't running now" in s.handle("what is the research agent doing").text
    assert s.handle("stop the research agent").text.startswith("The research agent isn't running")

    ask = s.handle("please start the reserch agent")
    assert ask.confirm and "127.0.0.1:8765" in ask.text and "PubMed" in ask.text and '"breast cancer"' in ask.text
    assert agent.pid() is None                                           # nothing started before the yes
    assert s.handle("yes").text.startswith("Started the research agent (process ")
    try:
        assert wait_for(lambda: agent.pid() is not None)
        assert "The agent is running (process" in s.handle("what is the research agent doing").text
        assert "already running" in s.handle("start the research agent").text
        assert s.handle("stop the research agent").confirm
        assert s.handle("yes").text.startswith("Stopped the research agent.")
        assert wait_for(lambda: agent.pid() is None)
    finally:
        agent.stop()
    log = paths.audit.read_text()
    assert "agent_started" in log and "agent_stopped" in log


def test_a_reused_process_id_is_never_stopped(tmp_path):
    import os

    from rabbitsoft.jobs import Service

    agent = Service("research-agent", tmp_path, ["unused"], tmp_path, marker="run_agent.py")
    tmp_path.mkdir(exist_ok=True)
    agent.pid_file.write_text(json.dumps({"pid": os.getpid()}))           # alive, but it's pytest, not the agent
    assert agent.pid() is None and agent.stop() is False


def test_whats_running(tmp_path):
    s = Session(make_os(tmp_path, time.time()), ai=FakeAI())
    assert s.handle("what's running").text == "Nothing else is running. The research agent isn't running."


def test_tidy_answer_removes_headings_repeats_and_missing_citations():
    raw = "**Facts:**\n* Claim one [1].\n* Claim one [1].\nClaim two [9]."
    assert tidy_answer(raw, 3) == "Claim one [1]. Claim two ."


# -- the web page -----------------------------------------------------------------------------------

@pytest.fixture
def server(tmp_path):
    from rabbitsoft.web import serve

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    paths = make_os(tmp_path, time.time())
    srv = serve(port, paths, factory=lambda: Session(paths, ai=FakeAI(), search=lambda q: []))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port
    srv.shutdown()
    srv.server_close()


def call(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
    response = conn.getresponse()
    return response.status, response.read()


def test_the_page_is_served(server):
    status, body = call(server, "GET", "/")
    assert status == 200 and b"<title>RabbitSoftware.inc</title>" in body and b'role="log"' in body


def test_the_page_uses_the_same_names_as_the_code():
    from rabbitsoft import COMPANY, NAME
    from rabbitsoft.web import PAGE

    page = PAGE.read_text(encoding="utf-8")
    assert f'const NAME = "{NAME}", COMPANY = "{COMPANY}"' in page
    assert f"<h1>{NAME}</h1>" in page and f"by {COMPANY}" in page


def test_messages_keep_their_conversation(server):
    key, headers = str(uuid.uuid4()), {"X-Rabbit": "1", "Content-Type": "application/json"}
    status, body = call(server, "POST", "/api/message", {"session": key, "text": "hello"}, headers)
    assert status == 200 and len(json.loads(body)["choices"]) == 10
    status, body = call(server, "POST", "/api/message", {"session": key, "text": "4"}, headers)
    assert json.loads(body)["text"].startswith("node-2: 6 credits")


@pytest.mark.parametrize("headers", [{}, {"X-Rabbit": "1", "Host": "evil.example:80"}])
def test_other_websites_cannot_send_messages(server, headers):
    status, _ = call(server, "POST", "/api/message", {"session": str(uuid.uuid4()), "text": "hi"}, headers)
    assert status == 403


def test_polling_is_quiet_when_nothing_finished(server):
    status, body = call(server, "POST", "/api/poll", {"session": str(uuid.uuid4()), "text": ""}, {"X-Rabbit": "1"})
    assert status == 200 and json.loads(body) == {"text": ""}


def test_a_bad_session_id_is_refused(server):
    status, _ = call(server, "POST", "/api/message", {"session": "x", "text": "hi"}, {"X-Rabbit": "1"})
    assert status == 400
