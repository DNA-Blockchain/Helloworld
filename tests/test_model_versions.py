"""Model versions across GitHub and Hugging Face: the manifest, candidate upload from Colab, recording it,
promotion by the GitHub release, and installing a version into Ollama."""
import hashlib
import json
import types
from pathlib import Path

import pytest
from huggingface_hub import CommitOperationAdd, CommitOperationCopy

import model_versions as mv
import rabbit
from tests.test_hf_publish import hf_publish

ROOT = Path(__file__).resolve().parent.parent
REPO = "owner/Llama-3.2-3B-RabbitSoftware-GGUF"
FILE = "nos-lora.Q4_K_M.gguf"


class FakeHub:
    """Branches, tags and commits like a Hugging Face repo; files are kept as their SHA-256 (and bytes)."""

    def __init__(self):
        self.commits = {"c" * 40: {}}           # commit id -> {path: (sha256, bytes)}
        self.branches = {"main": "c" * 40}
        self.tags = {}
        self.operations = []
        self.uploaded_bytes = 0

    def whoami(self):
        return {"name": "owner"}

    def _resolve(self, revision):
        return self.tags.get(revision) or self.branches.get(revision) or revision

    def create_branch(self, repo, branch, exist_ok=False):
        self.branches.setdefault(branch, self.branches["main"])

    def create_commit(self, repo, revision, operations, commit_message=""):
        files = dict(self.commits[self.branches[revision]])
        for op in operations:
            self.operations.append(type(op).__name__)
            if isinstance(op, CommitOperationAdd):
                data = op.path_or_fileobj if isinstance(op.path_or_fileobj, bytes) else Path(op.path_or_fileobj).read_bytes()
                self.uploaded_bytes += len(data)
                files[op.path_in_repo] = (hashlib.sha256(data).hexdigest(), data)
            elif isinstance(op, CommitOperationCopy):
                files[op.path_in_repo] = self.commits[self._resolve(op.src_revision)][op.src_path_in_repo]
        oid = hashlib.sha1(f"{len(self.commits)}{commit_message}".encode()).hexdigest()
        self.commits[oid] = files
        self.branches[revision] = oid
        return types.SimpleNamespace(oid=oid)

    def model_info(self, repo, revision="main", files_metadata=False):
        oid = self._resolve(revision)
        files = self.commits.get(oid, {})
        siblings = [types.SimpleNamespace(rfilename=p, lfs=types.SimpleNamespace(sha256=s)) for p, (s, _) in files.items()]
        return types.SimpleNamespace(sha=oid, siblings=siblings)

    def list_repo_refs(self, repo):
        return types.SimpleNamespace(tags=[types.SimpleNamespace(name=t) for t in self.tags])

    def create_tag(self, repo, tag, revision, tag_message=""):
        assert tag not in self.tags
        self.tags[tag] = self._resolve(revision)

    def download(self, repo_id, filename, revision):
        data = self.commits[self._resolve(revision)][filename][1]
        path = Path(self.tmp) / f"dl-{hashlib.sha256(data).hexdigest()[:8]}-{Path(filename).name}"
        path.write_bytes(data)
        return str(path)


@pytest.fixture
def hub(tmp_path):
    h = FakeHub()
    h.tmp = tmp_path
    return h


def empty_manifest():
    return {"repo": REPO.split("/")[1], "file": FILE, "versions": []}


def gguf(tmp_path, content=b"weights v1"):
    path = tmp_path / f"model-{hashlib.sha256(content).hexdigest()[:6]}.gguf"
    path.write_bytes(content)
    return path


def candidate(hub, manifest, path, version="1.1.0", release="v0.10.0"):
    return mv.add_candidate(hub, REPO, manifest, path, version, release, "a" * 40,
                            {"method": "LoRA", "examples": 200}, {"explain": "8/8"}, "meta-llama/Llama-3.2-3B-Instruct")


# -- the manifest in the repository -------------------------------------------------------------------
def test_the_repository_manifest_is_valid_and_matches_the_model_card():
    manifest = mv.load()
    assert mv.validate(manifest) == []
    first = manifest["versions"][0]
    assert first["version"] == "1.0.0" and first["sha256"] in (ROOT / "deploy/huggingface/model-card.md").read_text()


def test_validation_catches_every_kind_of_bad_entry():
    good = {"version": "1.0.0", "release": "v0.10.0", "sha256": "a" * 64, "size": 1, "hf_revision": "b" * 40,
            "git_commit": "c" * 40, "base_model": "m", "training": {"x": 1}}
    assert mv.validate({**empty_manifest(), "versions": [good]}) == []
    bad = [{**good, "version": "1.0"}, {**good, "sha256": "A" * 64}, {**good, "hf_revision": "abc"},
           {**good, "git_commit": "c" * 7}, {**good, "release": "0.10.0"}, {**good, "training": {}}, {**good, "size": 0}]
    for entry in bad:
        assert mv.validate({**empty_manifest(), "versions": [entry]}), entry
    assert mv.validate({**empty_manifest(), "versions": [good, {**good, "version": "1.0.0"}]})
    assert mv.validate({"versions": []}) == ["missing repo", "missing file"]


