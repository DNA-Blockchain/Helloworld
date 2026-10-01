"""RabbitSoftware.inc's account and sync conversation, against the real sync Worker run locally."""
import time

import pytest

from rabbitsoft.assistant import Session
from rabbitsoft.sync import SyncClient
from tests.test_rabbitsoft import RECORDS, FakeAI, make_os
from tests.test_sync_client import server  # noqa: F401  (the local sync service fixture)

pytestmark = pytest.mark.skipif(__import__("shutil").which("node") is None, reason="Node.js isn't installed")


def _session(tmp_path, url, name):
    paths = make_os(tmp_path / name, time.time())
    (paths.rabbit).mkdir(parents=True, exist_ok=True)
    (paths.rabbit / "signup.key").write_text("letmein")
    return Session(paths, ai=FakeAI(), search=lambda q: RECORDS, sync_client=SyncClient(paths.rabbit / "account", url))


def test_an_account_is_created_and_a_second_device_joins_and_syncs(tmp_path, server):  # noqa: F811
    from audit_trail import AuditTrail

    laptop = _session(tmp_path, server, "laptop")
    assert "no RabbitSoftware account yet" in laptop.handle("my account").text
    ask = laptop.handle("create an account")
    assert ask.confirm and "recovery phrase once" in ask.text and not laptop.sync_client.has_account()
    made = laptop.handle("yes").text
    assert "recovery phrase" in made and laptop.sync_client.has_account()
    assert "already" not in made and len(made.split("    ")[1].split("\n")[0].split("-")) == 13

    laptop._catalog().add_records(RECORDS)
    answered = laptop.handle("base editing sickle cell")
    assert "Share this answer for training" in answered.choices
    code = laptop.handle("add a device").text.split("join with code ")[1].split("\n")[0]

    phone = _session(tmp_path, server, "phone")
    assert phone.handle(f"join with code {code}").text.startswith("This device joined your account.")
    assert "base editing sickle cell" not in phone.handle("my account").text
    assert laptop.handle("sync now").text.startswith("Synced. Sent 1 research records")
    synced = phone.handle("sync now").text
    assert "brought in 1 from other devices" in synced
    assert [r["title"] for r in phone._catalog().all_records()] == [RECORDS[0]["title"]]
    assert [e["question"] for e in phone.sync_client.pull_history()] == ["base editing sickle cell"]

    listed = phone.handle("my devices").text
    assert "1." in listed and "2." in listed and "(this one)" in listed
    actions = [e["action"] for e in AuditTrail(str(laptop.paths.audit)).read_all()]
    assert {"account_created", "pairing_code_made", "synced"} <= set(actions)


def test_sharing_an_answer_asks_and_refuses_personal_information(tmp_path, server):  # noqa: F811
    s = _session(tmp_path, server, "a")
    s.handle("create an account")
    s.handle("yes")
    s._catalog().add_records(RECORDS)
    s.handle("base editing sickle cell")
    ask = s.handle("3")                                   # "Share this answer for training"
    assert ask.confirm and "no name, account or device" in ask.text
    assert s.handle("yes").text.startswith("Shared.")

    s.last_exchange = {"time": 1, "question": "my email is jo@example.com", "answer": "ok", "sources": []}
    assert "personal information" in s.confirm_share_training().text


def test_a_lost_device_is_replaced_with_the_recovery_phrase_typed_hidden(tmp_path, server, capsys):  # noqa: F811
    import rabbit

    old = _session(tmp_path, server, "old")
    old.handle("create an account")
    phrase = old.handle("yes").text.split("    ")[1].split("\n")[0]
    new = _session(tmp_path, server, "new")
    typed = []
    assert rabbit.account("recover", None, session=new, secret_input=lambda prompt: typed.append(prompt) or phrase) == 0
    assert typed == ["Recovery phrase (hidden as you type): "]
    assert new.sync_client.info()["account"] == old.sync_client.info()["account"]
    assert "back in your account" in capsys.readouterr().out
    assert rabbit.account("recover", None, session=_session(tmp_path, server, "bad"),
                          secret_input=lambda prompt: "ABCD-EFGH") == 1


def test_without_an_account_nothing_is_offered_or_sent(tmp_path, server):  # noqa: F811
    paths = make_os(tmp_path, time.time())
    s = Session(paths, ai=FakeAI(), sync_client=SyncClient(paths.rabbit / "account", server))
    s._catalog().add_records(RECORDS)
    assert "Share this answer for training" not in s.handle("base editing sickle cell").choices
    assert "no RabbitSoftware account yet" in s.handle("sync now").text
    assert s.handle("create an account").text == "New accounts aren't open yet. They open at the public launch."
