"""Model versions: GitHub records each version of RabbitSoftware.inc's model, Hugging Face stores the file,
and any PC can install a version into Ollama.

    Colab (colab/local_ai_lora_colab.ipynb) trains and converts the model to one GGUF file
      -> python deploy/hf_publish.py candidate --version 1.1.0 --release v0.10.0     (in Colab or on a PC)
           uploads it to the "candidates" branch of the private HF model repo, with its manifest entry
      -> python deploy/hf_publish.py record 1.1.0                                     (on your PC)
           adds that entry to deploy/huggingface/model-versions.json; commit it in a PR, like any change
      -> the GitHub release v0.10.0 (.github/workflows/release.yml) promotes it:
           HF copies the file to main on its own servers, the version is tagged model-v1.1.0, and
           the SHA-256 on main is checked against the manifest
      -> python rabbit.py model install [--version 1.1.0]
           downloads that version with your Hugging Face login, checks its SHA-256, and creates
           rabbitsoftware:1.1.0 and rabbitsoftware:latest in Ollama

The manifest is the record: for each version, the GGUF's SHA-256 and size, the HF commit it was uploaded
in, the GitHub commit it was built from, the base model, how it was trained and how it scored. Entries
are only added, never removed, and a version's identity (version, sha256, size, hf_revision, git_commit) never
changes; its evaluation may be corrected, with the earlier figure kept in a "corrected" note. Whether a version is released is read from Hugging Face (its model-v tag),
so the manifest never has to be changed after the release.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "deploy" / "huggingface" / "model-versions.json"
MODEL_CARD = ROOT / "deploy" / "huggingface" / "model-card.md"
CANDIDATES = "candidates"                  # the HF branch new versions are uploaded to before a release
OLLAMA_NAME = "rabbitsoftware"
OLLAMA_BASE = "llama3.2:3b"                # its chat template and stop tokens go with the weights
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")


def parse_version(text: str) -> tuple[int, int, int]:
    match = SEMVER.match(text or "")
    if not match:
        raise ValueError(f"a version looks like 1.2.0, not {text!r}")
    return tuple(int(x) for x in match.groups())


def tag_for(version: str) -> str:
    return f"model-v{version}"


def load(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(manifest: dict, path: Path = MANIFEST) -> None:
    problems = validate(manifest)
    if problems:
        raise ValueError("the manifest would be invalid: " + "; ".join(problems))
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def validate(manifest: dict) -> list[str]:
    """Every problem with the manifest, as readable lines (empty when it's sound)."""
    problems = []
    for key in ("repo", "file", "versions"):
        if key not in manifest:
            problems.append(f"missing {key}")
    previous = None
    for i, v in enumerate(manifest.get("versions", [])):
        where = f"versions[{i}]"
        try:
            current = parse_version(v.get("version", ""))
        except ValueError as error:
            problems.append(f"{where}: {error}")
            continue
        if previous is not None and current <= previous:
            problems.append(f"{where}: {v['version']} must be newer than the version before it")
        previous = current
        if not re.fullmatch(r"[0-9a-f]{64}", v.get("sha256", "")):
            problems.append(f"{where}: sha256 must be 64 lowercase hex digits")
        if not re.fullmatch(r"[0-9a-f]{40}", v.get("hf_revision", "")):
            problems.append(f"{where}: hf_revision must be a full 40-digit commit id")
        if not re.fullmatch(r"[0-9a-f]{40}", v.get("git_commit", "")):
            problems.append(f"{where}: git_commit must be a full 40-digit commit id")
        if not isinstance(v.get("size"), int) or v["size"] <= 0:
            problems.append(f"{where}: size must be a positive number of bytes")
        release = v.get("release")
        if release is not None and not RELEASE_TAG.match(release):
            problems.append(f"{where}: release must be a tag like v0.10.0 (or null)")
        for key in ("base_model", "training"):
            if not v.get(key):
                problems.append(f"{where}: missing {key}")
    return problems


def entry(manifest: dict, version: str) -> dict:
    for v in manifest["versions"]:
        if v["version"] == version:
            return v
    raise KeyError(f"no version {version} in the manifest")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remote_sha256(api, repo: str, filename: str, revision: str) -> str | None:
    """The SHA-256 Hugging Face stores for a file at a revision (from its LFS pointer), or None."""
    info = api.model_info(repo, revision=revision, files_metadata=True)
    for sibling in info.siblings or []:
        if sibling.rfilename == filename and sibling.lfs is not None:
            return sibling.lfs.sha256
    return None


def _operations():
    """Hugging Face's commit operations (add a file, copy one). Tests swap in stand-ins, so they run where
    huggingface_hub isn't installed, as on CI."""
    from huggingface_hub import CommitOperationAdd, CommitOperationCopy

    return CommitOperationAdd, CommitOperationCopy


def released_tags(api, repo: str) -> set[str]:
    return {t.name for t in api.list_repo_refs(repo).tags}


# -- 1. a new version, from the file Colab made -------------------------------------------------------
def entry_path(version: str) -> str:
    return f"versions/{version}.json"


def add_candidate(api, repo: str, manifest: dict, gguf: Path, version: str, release: str, git_commit: str,
                  training: dict, evaluation: dict, base_model: str) -> tuple[dict, dict]:
    """Uploads the GGUF to the candidates branch, then its manifest entry beside it (versions/<v>.json), so
    a PC that didn't do the upload (Colab did) can record it with fetch_candidate. Returns the manifest
    with the new entry, and the entry."""
    if manifest["versions"] and parse_version(version) <= parse_version(manifest["versions"][-1]["version"]):
        raise ValueError(f"{version} must be newer than {manifest['versions'][-1]['version']}")
    if not RELEASE_TAG.match(release):
        raise ValueError(f"the release that ships it looks like v0.10.0, not {release!r}")
    CommitOperationAdd, _ = _operations()

    sha = file_sha256(gguf)
    if any(v["sha256"] == sha for v in manifest["versions"]):
        raise ValueError("this exact file is already a version in the manifest")
    api.create_branch(repo, branch=CANDIDATES, exist_ok=True)
    commit = api.create_commit(repo, revision=CANDIDATES, operations=[
        CommitOperationAdd(path_in_repo=manifest["file"], path_or_fileobj=str(gguf))],
        commit_message=f"Candidate model {version} for {release} (built from git {git_commit[:12]})")
    if remote_sha256(api, repo, manifest["file"], commit.oid) != sha:
        raise RuntimeError("Hugging Face's copy doesn't match the file that was uploaded")
    new = {"version": version, "release": release, "sha256": sha, "size": Path(gguf).stat().st_size,
           "hf_revision": commit.oid, "git_commit": git_commit, "base_model": base_model,
           "training": training, "evaluation": evaluation}
    updated = {**manifest, "versions": manifest["versions"] + [new]}
    problems = validate(updated)
    if problems:
        raise ValueError("; ".join(problems))
    api.create_commit(repo, revision=CANDIDATES, operations=[
        CommitOperationAdd(path_in_repo=entry_path(version),
                           path_or_fileobj=(json.dumps(new, indent=2) + "\n").encode("utf-8"))],
        commit_message=f"Manifest entry for candidate model {version}")
    return updated, new


def fetch_candidate(api, repo: str, manifest: dict, version: str, download) -> dict:
    """The manifest with the entry Colab saved on the candidates branch, after checking that the file it
    names is on Hugging Face with that SHA-256."""
    path = download(repo_id=repo, filename=entry_path(version), revision=CANDIDATES)
    new = json.loads(Path(path).read_text(encoding="utf-8"))
    if new.get("version") != version:
        raise ValueError(f"{entry_path(version)} describes {new.get('version')!r}")
    if remote_sha256(api, repo, manifest["file"], new.get("hf_revision", "")) != new.get("sha256"):
        raise RuntimeError(f"the file for {version} on Hugging Face doesn't match its entry")
    updated = {**manifest, "versions": manifest["versions"] + [new]}
    problems = validate(updated)
    if problems:
        raise ValueError("; ".join(problems))
    return updated


# -- 2. the GitHub release promotes the versions it ships ---------------------------------------------
def promote(api, repo: str, manifest: dict, release: str, card: Path = MODEL_CARD, log=print) -> list[str]:
    """For every version whose release is this tag: copy its file to main on Hugging Face (a server-side
    copy, no re-upload), update the card, tag the commit model-v<version>, and check the SHA-256 on main.
    Already-promoted versions are checked and left alone. Returns the versions promoted or confirmed."""
    CommitOperationAdd, CommitOperationCopy = _operations()

    shipped = [v for v in manifest["versions"] if v.get("release") == release]
    if not shipped:
        log(f"No model version ships with {release}.")
        return []
    tags = released_tags(api, repo)
    done = []
    for v in shipped:
        tag = tag_for(v["version"])
        if tag in tags:
            if remote_sha256(api, repo, manifest["file"], tag) != v["sha256"]:
                raise RuntimeError(f"{tag} exists but its file doesn't match the manifest")
            log(f"{tag} was already released; its file matches the manifest.")
            done.append(v["version"])
            continue
        if remote_sha256(api, repo, manifest["file"], v["hf_revision"]) != v["sha256"]:
            raise RuntimeError(f"the candidate for {v['version']} on Hugging Face doesn't match the manifest")
        if remote_sha256(api, repo, manifest["file"], "main") == v["sha256"]:
            head = api.model_info(repo, revision="main").sha      # already on main (e.g. uploaded before tags)
            api.create_tag(repo, tag=tag, revision=head, tag_message=f"RabbitSoftware {release}")
            log(f"Model {v['version']} was already on main; tagged it {tag} (commit {head[:12]}).")
            done.append(v["version"])
            continue
        commit = api.create_commit(repo, revision="main", operations=[
            CommitOperationCopy(src_path_in_repo=manifest["file"], path_in_repo=manifest["file"],
                                src_revision=v["hf_revision"]),
            CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=str(card))],
            commit_message=f"Release model {v['version']} with RabbitSoftware {release}")
        if remote_sha256(api, repo, manifest["file"], commit.oid) != v["sha256"]:
            raise RuntimeError(f"main doesn't hold the file of {v['version']} after the copy")
        api.create_tag(repo, tag=tag, revision=commit.oid, tag_message=f"RabbitSoftware {release}")
        log(f"Released model {v['version']} as {tag} (commit {commit.oid[:12]}).")
        done.append(v["version"])
    return done