# -- 1. candidates ------------------------------------------------------------------------------------
def test_a_candidate_goes_to_its_own_branch_with_its_entry(hub, tmp_path):
    path = gguf(tmp_path)
    manifest, new = candidate(hub, empty_manifest(), path)
    assert new["sha256"] == mv.file_sha256(path) and new["size"] == path.stat().st_size
    assert hub.branches["main"] == "c" * 40                       # main is untouched until the release
    assert mv.remote_sha256(hub, REPO, FILE, new["hf_revision"]) == new["sha256"]
    saved = json.loads(hub.commits[hub.branches["candidates"]]["versions/1.1.0.json"][1])
    assert saved == new and manifest["versions"] == [new]


def test_candidates_must_be_newer_new_files_and_name_a_release(hub, tmp_path):
    manifest, _ = candidate(hub, empty_manifest(), gguf(tmp_path))
    with pytest.raises(ValueError, match="newer"):
        candidate(hub, manifest, gguf(tmp_path, b"other"), version="1.1.0")
    with pytest.raises(ValueError, match="already a version"):
        candidate(hub, manifest, gguf(tmp_path), version="1.2.0")
    with pytest.raises(ValueError, match="release"):
        candidate(hub, manifest, gguf(tmp_path, b"third"), version="1.2.0", release="soon")


def test_a_pc_records_the_entry_colab_saved(hub, tmp_path):
    _, new = candidate(hub, empty_manifest(), gguf(tmp_path))
    recorded = mv.fetch_candidate(hub, REPO, empty_manifest(), "1.1.0", hub.download)
    assert recorded["versions"] == [new]
    hub.commits[new["hf_revision"]][FILE] = ("f" * 64, b"tampered")
    with pytest.raises(RuntimeError, match="doesn't match"):
        mv.fetch_candidate(hub, REPO, empty_manifest(), "1.1.0", hub.download)


# -- 2. the release promotes ----------------------------------------------------------------------------
def test_the_release_copies_tags_and_checks_without_reuploading(hub, tmp_path):
    path = gguf(tmp_path, b"x" * 100_000)
    manifest, new = candidate(hub, empty_manifest(), path)
    uploaded = hub.uploaded_bytes
    assert mv.promote(hub, REPO, manifest, "v0.10.0", log=lambda *_: None) == ["1.1.0"]
    assert hub.uploaded_bytes - uploaded < 100_000                   # only the card; the model was copied on HF
    assert "CommitOperationCopy" in hub.operations
    assert mv.remote_sha256(hub, REPO, FILE, "main") == new["sha256"]
    assert mv.remote_sha256(hub, REPO, FILE, "model-v1.1.0") == new["sha256"]
    # Running the release again changes nothing; a release with no model does nothing.
    commits = len(hub.commits)
    assert mv.promote(hub, REPO, manifest, "v0.10.0", log=lambda *_: None) == ["1.1.0"] and len(hub.commits) == commits
    assert mv.promote(hub, REPO, manifest, "v0.11.0", log=lambda *_: None) == []


def test_the_release_refuses_a_candidate_that_doesnt_match(hub, tmp_path):
    manifest, new = candidate(hub, empty_manifest(), gguf(tmp_path))
    hub.commits[new["hf_revision"]][FILE] = ("f" * 64, b"tampered")
    with pytest.raises(RuntimeError, match="doesn't match"):
        mv.promote(hub, REPO, manifest, "v0.10.0", log=lambda *_: None)
    assert hub.tags == {}


def test_a_version_already_on_main_is_only_tagged(hub, tmp_path):
    path = gguf(tmp_path)
    manifest, new = candidate(hub, empty_manifest(), path)
    hub.commits[hub.branches["main"]][FILE] = hub.commits[new["hf_revision"]][FILE]     # uploaded before tags existed
    commits = len(hub.commits)
    assert mv.promote(hub, REPO, manifest, "v0.10.0", log=lambda *_: None) == ["1.1.0"]
    assert len(hub.commits) == commits and hub.tags["model-v1.1.0"] == hub.branches["main"]


