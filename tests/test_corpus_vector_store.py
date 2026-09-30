import pytest

from corpus_vector_store import TFIDF, CorpusVectorStore, document_from_record, min_similarity

# Words that mean the same idea share a dimension, the way a real embedding model places synonyms together.
CONCEPTS = [{"heart", "cardiac"}, {"tumor", "neoplasm", "cancer"}, {"sickle", "hemoglobin"}, {"blood", "leukemia"},
            {"immune", "car", "t-cell"}]


class FakeEmbedder:
    model = "fake-embed"

    def __init__(self):
        self.embedded = []
        self.broken = False

    def _vector(self, text):
        words = set(text.lower().replace(".", " ").split())
        return [0.01] + [float(len(words & c)) for c in CONCEPTS]

    def embed_documents(self, texts):
        if self.broken:
            raise OSError("model not answering")
        self.embedded += texts
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        if self.broken:
            raise OSError("model not answering")
        return self._vector(text)


DOCS = [{"id": "pubmed:1", "text": "Cardiac neoplasm outcomes after surgery"},
        {"id": "pubmed:2", "text": "Base editing for sickle cell disease"},
        {"id": "pubmed:3", "text": "CAR T-cell therapy in pediatric leukemia"}]


def test_word_matching_finds_shared_words_and_updates_changed_records(tmp_path):
    store = CorpusVectorStore(store_path=str(tmp_path / "corpus.json"))
    assert store.add_documents(DOCS) == 3 and store.add_documents(DOCS) == 0
    assert store.method() == TFIDF
    results = store.semantic_search("sickle cell editing")
    assert results[0]["id"] == "pubmed:2" and results[0]["method"] == TFIDF
    assert store.semantic_search("heart tumor") == []            # no shared words: TF-IDF can't see it

    changed = {**DOCS[1], "text": DOCS[1]["text"] + ". Fetal hemoglobin rose."}
    assert store.add_documents([changed]) == 1 and len(store) == 3
    assert CorpusVectorStore(store_path=str(tmp_path / "corpus.json")).documents[1]["text"].endswith("rose.")


def test_the_meaning_model_finds_synonyms_and_embeds_each_record_once(tmp_path):
    embedder = FakeEmbedder()
    store = CorpusVectorStore(store_path=str(tmp_path / "corpus.json"), embedder=embedder)
    store.add_documents(DOCS)
    assert store.method() == TFIDF                    # not every record has a vector yet
    assert store.embed_missing() == 3 and store.method() == "fake-embed"
    top = store.semantic_search("heart tumor", top_k=1)[0]
    assert top["id"] == "pubmed:1" and top["method"] == "fake-embed"
    assert top["similarity"] >= min_similarity("fake-embed")

    reopened = CorpusVectorStore(store_path=str(tmp_path / "corpus.json"), embedder=embedder)
    assert reopened.embed_missing() == 0 and len(embedder.embedded) == 3     # vectors were kept on disk
    reopened.add_documents([{**DOCS[0], "text": DOCS[0]["text"] + ". Cardiac surgery."}])
    assert reopened.embed_missing() == 1                                     # only the changed record


def test_a_model_that_stops_answering_falls_back_to_word_matching(tmp_path):
    embedder = FakeEmbedder()
    store = CorpusVectorStore(embedder=embedder)
    store.add_documents(DOCS)
    store.embed_missing()
    embedder.broken = True
    results = store.semantic_search("sickle cell")
    assert results[0]["id"] == "pubmed:2" and results[0]["method"] == TFIDF
    assert "model not answering" in store.last_error


def test_a_corpus_belongs_to_one_identity(tmp_path):
    CorpusVectorStore(identity="a", store_path=str(tmp_path / "c.json")).add_documents(DOCS)
    with pytest.raises(ValueError, match="belongs to identity 'a'"):
        CorpusVectorStore(identity="b", store_path=str(tmp_path / "c.json"))


def test_a_catalog_record_becomes_a_document_with_its_abstract():
    doc = document_from_record({"source": "pubmed", "external_id": "7", "title": "A title",
                                "abstract": "What it found.", "source_url": "https://x/7", "published_at": "2026"})
    assert doc["id"] == "pubmed:7" and doc["text"] == "A title. What it found." and doc["url"] == "https://x/7"