# -- 3. any PC installs a version into Ollama ---------------------------------------------------------
def choose(manifest: dict, tags: set[str], version: str | None, allow_candidate: bool) -> tuple[dict, str]:
    """The entry to install and the revision to download it from."""
    if version:
        v = entry(manifest, version)
        if tag_for(version) in tags:
            return v, tag_for(version)
        if not allow_candidate:
            raise ValueError(f"{version} isn't released yet; add --candidate to install it anyway")
        return v, v["hf_revision"]
    released = [v for v in manifest["versions"] if tag_for(v["version"]) in tags]
    if not released:
        raise ValueError("no version has been released yet (give --version and --candidate to try one)")
    return released[-1], tag_for(released[-1]["version"])


def obtain(v: dict, filename: str, repo: str, revision: str, known_paths: list[Path], download) -> Path:
    """A local copy of the version's file: one already on this PC with the right SHA-256 (same size first,
    so other files aren't hashed), or a download that is then checked."""
    for path in known_paths:
        if path.is_file() and path.stat().st_size == v["size"] and file_sha256(path) == v["sha256"]:
            return path
    path = Path(download(repo_id=repo, filename=filename, revision=revision))
    actual = file_sha256(path)
    if actual != v["sha256"]:
        raise RuntimeError(f"the downloaded file's SHA-256 is {actual[:12]}..., not {v['sha256'][:12]}... "
                           f"as the manifest records; it wasn't installed")
    return path


