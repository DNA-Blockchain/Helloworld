"""Public abstracts for research records already saved in the catalog.

Searches save titles only; answering and search-by-meaning work much better with the abstract. This asks
each public source for the abstracts of records it already returned, sending only their record IDs
(PMIDs, project numbers, NCT numbers) -- never a question, a name or anything personal.

    python research_abstracts.py        # fills in every saved record that has no abstract yet
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError

from public_variant_sources import NCBI_EFETCH, SSL_CONTEXT, USER_AGENT, _ncbi_prepare

EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
NIH_REPORTER_SEARCH = "https://api.reporter.nih.gov/v2/projects/search"
CLINICALTRIALS_STUDIES = "https://clinicaltrials.gov/api/v2/studies"
SOURCE_NAMES = {"pubmed": "PubMed", "europe_pmc": "Europe PMC", "nih_reporter": "NIH RePORTER",
                "clinicaltrials.gov": "ClinicalTrials.gov"}
MAX_ABSTRACT_CHARS = 6000
BATCH = 40


def _request(url: str, payload: dict | None = None, accept: str = "application/json") -> bytes:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    host = urllib.parse.urlsplit(url).hostname
    try:
        with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
            return response.read(8 * 1024 * 1024)
    except HTTPError as error:
        raise RuntimeError(f"{host} returned HTTP {error.code}") from None
    except (URLError, OSError, TimeoutError) as error:
        raise RuntimeError(f"request to {host} failed ({type(error).__name__})") from None


def _clean(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:MAX_ABSTRACT_CHARS]


def _batches(ids: list[str]) -> Iterable[list[str]]:
    for i in range(0, len(ids), BATCH):
        yield ids[i:i + BATCH]


def fetch_pubmed(pmids: list[str]) -> dict[str, str]:
    found = {}
    for batch in _batches(pmids):
        params = _ncbi_prepare({"db": "pubmed", "id": ",".join(batch), "retmode": "xml"})
        root = ET.fromstring(_request(f"{NCBI_EFETCH}?{urllib.parse.urlencode(params)}", accept="text/xml"))
        for article in root.iter("PubmedArticle"):
            pmid = article.findtext("MedlineCitation/PMID")
            parts = [" ".join(p.itertext()) for p in article.iter("AbstractText")]
            if pmid and parts:
                found[pmid] = _clean(" ".join(parts))
    return found


def fetch_europepmc(ids: list[str]) -> dict[str, str]:
    found = {}
    for batch in _batches(ids):
        params = {"query": " OR ".join(f"EXT_ID:{i}" for i in batch), "resultType": "core", "format": "json",
                  "pageSize": str(len(batch) * 2)}
        data = json.loads(_request(f"{EUROPEPMC_SEARCH}?{urllib.parse.urlencode(params)}"))
        for record in data.get("resultList", {}).get("result", []):
            if record.get("id") in batch and record.get("abstractText"):
                found[record["id"]] = _clean(record["abstractText"])
    return found


def fetch_nih_reporter(project_numbers: list[str]) -> dict[str, str]:
    found = {}
    for batch in _batches(project_numbers):
        data = json.loads(_request(NIH_REPORTER_SEARCH, {
            "criteria": {"project_nums": batch}, "include_fields": ["ProjectNum", "AbstractText"],
            "limit": len(batch) * 5}))
        for project in data.get("results", []):
            if project.get("project_num") in batch and project.get("abstract_text"):
                found[project["project_num"]] = _clean(project["abstract_text"])
    return found


def fetch_clinicaltrials(nct_ids: list[str]) -> dict[str, str]:
    found = {}
    for batch in _batches(nct_ids):
        params = {"filter.ids": ",".join(batch), "fields": "NCTId,BriefSummary", "pageSize": str(len(batch))}
        data = json.loads(_request(f"{CLINICALTRIALS_STUDIES}?{urllib.parse.urlencode(params)}"))
        for study in data.get("studies", []):
            section = study.get("protocolSection", {})
            nct = section.get("identificationModule", {}).get("nctId")
            summary = section.get("descriptionModule", {}).get("briefSummary")
            if nct and summary:
                found[nct] = _clean(summary)
    return found


FETCHERS: dict[str, Callable[[list[str]], dict[str, str]]] = {
    "pubmed": fetch_pubmed, "europe_pmc": fetch_europepmc, "nih_reporter": fetch_nih_reporter,
    "clinicaltrials.gov": fetch_clinicaltrials,
}


def fill_missing_abstracts(catalog, fetchers: dict | None = None, limit: int = 200) -> dict:
    """Asks each source for the abstracts of its saved records that have none. A source that fails is
    reported and skipped; the rest still fill in."""
    fetchers = FETCHERS if fetchers is None else fetchers
    by_source: dict[str, list[str]] = {}
    for source, external_id in catalog.missing_abstracts(limit=limit):
        if source in fetchers:
            by_source.setdefault(source, []).append(external_id)
    filled, failed = 0, {}
    for source, ids in by_source.items():
        try:
            abstracts = fetchers[source](ids)
        except (RuntimeError, ValueError, ET.ParseError) as error:
            failed[source] = str(error)
            continue
        filled += sum(catalog.set_abstract(source, i, text) for i, text in abstracts.items() if text)
    return {"asked": sum(len(ids) for ids in by_source.values()), "filled": filled,
            "sources": sorted(by_source), "failed": failed}


if __name__ == "__main__":
    from research_catalog import ResearchCatalog

    result = fill_missing_abstracts(ResearchCatalog())
    print(f"Asked for {result['asked']} abstracts from {', '.join(SOURCE_NAMES[s] for s in result['sources']) or 'no sources'};"
          f" filled in {result['filled']}.")
    for source, error in result["failed"].items():
        print(f"  {SOURCE_NAMES[source]} didn't answer: {error}")