# -- 3. installing ------------------------------------------------------------------------------------
class FakeOllama:
    def __init__(self, has_base=True):
        self.calls, self.has_base, self.modelfile = [], has_base, ""

    def __call__(self, command, **kw):
        self.calls.append(command)
        if command[1] == "show":
            ok = self.has_base
            out = {"--template": "{{ .Prompt }}", "--parameters": 'stop "<|eot_id|>"'}[command[3]] if ok else ""
            return types.SimpleNamespace(returncode=0 if ok else 1, stdout=out, stderr="")
        self.modelfile = Path(command[-1]).read_text()
        return types.SimpleNamespace(returncode=0, stdout="success", stderr="")


def test_choose_installs_the_newest_released_unless_asked(hub, tmp_path):
    manifest, _ = candidate(hub, empty_manifest(), gguf(tmp_path))
    manifest, _ = candidate(hub, manifest, gguf(tmp_path, b"v2"), version="1.2.0", release="v0.11.0")
    with pytest.raises(ValueError, match="no version has been released"):
        mv.choose(manifest, set(), None, False)
    v, revision = mv.choose(manifest, {"model-v1.1.0"}, None, False)
    assert (v["version"], revision) == ("1.1.0", "model-v1.1.0")
    with pytest.raises(ValueError, match="--candidate"):
        mv.choose(manifest, {"model-v1.1.0"}, "1.2.0", False)
    v, revision = mv.choose(manifest, {"model-v1.1.0"}, "1.2.0", True)
    assert revision == v["hf_revision"]


def test_a_local_copy_with_the_right_sha_is_used_and_downloads_are_checked(hub, tmp_path):
    path = gguf(tmp_path)
    manifest, new = candidate(hub, empty_manifest(), path)
    no_download = lambda **kw: pytest.fail("downloaded although the file was here")
    assert mv.obtain(new, FILE, REPO, "x", [tmp_path / "missing.gguf", path], no_download) == path
    downloaded = mv.obtain(new, FILE, REPO, new["hf_revision"], [], hub.download)
    assert mv.file_sha256(downloaded) == new["sha256"]
    with pytest.raises(RuntimeError, match="wasn't installed"):
        mv.obtain({**new, "sha256": "0" * 64}, FILE, REPO, new["hf_revision"], [], hub.download)


def test_ollama_gets_the_versioned_and_latest_names_with_llama_chat_format(tmp_path):
    run = FakeOllama()
    names = mv.ollama_install(tmp_path / "m.gguf", "1.1.0", tmp_path / "work", run)
    assert names == ["rabbitsoftware:1.1.0", "rabbitsoftware:latest"]
    assert run.modelfile.startswith(f"FROM {(tmp_path / 'm.gguf').as_posix()}\nTEMPLATE \"\"\"{{{{ .Prompt }}}}\"\"\"")
    assert 'PARAMETER stop "<|eot_id|>"' in run.modelfile
    with pytest.raises(RuntimeError, match="ollama pull llama3.2:3b"):
        mv.ollama_install(tmp_path / "m.gguf", "1.1.0", tmp_path / "work", FakeOllama(has_base=False))


def test_rabbit_model_install_and_versions(hub, tmp_path, monkeypatch, capsys):
    manifest, _ = candidate(hub, empty_manifest(), gguf(tmp_path))
    monkeypatch.setattr(mv, "load", lambda path=None: manifest)
    monkeypatch.setattr(rabbit, "ROOT", tmp_path)
    run = FakeOllama()
    assert rabbit.model("versions", api=hub, download=hub.download, run=run) == 0
    assert "candidate for v0.10.0" in capsys.readouterr().out
    assert rabbit.model("install", api=hub, download=hub.download, run=run) == 1
    assert "no version has been released" in capsys.readouterr().out
    assert rabbit.model("install", "1.1.0", candidate=True, api=hub, download=hub.download, run=run) == 0
    assert "Installed rabbitsoftware:1.1.0 and rabbitsoftware:latest" in capsys.readouterr().out


# -- the commands and the release workflow ------------------------------------------------------------
def test_release_notes_and_a_release_without_a_model_need_no_login(monkeypatch, capsys):
    monkeypatch.setattr(hf_publish, "api", lambda: pytest.fail("logged in for a release without a model"))
    assert hf_publish.promote_release("v9.9.9") == 0
    assert "nothing to publish" in capsys.readouterr().out
    assert hf_publish.release_notes("v0.10.0") == 0
    assert "**Model 1.0.0**" in capsys.readouterr().out and "model-v1.0.0" in mv.tag_for("1.0.0")


def test_the_release_workflow_publishes_the_model_before_the_github_release():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    promote = workflow.index("hf_publish.py promote --release")
    assert workflow.index("python -m pytest") < promote < workflow.index("gh release create")
    assert "HF_TOKEN: ${{ secrets.HF_TOKEN }}" in workflow and "hf_publish.py notes" in workflow