def in_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def ollama_command(which=shutil.which, wsl: bool | None = None, run=subprocess.run):
    """The Ollama to install into, and how to name a file for it. In WSL that's Windows' Ollama (ollama.exe)
    when it's there: it holds the models (llama3.2:3b) and is the one RabbitSoftware.inc uses, while a
    Linux Ollama inside WSL keeps a separate, usually empty, store. Windows programs need Windows paths."""
    if (in_wsl() if wsl is None else wsl) and which("ollama.exe"):
        def windows_path(path: Path) -> str:
            done = run(["wslpath", "-w", str(path)], capture_output=True, text=True)
            if done.returncode != 0:
                raise RuntimeError(f"can't give Windows a path for {path}: {done.stderr.strip()}")
            return done.stdout.strip()
        return "ollama.exe", windows_path
    return "ollama", lambda path: Path(path).as_posix()


def ollama_install(gguf: Path, version: str, workdir: Path, run=subprocess.run, ollama=None) -> list[str]:
    """Creates rabbitsoftware:<version> and rabbitsoftware:latest from the file, with Llama 3.2's chat format."""
    command, file_name = ollama or ollama_command(run=run)

    def show(flag: str) -> str:
        done = run([command, "show", OLLAMA_BASE, flag], capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            raise RuntimeError(f"Ollama needs {OLLAMA_BASE} for the chat format: {command} pull {OLLAMA_BASE}")
        return done.stdout

    params = [line.split(None, 1) for line in show("--parameters").splitlines() if line.strip()]
    text = (f"FROM {file_name(Path(gguf))}\n" + f'TEMPLATE """{show("--template").strip()}"""\n'
            + "".join(f"PARAMETER {k} {v.strip()}\n" for k, v in params))
    workdir.mkdir(parents=True, exist_ok=True)
    modelfile = workdir / f"{OLLAMA_NAME}-{version}.Modelfile"
    modelfile.write_text(text, encoding="utf-8")
    names = [f"{OLLAMA_NAME}:{version}", f"{OLLAMA_NAME}:latest"]
    for name in names:
        done = run([command, "create", name, "-f", file_name(modelfile)], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
        if done.returncode != 0:
            raise RuntimeError(f"{command} create {name} failed: {(done.stderr or done.stdout).strip()[-300:]}")
    return names
