import json

import research_abstracts
from research_abstracts import fill_missing_abstracts
from research_catalog import ResearchCatalog


def _catalog(tmp_path):
    catalog = ResearchCatalog(tmp_path / "catalog.sqlite3")
    catalog.add_records([
        {"source": "pubmed", "external_id": "1", "title": "One", "source_url": "https://x/1", "classification": "public"},
        {"source": "nih_reporter", "external_id": "R01-2", "title": "Two", "source_url": "https://x/2",
         "classification": "public"},
        {"source": "pubmed", "external_id": "3", "title": "Three", "abstract": "Already here.",
         "source_url": "https://x/3", "classification": "public"},
        {"source": "pubmed", "external_id": "4", "title": "Private", "source_url": "https://x/4",
         "classification": "private"},
    ])
    return catalog


def test_missing_abstracts_are_filled_and_a_failing_source_is_reported(tmp_path):
    catalog = _catalog(tmp_path)
    assert catalog.missing_abstracts() == [("pubmed", "1"), ("nih_reporter", "R01-2")]   # public ones only
    asked = {}

    def pubmed(ids):
        asked["pubmed"] = ids
        return {"1": "What paper one found."}

    def nih(ids):
        raise RuntimeError("api.reporter.nih.gov returned HTTP 503")

    result = fill_missing_abstracts(catalog, fetchers={"pubmed": pubmed, "nih_reporter": nih})
    assert asked == {"pubmed": ["1"]} and result["filled"] == 1 and result["asked"] == 2
    assert result["failed"] == {"nih_reporter": "api.reporter.nih.gov returned HTTP 503"}
    assert catalog.missing_abstracts() == [("nih_reporter", "R01-2")]
    assert {r["external_id"]: r["abstract"] for r in catalog.all_records()}["1"] == "What paper one found."


def test_each_source_reply_is_read_correctly(monkeypatch):
    replies = {
        "eutils": b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>11</PMID><Article><Abstract>
            <AbstractText Label="BACKGROUND">Why it <i>matters</i>.</AbstractText>
            <AbstractText Label="RESULTS">What &amp; how.</AbstractText></Abstract></Article></MedlineCitation>
            </PubmedArticle></PubmedArticleSet>""",
        "ebi.ac.uk": json.dumps({"resultList": {"result": [{"id": "22", "abstractText": "<h4>Aim</h4>Find it."},
                                                           {"id": "99", "abstractText": "Not asked for."}]}}).encode(),
        "reporter": json.dumps({"results": [{"project_num": "R01-3", "abstract_text": "  Project   aims. "}]}).encode(),
        "clinicaltrials": json.dumps({"studies": [{"protocolSection": {
            "identificationModule": {"nctId": "NCT4"}, "descriptionModule": {"briefSummary": "A trial."}}}]}).encode(),
    }
    sent = []

    def fake_request(url, payload=None, accept="application/json"):
        sent.append((url, payload))
        return next(body for key, body in replies.items() if key in url)

    monkeypatch.setattr(research_abstracts, "_request", fake_request)
    monkeypatch.setattr(research_abstracts, "_ncbi_prepare", lambda params: params)
    assert research_abstracts.fetch_pubmed(["11"]) == {"11": "Why it matters . What & how."}
    assert research_abstracts.fetch_europepmc(["22"]) == {"22": "Aim Find it."}
    assert research_abstracts.fetch_nih_reporter(["R01-3"]) == {"R01-3": "Project aims."}
    assert research_abstracts.fetch_clinicaltrials(["NCT4"]) == {"NCT4": "A trial."}
    assert sent[2][1]["criteria"] == {"project_nums": ["R01-3"]}     # only record numbers are sent
