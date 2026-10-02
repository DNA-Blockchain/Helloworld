# Public data source adapters

One worked example per source: the exact request, the real response, how the record is attributed, and
what the adapter does when the source fails. Every response below was captured from a live call on
**2 October 2026**; where a figure would change by the day (a hit count) it is marked.

| Source | Adapter | Record type | Terms |
|---|---|---|---|
| PubMed | [`multi_source_research.py`](../../multi_source_research.py) `search_pubmed` | `article` | [NCBI policies](https://www.ncbi.nlm.nih.gov/home/about/policies/) |
| Europe PMC | [`extended_research_sources.py`](../../extended_research_sources.py) `search_europepmc` | `article`, `preprint` | [Europe PMC terms](https://europepmc.org/terms) |
| ClinicalTrials.gov | [`research_matcher.py`](../../research_matcher.py) `find_trials` | `clinical_trial` | [Terms and conditions](https://clinicaltrials.gov/about-site/terms-conditions) |
| ClinVar | [`public_variant_sources.py`](../../public_variant_sources.py) `search_ncbi_variants` | `variant` | [NCBI policies](https://www.ncbi.nlm.nih.gov/home/about/policies/) |
| NIH RePORTER | [`extended_research_sources.py`](../../extended_research_sources.py) `search_nih_grants` | `grant` | [RePORTER API terms](https://api.reporter.nih.gov/) |

Each adapter returns a plain dict. `research_catalog.search_public_sources` normalizes those into records
with `source`, `external_id`, `title`, `source_url`, `rights_status`, `terms_url` and the optional
citation fields, which [`research_export.py`](../../research_export.py) turns into BibTeX, RIS, CSV or
JSONL. The provenance those exports carry is specified in [docs/api/provenance.md](../api/provenance.md).

## Rules every adapter follows

1. **No key required.** All five work anonymously. An `NCBI_API_KEY` in the environment raises NCBI's
   rate limit; nothing breaks without it.
2. **Failure returns an empty list, never a fake record.** A search that cannot reach its source yields
   `[]` and the caller reports "that source failed", rather than presenting zero results as "nothing
   exists". `pubmed_summaries` is the deliberate exception: it raises, so a backfill can tell *not found*
   from *not reachable*.
3. **Attribution travels with the record.** `terms_url` is set per source, and `rights_status` is
   `"unknown; review source and record terms"` unless the source states otherwise. A guessed licence
   would be worse than an honest unknown.
4. **The source's own identifier is kept** (PMID, NCT number, VCV accession, project number) and paired
   with the source name, because neither half identifies a record alone.

---

## PubMed

NCBI E-utilities, two requests: `esearch` for IDs, then `esummary` for the records.

```bash
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=BRCA1+breast+cancer+remission&retmode=json&retmax=3"
```

```json
{"esearchresult": {"count": "49", "idlist": ["42789486", "42780989", "42301569"]}}
```

```bash
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id=42789486&retmode=json"
```

```json
{"result": {"42789486": {
  "title": "Pure Red Cell Aplasia Following Neoadjuvant Therapy...",
  "pubdate": "2026 Sep 25",
  "fulljournalname": "The American journal of case reports",
  "source": "Am J Case Rep", "volume": "27", "pages": "e952933",
  "authors": [{"name": "Chen Y", "authtype": "Author"}, {"name": "Chen F", "authtype": "Author"}],
  "elocationid": "doi: 10.12659/AJCR.952933",
  "articleids": [{"idtype": "pubmed", "value": "42789486"},
                 {"idtype": "doi", "value": "10.12659/AJCR.952933"}]
}}}
```

**What the adapter keeps:** `pmid`, `title`, `pub_date`, `url`, and for citations `authors` (only entries
whose `authtype` is `Author`, so a collective name isn't treated as a person), `container`
(`fulljournalname`, falling back to the abbreviation), `volume`, `issue`, `pages` and `doi` from
`articleids`. All of it comes from the response already being fetched: **no extra request** is made for
citation data.

**Attribution:** `source: pubmed`, `source_url: https://pubmed.ncbi.nlm.nih.gov/<pmid>/`,
`terms_url: https://www.ncbi.nlm.nih.gov/home/about/policies/`.

**Error handling and limits.** `search_pubmed` returns `[]` on any failure. Requests are spaced by
`_NCBI_MIN_INTERVAL_S` to respect NCBI's rate limit (3 requests/second anonymously, 10 with a key).
`esummary` takes at most 200 IDs per request, which `pubmed_summaries` enforces. An empty `idlist` means
no matches, which is not an error.

---

## Europe PMC

One request. The default `resultType=lite` already carries the citation fields.

```bash
curl "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=BRCA1%20breast%20cancer&format=json&pageSize=2"
```

```json
{"hitCount": 67830, "resultList": {"result": [{
  "id": "41563221", "source": "MED", "pmid": "41563221",
  "doi": "10.1016/j.jaccas.2025.106608",
  "title": "Heart Transplantation and Cancer Risk in a BRCA1 Breast Cancer Survivor.",
  "authorString": "Noteware L, Keller E, Lotan D, ...",
  "journalTitle": "JACC Case Rep", "journalVolume": "31", "issue": "8", "pageInfo": "106608",
  "pubYear": "2026", "isOpenAccess": "Y", "firstPublicationDate": "2026-04-15"
}]}}
```

(`hitCount` grows over time.)

**What the adapter keeps:** `id`, `title`, `pub_year`, `url`, plus `authors` (`authorString` is
**comma**-separated, so it is split on commas, not semicolons), `container` from `journalTitle`,
`volume`, `issue`, `pages` from `pageInfo`, and `doi`. A record whose `source` is `PPR` is typed
`preprint` rather than `article`.

**Why not `resultType=core`:** `core` returns the same fields nested under `journalInfo` plus abstracts
and reference lists, at about **nine times the bytes** (11,989 vs 1,333 for one record). `lite` has
everything the adapter uses.

**Attribution:** `source: europe_pmc`, URL to PubMed when a PMID is present (the same article), else the
DOI. `terms_url: https://europepmc.org/terms`. Europe PMC often states a licence per record
(`license: "cc by-nc-nd"`), which is worth reading before reuse.

**Error handling.** Returns `[]` on any failure. A query that matches nothing yields `hitCount: 0` and an
empty `result` list, which is not an error.

---

## ClinicalTrials.gov

API **v2**. The v1 API was retired in June 2024, so a v1 URL now fails.

```bash
curl "https://clinicaltrials.gov/api/v2/studies?query.term=BRCA1%20breast%20cancer&pageSize=2&format=json"
```

```json
{"studies": [{"protocolSection": {
  "identificationModule": {"nctId": "NCT03078036",
    "briefTitle": "International Breast Cancer Biomarker, Standard of Care and Real World ..."},
  "statusModule": {"overallStatus": "COMPLETED", "startDateStruct": {"date": "2017-03-13"}},
  "sponsorCollaboratorsModule": {"leadSponsor": {"name": "AstraZeneca"}}
}}]}
```

**What the adapter keeps:** `nct_id`, `title`, `status`, the start date as `published_at`, and the lead
sponsor as `publisher`. Exports type it `clinical_trial` (`@misc` in BibTeX, `DBASE` in RIS).

**Attribution:** `source: clinicaltrials.gov`,
`source_url: https://clinicaltrials.gov/study/<nctId>`, terms as above. Records are US government work
and generally free to reuse; the registry asks that it be credited as the source.

**Error handling and a gotcha.** Returns `[]` on failure. The response has **no total count**: there is
no `totalCount` key unless you ask for it with `countTotal=true`, so an adapter that reads one will get
`None`. Paging uses `nextPageToken`, not an offset.

---

## ClinVar

E-utilities again, `db=clinvar`.

```bash
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=clinvar&term=BRCA1%5Bgene%5D+AND+pathogenic&retmode=json&retmax=2"
curl "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=clinvar&id=4935332&retmode=json"
```

```json
{"result": {"4935332": {
  "accession": "VCV004935332",
  "title": "NM_007294.4(BRCA1):c.441+1G>T",
  "germline_classification": {"description": "Likely pathogenic",
                              "review_status": "criteria provided, single submitter"},
  "genes": [{"symbol": "BRCA1"}],
  "obj_type": "single nucleotide variant"
}}}
```

**What the adapter keeps:** the `accession` (`VCV…`) as the identifier, the variant name as the title,
and the classification with its **review status**, which matters: "criteria provided, single submitter"
is weaker evidence than "reviewed by expert panel", and a classification quoted without it misleads.

**Attribution:** `source: clinvar`, `source_url: https://www.ncbi.nlm.nih.gov/clinvar/variation/<uid>/`.
Every row is attributed to **ClinVar and its submitters**, never to this project.

**Error handling and a schema change.** Returns `[]` on failure. ClinVar renamed
`clinical_significance` to `germline_classification` (with `oncogenicity_classification` and
`clinical_impact_classification` added), so an adapter should read the new name and fall back to the old
one, which is what this one does.

---

## NIH RePORTER

A **POST** with a JSON body, unlike the four above.

```bash
curl -X POST "https://api.reporter.nih.gov/v2/projects/search" -H "Content-Type: application/json" \
  -d '{"criteria": {"advanced_text_search": {"operator": "and",
       "search_field": "projecttitle,terms", "search_text": "BRCA1 breast cancer"}}, "limit": 2}'
```

```json
{"meta": {"total": 5071}, "results": [{
  "project_num": "5R01CA279064-03", "fiscal_year": 2026,
  "project_title": "DNA damage-related stemness program during BRCA1 breast cancer initiation",
  "organization": {"org_name": "UNIVERSITY OF ALABAMA AT BIRMINGHAM"},
  "award_amount": 930464,
  "principal_investigators": [{"full_name": "..."}]
}]}
```

**⚠ The important gotcha: an unknown criteria key is silently ignored.** Verified on 2 October 2026:

| Request body | `meta.total` | Filtered? |
|---|---|---|
| `advanced_text_search` with `operator: and` | **5,071** | yes, results contain the terms |
| `text_search` (no such field) | 2,982,395 | **no** — every project in the database |
| `not_a_real_field` | 2,982,395 | **no** — identical |

A typo in a criteria name therefore returns a `200 OK` with millions of unrelated projects, which looks
like a successful search. Two defences, both worth copying: use `advanced_text_search` (what this
adapter does), and treat an implausibly large `meta.total` as a failed query rather than a result.

**What the adapter keeps:** `project_num`, `project_title`, `fiscal_year` as `published_at`, the
organization as `publisher`.
**Attribution:** `source: nih_reporter`,
`source_url: https://reporter.nih.gov/project-details/<project_num>`.

**Error handling.** Returns `[]` on failure. Some government certificate chains fail to verify on older
Python installs, which the adapter notes and handles explicitly rather than disabling verification
globally.

---

## Adding a source

1. Write a function returning a list of dicts, with `[]` on failure and no invented records.
2. Add it to `research_catalog.search_public_sources` and give it an entry in `SOURCE_TERMS`.
3. Add it to `research_analysis.PUBLIC_SOURCES` so nodes accept records from it.
4. Set `record_type` (and, for exports, `SOURCE_RECORD_TYPES` in `research_export.py`).
5. Add a test with a **fake** `urlopen` for the happy path and for failure. Tests must not hit the
   network; the captured responses above are enough to build a fixture.

A pull request adding a source is welcome, as is a correction to anything documented here: if you
maintain one of these APIs and something above is wrong or out of date, please
[open an issue](https://github.com/DNA-Blockchain/Helloworld/issues).
