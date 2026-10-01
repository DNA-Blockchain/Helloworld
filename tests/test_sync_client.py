"""The Python sync client against the REAL sync Worker code (deploy/cloudflare-sync), run locally by Node
with an in-memory bucket, so the signatures, encryption and formats are tested end to end."""
import shutil
import subprocess
from pathlib import Path

import pytest

from rabbitsoft import sync
from rabbitsoft.sync import SyncClient, SyncError
from research_catalog import ResearchCatalog

SERVER = Path(__file__).resolve().parent.parent / "deploy" / "cloudflare-sync" / "test" / "local_server.mjs"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")

RECORD = {"source": "pubmed", "external_id": "77", "title": "Base editing in sickle cell disease",
          "abstract": "Fetal hemoglobin rose.", "source_url": "https://pubmed.ncbi.nlm.nih.gov/77/",
          "published_at": "2026", "classification": "public"}


@pytest.fixture
def server():
    process = subprocess.Popen(["node", str(SERVER), "0"], stdout=subprocess.PIPE, text=True)
    line = process.stdout.readline()
    assert line.startswith("listening "), line
    yield f"http://127.0.0.1:{line.split()[1]}"
    process.terminate()
    process.wait(timeout=10)


def test_codes_and_phrases_round_trip():
    secret = bytes(range(32))
    phrase = sync.phrase_for(secret)
    assert len(phrase.split("-")) == 13 and sync.secret_from_phrase(phrase.lower().replace("-", " ")) == secret
    with pytest.raises(ValueError):
        sync.secret_from_phrase("ABCD-EFGH")
    sealed = sync.seal(secret, "ABCD", "EFGHJKLM")
    assert sync.unseal(sealed, "ABCD", "EFGHJKLM") == secret
    with pytest.raises(ValueError, match="doesn't match"):
        sync.unseal(sealed, "ABCD", "EFGHJKLZ")
    assert sync.split_code("abcd efgh-jklm") == ("ABCD", "EFGHJKLM")


def test_one_account_many_devices(server, tmp_path):
    laptop = SyncClient(tmp_path / "laptop", server)
    with pytest.raises(SyncError, match="new accounts aren't open yet"):
        laptop.create_account("laptop", "wrong-key")
    phrase = laptop.create_account("laptop", "letmein")
    assert laptop.info()["name"] == "laptop" and len(phrase.split("-")) == 13
    with pytest.raises(SyncError, match="already belongs"):
        laptop.create_account("laptop", "letmein")

    phone = SyncClient(tmp_path / "phone", server)
    code = laptop.make_pairing_code()
    with pytest.raises(ValueError, match="doesn't match"):
        phone.join_with_code(code[:-1] + ("A" if code[-1] != "A" else "B"), "phone")
    phone.join_with_code(code, "phone")
    tablet = SyncClient(tmp_path / "tablet", server)
    tablet.join_with_phrase(phrase, "tablet")
    assert phone.info()["account"] == tablet.info()["account"] == laptop.info()["account"]
    assert sorted(d["name"] for d in laptop.devices()) == ["laptop", "phone", "tablet"]

    # History is encrypted on the device that writes it and read on another device of the same account.
    laptop.push_history([{"time": 1, "question": "What is HBB?", "answer": "The beta-globin gene."}])
    phone.push_history([{"time": 2, "question": "And base editing?", "answer": "Changes one DNA letter."}])
    history = tablet.pull_history()
    assert [(e["device"], e["question"]) for e in history] == [("laptop", "What is HBB?"), ("phone", "And base editing?")]

    # A removed device is cut off.
    phone.remove_device(laptop.info()["device"])
    with pytest.raises(SyncError, match="isn't part of the account"):
        laptop.devices()


def test_research_records_grow_every_devices_corpus(server, tmp_path):
    a = SyncClient(tmp_path / "a", server)
    a.create_account("a", "letmein")
    b = SyncClient(tmp_path / "b", server)
    b.join_with_code(a.make_pairing_code(), "b")
    catalog_a = ResearchCatalog(tmp_path / "a.sqlite3")
    catalog_b = ResearchCatalog(tmp_path / "b.sqlite3")
    catalog_a.add_records([RECORD])

    assert a.sync(catalog_a, [])["pushed"] == 1
    result = b.sync(catalog_b, [])
    assert result["added"] == 1 and result["pushed"] == 0            # pulled records aren't pushed back
    assert [r["title"] for r in catalog_b.all_records()] == [RECORD["title"]]
    assert a.sync(catalog_a, [])["pushed"] == 0                       # nothing new, nothing re-sent


def test_sharing_an_answer_for_training(server, tmp_path):
    a = SyncClient(tmp_path / "a", server)
    a.create_account("a", "letmein")
    a.share_training("What is HBB?", "The beta-globin gene.", ["https://pubmed.ncbi.nlm.nih.gov/77/"], rating=1,
                     model="rabbitsoftware")
    with pytest.raises(SyncError, match="rating must be"):
        a.share_training("q", "a", [], rating=7)
