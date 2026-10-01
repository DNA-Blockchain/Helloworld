"""Shared answers through SQL (D1) to the private Hugging Face dataset as Parquet, end to end against the REAL
sync Worker code run locally by Node (SQLite in place of D1), with a stand-in for the Hugging Face API."""
import hashlib
import io
import shutil
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
import pytest

import node_supervisor
import rabbit
from rabbitsoft import training_export
from rabbitsoft.sync import SyncClient, SyncError, _id, _raw_public, account_keys
from research_catalog import ResearchCatalog
from tests.test_sync_client import RECORD, SERVER

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
OWNER_SECRET = bytes(range(32))


def owner_id() -> str:
    return _id(_raw_public(account_keys(OWNER_SECRET)[1]))


@pytest.fixture
def server():
    process = subprocess.Popen(["node", str(SERVER), "0", owner_id()], stdout=subprocess.PIPE, text=True)
    line = process.stdout.readline()
    assert line.startswith("listening "), line
    yield f"http://127.0.0.1:{line.split()[1]}"
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture
def clients(server, tmp_path):
    owner = SyncClient(tmp_path / "owner", server)
    owner._register(OWNER_SECRET, "owner-pc", "letmein")
    user = SyncClient(tmp_path / "user", server)
    user.create_account("user-pc", "letmein")
    return owner, user


class FakeHub:
    def __init__(self, private=True):
        self.private, self.files, self.uploads = private, {"README.md": b""}, []

    def whoami(self):
        return {"name": "owner"}

    def repo_info(self, repo, repo_type):
        assert repo_type == "dataset"
        return type("Info", (), {"private": self.private})()

    def list_repo_files(self, repo, repo_type):
        return list(self.files)

    def upload_file(self, path_or_fileobj, path_in_repo, repo_id, repo_type, commit_message):
        self.files[path_in_repo] = path_or_fileobj
        self.uploads.append((repo_id, path_in_repo))
        return type("Commit", (), {"oid": "c0ffee" * 6})()


def test_shared_answers_go_through_sql_to_parquet_once(clients):
    owner, user = clients
    user.share_training("What does HBB encode?", "Beta-globin [1].", ["https://pubmed.ncbi.nlm.nih.gov/1/"], rating=1, model="local")
    user.share_training("Is it inherited?", "Autosomal recessive [2].", [], rating=0, model="rabbitsoftware")
    user.share_training("Off topic?", "No.", [], rating=-1)
    with pytest.raises(SyncError, match="only the owner"):
        user.admin_training()
    pending = owner.admin_training("pending")
    assert len(pending) == 3 and all(p["status"] == "pending" for p in pending)
    off_topic = next(p["id"] for p in pending if p["question"] == "Off topic?")
    assert owner.review_training([off_topic], "rejected") == 1

    hub, asked = FakeHub(), []
    result = training_export.export(owner, hub=hub, ask=lambda q: asked.append(q) or "yes", today="2026-10-01")
    assert result["exported"] == 2 and result["marked"] == 2 and result["file"] == "data/2026-10-01.parquet"
    assert "private dataset owner/rabbitsoftware-training" in asked[0]
    data = hub.files["data/2026-10-01.parquet"]
    assert hashlib.sha256(data).hexdigest() == result["sha256"]
    table = pq.read_table(io.BytesIO(data))
    assert table.column_names == list(training_export.COLUMNS) and str(table.schema.field("rating").type) == "int8"
    rows = sorted(table.to_pylist(), key=lambda r: r["question"])
    assert rows[0]["question"] == "Is it inherited?" and rows[1]["sources"] == ["https://pubmed.ncbi.nlm.nih.gov/1/"]

    assert training_export.export(owner, hub=hub, ask=lambda q: "yes")["exported"] == 0   # nothing twice
    user.share_training("And treatment?", "Gene therapy [3].", [])
    second = training_export.export(owner, hub=hub, ask=lambda q: "yes", today="2026-10-01")
    assert second["file"] == "data/2026-10-01-2.parquet"                                  # same day: a new file
    stats = owner.admin_stats()
    assert stats["accounts"] == 2 and stats["exports"]["files"] == 2 and stats["exports"]["rows"] == 3


def test_export_asks_first_screens_again_and_never_goes_public(clients):
    owner, user = clients
    user.share_training("Fine question?", "Fine answer.", [])
    user.share_training("Call me?", "Reach me at 555-123-4567.", [])     # got past a device, the export catches it
    hub = FakeHub()
    assert training_export.export(owner, hub=hub, ask=lambda q: "no")["message"] == "Nothing was uploaded."
    assert hub.uploads == []
    rejected = [p for p in owner.admin_training("rejected")]
    assert [p["question"] for p in rejected] == ["Call me?"]
    with pytest.raises(RuntimeError, match="is public"):
        training_export.export(owner, hub=FakeHub(private=False), ask=lambda q: "yes")
    assert owner.training_to_export()[0]["question"] == "Fine question?"                    # still waiting


def test_the_shared_corpus_is_searchable_in_sql(clients, tmp_path):
    owner, _ = clients
    catalog = ResearchCatalog(tmp_path / "c.sqlite3")
    catalog.add_records([RECORD])
    owner.push_corpus(catalog)
    assert [r["external_id"] for r in owner.corpus_search("sickle editing")] == ["77"]
    assert owner.corpus_stats()["total"] == 1


def test_the_training_command(clients, capsys, monkeypatch):
    owner, user = clients
    user.share_training("Q?", "A.", [], rating=1)
    session = type("S", (), {"sync_client": owner, "paths": None, "_log": lambda self, *a: None})()
    assert rabbit.training("pending", [], session=session) == 0
    out = capsys.readouterr().out
    answer_id = out.split()[0]
    assert "1 answer(s) waiting for review." in out
    assert rabbit.training("approve", [answer_id], session=session) == 0
    assert "1 answer(s) marked approved." in capsys.readouterr().out
    assert rabbit.training("stats", [], session=session) == 0
    assert "Shared answers: approved 1 (0 exported)" in capsys.readouterr().out
    user_session = type("S", (), {"sync_client": user, "paths": None, "_log": lambda self, *a: None})()
    assert rabbit.training("stats", [], session=user_session) == 1
    assert "only the owner" in capsys.readouterr().out


def test_the_daily_export_runs_only_when_turned_on(tmp_path, monkeypatch):
    from rabbitsoft.tools import Paths

    paths = Paths(root=tmp_path, autonomous=tmp_path / "autonomous")
    assert node_supervisor.training_export_section(paths) == ("", [])                       # off by default
    training_export.set_exporting_daily(paths, True)
    assert training_export.exporting_daily(paths)

    class Broken:
        def __init__(self, paths):
            self.sync_client, self._log = None, lambda *a: None

    section, problems = node_supervisor.training_export_section(paths, session_factory=Broken)
    assert section.startswith("\n## Training export\n\n- [ALERT] training export didn't run") and problems
