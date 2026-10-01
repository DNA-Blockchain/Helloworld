"""
corpus_vector_store.py
================
Search by meaning over the public research this PC has saved: every record in the research catalog
(title plus abstract) becomes a vector, and a question is matched to the records whose vectors point the
same way (cosine similarity) -- so "blood cancer immune therapy" finds "CAR T-cell therapy in B-cell
leukemia" even though they share almost no words.

TWO WAYS TO MAKE THE VECTORS
----------------------------------
- A local neural embedding model through Ollama (nomic-embed-text, about 270 MB, runs on this PC).
  This understands meaning: it knows "heart tumor" and "cardiac neoplasm" are the same idea. Each
  record is embedded once; its vector is kept with the corpus and only redone if its text changes.
- TF-IDF (term frequency / inverse document frequency), used until that model is downloaded or when
  Ollama isn't running. A real vector-search method, but it matches shared vocabulary, not meaning.

Which one answered is part of every result ("method"), so it's never unclear what did the matching.

WHAT'S IN IT
----------------
Public records only (the catalog's "public" classification) -- the same records anyone can fetch, so
the corpus holds nothing personal. Personal data belongs in the digital twin's encrypted vault, not here.

Usage
-----
    from corpus_vector_store import CorpusVectorStore, OllamaEmbedder
    from research_catalog import ResearchCatalog

    store = CorpusVectorStore(store_path="dna_shell_data/corpus_vectors.json", embedder=OllamaEmbedder())
    store.sync_from_catalog(ResearchCatalog())
    results = store.semantic_search("immune cell therapy for blood cancer", top_k=5)
"""

from __future__ import annotations
import hashlib
import json
import os
import urllib.request
from urllib.error import URLError

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

IDENTITY = "rabbitsoftware-public-research"
EMBED_MODEL = "nomic-embed-text"
OLLAMA_HOST = "http://127.0.0.1:11434"
TFIDF = "tfidf"
# Below these, a match shares too little with the question to answer from. The two methods score on
# different scales: TF-IDF only counts shared words, neural embeddings of any two sentences are somewhat alike.
# With nomic-embed-text on the real catalog, related questions scored 0.72-0.83 and unrelated ones up to 0.55.
MIN_SIMILARITY = {TFIDF: 0.12, "neural": 0.62}


