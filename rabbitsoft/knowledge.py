"""The project knowledge base: the research reports in docs/research/, searchable by meaning, for
RabbitSoftware.inc and the model, and kept as a private Hugging Face dataset.

    python rabbit.py knowledge status            sections, vectors, fingerprint, what's on Hugging Face
    python rabbit.py knowledge search "what can EEG decode"
    python rabbit.py knowledge sync              rebuild the index after reports change (also done when needed)
    python rabbit.py knowledge publish           asks first; uploads to the private dataset rabbitsoftware-knowledge

Every Markdown file under docs/research/ is split into sections at its headings (H1-H3). A long section is split
again at paragraph boundaries. Each section gets a stable ID (path#heading-slug, numbered if split), its text's
SHA-256, and the source links it cites. The sections are indexed like the research corpus
(corpus_vector_store.py: nomic-embed-text when Ollama has it, TF-IDF until then), in their own store, so project
knowledge and public research records stay separate. The fingerprint, a SHA-256 over every section's ID and hash,
changes whenever any section does.

Questions the reports cover are answered from the matching sections, with [K1]-style citations. The passages go to
the model with the question: to this PC's model, or to the model server under the usual consent rules. The reports
hold public research, nothing personal.

Publishing writes data/knowledge.parquet (zstd), manifest.json (fingerprint plus each section's ID and SHA-256)
and the dataset card to a private dataset. It skips the upload when the fingerprint on Hugging Face already
matches, and refuses a repo that isn't private. Earlier versions stay in the dataset's git history.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path

IDENTITY = "rabbitsoftware-project-knowledge"
DATASET_REPO = "rabbitsoftware-knowledge"
MAX_CHARS = 1800                  # a section longer than this is split at paragraph boundaries
URL = re.compile(r"https?://[^\s)\]>\"']+")
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
CARD = Path(__file__).resolve().parent.parent / "deploy" / "huggingface" / "knowledge-card.md"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"`", "", text.lower())).strip("-")[:80] or "section"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pieces(body: str) -> list[str]:
    """A section's text, split at paragraph boundaries into parts of at most MAX_CHARS (a single longer
    paragraph stays whole)."""
    parts, current = [], ""
    for paragraph in re.split(r"\n\s*\n", body.strip()):
        if current and len(current) + len(paragraph) + 2 > MAX_CHARS:
            parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    return parts + ([current] if current else [])


def _blocks(text: str, title: str) -> list[tuple[list[str], str]]:
    """(heading path, body) per heading. The path keeps the parent headings, so a "### Cited Findings" under
    "## Datasets" is "Datasets > Cited Findings", not one of many identical "Cited Findings". Lines inside
    fenced code blocks are never headings."""
    blocks, path, lines, fence = [], [], [], None
    for line in text.splitlines():
        stripped = line.lstrip()
        if fence is None and stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
        elif fence is not None and stripped.startswith(fence):
            fence = None
        elif fence is None and (m := HEADING.match(line)):
            blocks.append((path or [title], "\n".join(lines)))
            level = len(m.group(1))
            path = (path[:level - 1] if level > 1 else []) + [m.group(2)]
            path = [p for p in path if p]
            lines = []
            continue
        lines.append(line)
    blocks.append((path or [title], "\n".join(lines)))
    return blocks


def sections(path: Path, root: Path) -> list[dict]:
    """The knowledge sections of one Markdown file. IDs are the file plus the heading path (and ~pN for later parts
    of a long section, ~dN for a repeated heading path), so they can't collide and stay stable when other
    sections change."""
    rel = path.relative_to(root).as_posix()
    text = path.read_bytes().decode("utf-8-sig", errors="replace")     # a BOM or a stray byte can't break it
    title = next((m.group(2) for line in text.splitlines() if (m := HEADING.match(line)) and m.group(1) == "#"),
                 path.stem.replace("-", " "))
    out, seen = [], set()
    for heading_path, body in _blocks(text, title):
        pieces = _pieces(body)
        if not pieces:                      # a heading with nothing under it (or text before the title): no section
            continue
        trail = heading_path[1:] if len(heading_path) > 1 and heading_path[0] == title else heading_path
        heading = " > ".join(trail) or title
        base = f"{rel}#" + "/".join(_slug(h) for h in trail or [title])
        n_dup = 1
        while (base if n_dup == 1 else f"{base}~d{n_dup}") in seen:
            n_dup += 1
        base = base if n_dup == 1 else f"{base}~d{n_dup}"
        for n, piece in enumerate(pieces, start=1):
            sid = base if n == 1 else f"{base}~p{n}"
            seen.add(sid)
            heading_text = heading if n == 1 else f"{heading} (part {n})"
            full = f"{title} - {heading_text}\n\n{piece}"
            out.append({"id": sid, "path": rel, "title": title, "heading": heading_text, "text": full,
                        "body": piece, "sha256": _sha(full), "urls": sorted(set(URL.findall(piece)))[:30]})
        seen.add(base)
    return out


def tracked_files(root: Path, dirs: tuple[str, ...]) -> set[str] | None:
    """Files under dirs that git tracks (committed or staged), or None if git can't tell."""
    import subprocess

    try:
        out = subprocess.run(["git", "ls-files", "--", *dirs], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return set(out.stdout.split("\n")) - {""} if out.returncode == 0 else None


def collect(root: Path, dirs: tuple[str, ...] = ("docs/research",), only: set[str] | None = None) -> list[dict]:
    """Every section of every report under dirs (README indexes excluded), or only of the files in `only`."""
    found = []
    for d in dirs:
        for path in sorted((root / d).rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            if path.name.lower() != "readme.md" and (only is None or rel in only):
                found += sections(path, root)
    return found


def fingerprint(items: list[dict]) -> str:
    return _sha("\n".join(f"{s['id']} {s['sha256']}" for s in sorted(items, key=lambda s: s["id"])))


def _document(s: dict) -> dict:
    """A section as a corpus document (the fields CorpusVectorStore and its search results carry)."""
    return {"id": s["id"], "text": s["text"], "source": "project-knowledge", "record_id": s["id"],
            "title": f"{s['title']} - {s['heading']}", "url": s["path"], "published_at": "", "abstract": s["body"],
            "sha256": s["sha256"], "urls": s["urls"]}


class KnowledgeBase:
    def __init__(self, root: Path, store_path: Path, embedder=None, dirs: tuple[str, ...] = ("docs/research",)):
        self.root, self.store_path, self.embedder, self.dirs = Path(root), Path(store_path), embedder, dirs
        self._store = None
        self.rebuilt = ""            # why the index file was rebuilt from the reports, if it was

    @property
    def store(self):
        if self._store is None:
            from corpus_vector_store import CorpusVectorStore

            try:
                self._store = CorpusVectorStore(IDENTITY, str(self.store_path), embedder=self.embedder)
            except (ValueError, KeyError, OSError) as error:   # unreadable or foreign: it's only an index, rebuild it
                self.rebuilt = f"{type(error).__name__}: {error}"[:200]
                self._store = CorpusVectorStore(IDENTITY, None, embedder=self.embedder)
                self._store.store_path = str(self.store_path)
        return self._store

    def sync(self) -> dict:
        """Brings the index up to date with the reports: new and changed sections are (re)indexed, sections whose
        files or headings are gone are dropped. Returns the counts."""
        current = collect(self.root, self.dirs)
        wanted = {s["id"] for s in current}
        store = self.store
        before = len(store.documents)
        kept = [d for d in store.documents if d["id"] in wanted]
        removed = before - len(kept)
        if removed:
            store.documents = kept
            store.vectors = {k: v for k, v in store.vectors.items() if k in wanted}
            store._refit()
            store._save()
        changed = store.add_documents([_document(s) for s in current])
        embedded = store.embed_missing()
        return {"sections": len(current), "changed": changed, "removed": removed, "embedded": embedded,
                "method": store.method(), "fingerprint": fingerprint(current),
                "embed_error": store.last_error, "rebuilt": self.rebuilt}

    def search(self, query: str, top_k: int = 4, require_neural: bool = False) -> list[dict]:
        """Sections about the query, best first, above the corpus's similarity cutoff for the method used.
        With require_neural, nothing is returned unless the neural meaning model answered: on a corpus this small,
        TF-IDF scores unrelated questions as high as related ones."""
        from corpus_vector_store import TFIDF, min_similarity

        self.sync()
        found = self.store.semantic_search(query, top_k=top_k)
        if require_neural and any(r["method"] == TFIDF for r in found):
            return []
        return [r for r in found if r["similarity"] >= min_similarity(r["method"])]

    def status(self) -> dict:
        current = collect(self.root, self.dirs)
        files = sorted({s["path"] for s in current})
        vectors = sum(1 for d in self.store.documents if d["id"] in self.store.vectors)
        return {"files": files, "sections": len(current), "indexed": len(self.store.documents), "vectors": vectors,
                "method": self.store.method(), "fingerprint": fingerprint(current),
                "embed_error": self.store.last_error, "rebuilt": self.rebuilt}


# -- the private Hugging Face dataset ------------------------------------------------------------------------
def to_parquet(items: list[dict], version: str) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema([("id", pa.string()), ("path", pa.string()), ("title", pa.string()), ("heading", pa.string()),
                        ("text", pa.string()), ("sha256", pa.string()), ("urls", pa.list_(pa.string())),
                        ("version", pa.string())])
    rows = [{"id": s["id"], "path": s["path"], "title": s["title"], "heading": s["heading"], "text": s["text"],
             "sha256": s["sha256"], "urls": s["urls"], "version": version} for s in items]
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), buffer, compression="zstd")
    return buffer.getvalue()