class OllamaEmbedder:
    """A local embedding model served by Ollama. nomic-embed-text wants its inputs marked as a document
    or a query; other models just get the text."""

    def __init__(self, model: str = EMBED_MODEL, host: str = OLLAMA_HOST, timeout: float = 120):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._prefix = self.model.startswith("nomic-embed")

    def _post(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(f"{self.host}{path}", data=data,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def available(self) -> bool:
        try:
            names = [m.get("name", "") for m in self._post("/api/tags").get("models", [])]
        except (URLError, OSError, ValueError):
            return False
        return any(n == self.model or n.startswith(f"{self.model}:") for n in names)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._post("/api/embed", {"model": self.model, "input": texts}).get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError("the embedding model returned the wrong number of vectors")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed([f"search_document: {t}" if self._prefix else t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([f"search_query: {text}" if self._prefix else text])[0]


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CorpusVectorStore:
    def __init__(self, identity: str = IDENTITY, store_path: str | None = None, embedder=None):
        self.identity = identity
        self.store_path = store_path
        self.embedder = embedder
        self.documents: list[dict] = []           # [{"id", "text", "source", "record_id", "title", "url", ...}]
        self.vectors: dict[str, dict] = {}        # id -> {"model", "text_sha256", "vector"}
        self.last_error = ""                      # why the neural model wasn't used, if it wasn't
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None

        if store_path and os.path.exists(store_path):
            self._load()

    def _load(self):
        with open(self.store_path, encoding="utf-8") as f:
            state = json.load(f)
        if state.get("identity") != self.identity:
            raise ValueError(
                f"Store at {self.store_path} belongs to identity '{state.get('identity')}', "
                f"not '{self.identity}' — each identity should use its own store_path."
            )
        self.documents = state["documents"]
        self.vectors = state.get("vectors", {})
        self._refit()

    def _save(self):
        if not self.store_path:
            return
        state = {"identity": self.identity, "documents": self.documents, "vectors": self.vectors}
        os.makedirs(os.path.dirname(os.path.abspath(self.store_path)), exist_ok=True)
        tmp_path = self.store_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp_path, self.store_path)

    def _refit(self):
        """TF-IDF needs the full vocabulary, so it refits on every change.
        Fine up to a few thousand documents; if this corpus grows much
        larger than that, this is the first thing worth optimizing."""
        if not self.documents:
            self._vectorizer = None
            self._matrix = None
            return
        texts = [d["text"] for d in self.documents]
        self._vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        self._matrix = self._vectorizer.fit_transform(texts)

    # -- neural vectors -------------------------------------------------------------------------------
    def _stale(self) -> list[dict]:
        model = self.embedder.model
        return [d for d in self.documents if (v := self.vectors.get(d["id"])) is None
                or v["model"] != model or v["text_sha256"] != _text_sha(d["text"])]

    def embed_missing(self, batch: int = 16) -> int:
        """Embeds every document without a current vector from the neural model. Returns how many were
        embedded; on failure, stops, keeps what's done and leaves the reason in last_error."""
        if self.embedder is None:
            return 0
        done = 0
        stale = self._stale()
        try:
            for i in range(0, len(stale), batch):
                chunk = stale[i:i + batch]
                for doc, vector in zip(chunk, self.embedder.embed_documents([d["text"] for d in chunk])):
                    self.vectors[doc["id"]] = {"model": self.embedder.model, "text_sha256": _text_sha(doc["text"]),
                                               "vector": [round(float(x), 6) for x in vector]}
                    done += 1
            self.last_error = ""
        except (URLError, OSError, ValueError) as error:
            self.last_error = f"{type(error).__name__}: {error}"
        if done:
            self._save()
        return done

    def method(self) -> str:
        """The neural model's name once every document has a current vector from it, else "tfidf"."""
        if self.embedder is not None and self.documents and not self._stale():
            return self.embedder.model
        return TFIDF

    # -- documents ----------------------------------------------------------------------------------
    def add_documents(self, new_docs: list[dict]) -> int:
        """Adds new documents and updates ones whose text changed (a record gains its abstract later).
        Returns how many were added or changed; adding the same record twice is a no-op."""
        index = {d["id"]: i for i, d in enumerate(self.documents)}
        changed = 0
        for doc in new_docs:
            if not doc.get("text"):
                continue
            if doc["id"] not in index:
                index[doc["id"]] = len(self.documents)
                self.documents.append(doc)
                changed += 1
            elif self.documents[index[doc["id"]]] != doc:
                self.documents[index[doc["id"]]] = doc
                changed += 1
        if changed:
            self._refit()
            self._save()
        return changed

    def sync_from_catalog(self, catalog) -> int:
        """Brings the corpus up to date with the catalog's public records, then embeds whatever's new."""
        changed = self.add_documents([document_from_record(r) for r in catalog.all_records()])
        self.embed_missing()
        return changed

    # -- search -------------------------------------------------------------------------------------
    def semantic_search(self, query: str, top_k: int = 5) -> list[dict]:
        if not self.documents or self._vectorizer is None:
            return []
        method = self.method()
        if method != TFIDF:
            try:
                query_vec = np.array([self.embedder.embed_query(query)])
                matrix = np.array([self.vectors[d["id"]]["vector"] for d in self.documents])
                similarities = cosine_similarity(query_vec, matrix)[0]
            except (URLError, OSError, ValueError) as error:
                self.last_error = f"{type(error).__name__}: {error}"
                method = TFIDF
        if method == TFIDF:
            similarities = cosine_similarity(self._vectorizer.transform([query]), self._matrix)[0]
        ranked = sorted(zip(self.documents, similarities), key=lambda x: -x[1])
        return [{**doc, "similarity": round(float(sim), 4), "method": method}
                for doc, sim in ranked[:top_k] if sim > 0]

    def find_similar(self, doc_id: str, top_k: int = 5) -> list[dict]:
        idx = next((i for i, d in enumerate(self.documents) if d["id"] == doc_id), None)
        if idx is None or self._matrix is None:
            return []
        similarities = cosine_similarity(self._matrix[idx], self._matrix)[0]
        ranked = sorted(
            [(d, s) for i, (d, s) in enumerate(zip(self.documents, similarities)) if i != idx],
            key=lambda x: -x[1],
        )
        return [{**doc, "similarity": round(float(sim), 4)} for doc, sim in ranked[:top_k] if sim > 0]

    def __len__(self):
        return len(self.documents)


def min_similarity(method: str) -> float:
    return MIN_SIMILARITY[TFIDF if method == TFIDF else "neural"]


def document_from_record(record: dict) -> dict:
    """A catalog record as a corpus document: its title and abstract are the text that gets a vector."""
    text = record["title"].strip()
    if record.get("abstract"):
        text = f"{text}. {record['abstract'].strip()}"
    return {"id": f"{record['source']}:{record['external_id']}", "text": text, "source": record["source"],
            "record_id": record["external_id"], "title": record["title"], "url": record["source_url"],
            "published_at": record.get("published_at") or "", "abstract": record.get("abstract") or ""}


if __name__ == "__main__":
    from research_catalog import ResearchCatalog

    embedder = OllamaEmbedder()
    store = CorpusVectorStore(store_path=os.path.join("dna_shell_data", "corpus_vectors.json"),
                              embedder=embedder if embedder.available() else None)
    changed = store.sync_from_catalog(ResearchCatalog())
    print(f"Corpus: {len(store)} public records ({changed} new or changed); vectors by {store.method()}.")
    if store.embedder is None:
        print(f"For search by meaning, download the local model once: ollama pull {EMBED_MODEL}")
    for query in ("immune cell therapy for blood cancer", "gene editing to treat sickle cell disease"):
        print(f"\nQuery: '{query}'")
        for r in store.semantic_search(query, top_k=3):
            print(f"  {r['similarity']:.3f}  [{r['source']}]  {r['title']}")