def manifest(items: list[dict]) -> dict:
    return {"schema": "rabbitsoft-knowledge.v1", "fingerprint": fingerprint(items), "sections": len(items),
            "files": sorted({s["path"] for s in items}),
            "items": [{"id": s["id"], "sha256": s["sha256"]} for s in sorted(items, key=lambda s: s["id"])]}


def remote_fingerprint(hub, repo: str) -> str | None:
    """The fingerprint of the version on Hugging Face, or None if there's no dataset or no manifest yet."""
    if not hub.repo_exists(repo, repo_type="dataset"):
        return None
    if "manifest.json" not in hub.list_repo_files(repo, repo_type="dataset"):
        return ""
    path = hub.hf_hub_download(repo, "manifest.json", repo_type="dataset")
    return json.loads(Path(path).read_text(encoding="utf-8")).get("fingerprint", "")


def publish(root: Path, hub=None, ask=input, repo: str | None = None, log=None,
            dirs: tuple[str, ...] = ("docs/research",)) -> dict:
    """One publish run. Returns what happened; raises on a Hugging Face error.

    Only reports git tracks are published: committed reports have been through review, and a local draft (or
    anything else dropped into docs/research/) never leaves the PC by accident."""
    tracked = tracked_files(Path(root), dirs)
    if tracked is None:
        raise RuntimeError("git can't list the tracked reports here, so nothing is published")
    items = collect(Path(root), dirs, only=tracked)
    if not items:
        return {"published": False, "message": "No committed research reports in docs/research/ to publish."}
    local = fingerprint(items)
    data, meta = to_parquet(items, local), manifest(items)          # built first: a failure here touches nothing
    if hub is None:
        from huggingface_hub import HfApi
        hub = HfApi()
    repo = repo or f"{hub.whoami()['name']}/{DATASET_REPO}"
    remote = remote_fingerprint(hub, repo)
    if remote is not None and not hub.repo_info(repo, repo_type="dataset").private:
        raise RuntimeError(f"{repo} is public; the knowledge base only goes to a private dataset")
    if remote == local:
        return {"published": False, "fingerprint": local,
                "message": f"{repo} already has this version ({local[:12]}); nothing to upload."}
    files = sorted({s["path"] for s in items})
    action = "Create the PRIVATE dataset" if remote is None else "Update the private dataset"
    question = (f"{action} {repo} with {len(items)} sections from {len(files)} committed research reports "
                f"(version {local[:12]})? (yes/no) ")
    if ask(question).strip().lower() not in ("y", "yes"):
        return {"published": False, "message": "Nothing was uploaded."}
    from huggingface_hub import CommitOperationAdd

    if remote is None:
        hub.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    commit = hub.create_commit(                    # one commit: the data, manifest and card change together
        repo_id=repo, repo_type="dataset", commit_message=f"Knowledge base {local[:12]}: {len(items)} sections",
        operations=[CommitOperationAdd(path_in_repo="data/knowledge.parquet", path_or_fileobj=data),
                    CommitOperationAdd(path_in_repo="manifest.json",
                                       path_or_fileobj=json.dumps(meta, indent=1).encode("utf-8")),
                    CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=CARD.read_bytes())])
    oid = str(getattr(commit, "oid", "") or "")
    result = {"published": True, "repo": repo, "fingerprint": local, "sections": len(items), "files": len(files),
              "commit": oid, "parquet_sha256": hashlib.sha256(data).hexdigest(),
              "message": f"Published {len(items)} sections from {len(files)} reports to {repo} "
                         f"(version {local[:12]}, commit {oid[:10]})."}
    if log:
        log("knowledge_published", {k: result[k] for k in ("repo", "fingerprint", "sections", "commit", "parquet_sha256")})
    return result
