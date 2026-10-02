"""Portable research records: citation metadata in the catalog, exports to BibTeX, RIS, CSV and JSONL,
the citation backfill, and the provenance format those exports carry."""
import csv
import io
import re
import json
import time

import pytest

from rabbitsoft import contracts
from research_catalog import ResearchCatalog, author_list, citation_fields, normalize_record
import research_export as ex

ARTICLE = {
    "source": "pubmed", "external_id": "42789486", "classification": "public",
    "title": "Pure Red Cell Aplasia Following Neoadjuvant Therapy",
    "abstract": "A case report.\nWith a newline.", "source_url": "https://pubmed.ncbi.nlm.nih.gov/42789486/",
    "published_at": "2026 Sep 25", "authors": ["Chen Y", "Chen F", "Luo R"],
    "container": "The American journal of case reports", "volume": "27", "pages": "e952933",
    "doi": "doi: 10.12659/AJCR.952933", "record_type": "article",
    "rights_status": "unknown; review source and record terms",
    "terms_url": "https://www.ncbi.nlm.nih.gov/home/about/policies/", "retrieved_at": 1790931234.5678,
}
TRIAL = {"source": "clinicaltrials.gov", "external_id": "NCT03078036", "classification": "public",
         "title": "A breast cancer study", "source_url": "https://clinicaltrials.gov/study/NCT03078036",
         "published_at": "2017-03-13", "publisher": "AstraZeneca", "record_type": "clinical_trial",
         "rights_status": "public domain", "terms_url": "https://clinicaltrials.gov/about-site/terms-conditions"}


def catalog(tmp_path, records=(ARTICLE, TRIAL)):
    cat = ResearchCatalog(tmp_path / "catalog.sqlite3")
    cat.add_records(list(records))
    return cat


# -- citation metadata in the record and the catalog ---------------------------------------------------
def test_citation_fields_are_normalized_and_optional():
    fields = citation_fields(ARTICLE)
    assert json.loads(fields["authors"]) == ["Chen Y", "Chen F", "Luo R"]
    assert fields["doi"] == "10.12659/AJCR.952933"                      # the "doi: " prefix is stripped
    assert citation_fields({"doi": "https://doi.org/10.1/x"})["doi"] == "10.1/x"
    assert citation_fields({"authors": "Pal B; Anderson RL"})["authors"] == '["Pal B", "Anderson RL"]'
    empty = citation_fields({})
    assert empty["authors"] == "" and empty["container"] == "" and empty["record_type"] == ""
    with pytest.raises(ValueError, match="record_type must be one of"):
        citation_fields({"record_type": "manuscript"})
    # A record with no citation metadata still normalizes, as before.
    plain = normalize_record({"source": "pubmed", "external_id": "1", "title": "t",
                              "source_url": "https://x/1", "classification": "public"})
    assert plain["authors"] == "" and author_list(plain) == []


def test_the_catalog_stores_citation_fields_and_never_loses_one(tmp_path):
    cat = catalog(tmp_path)
    [article] = [r for r in cat.all_records() if r["source"] == "pubmed"]
    assert author_list(article) == ["Chen Y", "Chen F", "Luo R"] and article["volume"] == "27"
    assert article["classification"] == "public" and article["retrieved_at"] > 0
    # Retrieving the same record later without citation fields must not blank the ones we have.
    cat.add_records([{k: v for k, v in ARTICLE.items()
                      if k not in ("authors", "container", "volume", "pages", "doi")}])
    [again] = [r for r in cat.all_records() if r["source"] == "pubmed"]
    assert author_list(again) == ["Chen Y", "Chen F", "Luo R"] and again["doi"] == "10.12659/AJCR.952933"
    # And a query-filtered retrieval carries them too.
    found = ex.select(cat, query="aplasia")
    assert author_list(found[0]) and found[0]["retrieved_at"] > 0


def test_an_existing_catalog_without_the_columns_is_migrated(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:            # the schema as it was before citation fields existed
        db.execute("""CREATE TABLE research_records (record_key TEXT PRIMARY KEY, source TEXT NOT NULL,
                   external_id TEXT NOT NULL, title TEXT NOT NULL, abstract TEXT NOT NULL DEFAULT '',
                   source_url TEXT NOT NULL, published_at TEXT NOT NULL DEFAULT '',
                   retrieved_at REAL NOT NULL, classification TEXT NOT NULL CHECK (
                   classification IN ('public', 'restricted', 'private')), rights_status TEXT NOT NULL,
                   terms_url TEXT NOT NULL)""")
        db.execute("INSERT INTO research_records VALUES ('k', 'pubmed', '7', 'An older record', '', "
                   "'https://pubmed.ncbi.nlm.nih.gov/7/', '2019', 1700000000.0, 'public', 'unknown', '')")
    cat = ResearchCatalog(path)                  # opening it migrates in place
    [row] = cat.all_records()
    assert row["title"] == "An older record" and row["authors"] == "" and row["record_type"] == ""
    assert cat.set_citation("pubmed", "7", {"authors": ["Doe J"], "container": "Nature"})
    assert author_list(cat.all_records()[0]) == ["Doe J"]


# -- the four formats ----------------------------------------------------------------------------------
def test_bibtex_is_importable_and_escaped(tmp_path):
    text = ex.to_bibtex(catalog(tmp_path).all_records())
    assert text.count("@") == 2 and "@article{chen2026pubmed42789486," in text
    assert "author = {Chen Y and Chen F and Luo R}" in text        # BibTeX joins authors with " and "
    assert "journal = {The American journal of case reports}" in text and "doi = {10.12659/AJCR.952933}" in text
    assert "@misc{" in text and "howpublished = {AstraZeneca}" not in text   # a trial has no journal
    assert "url = {https://clinicaltrials.gov/study/NCT03078036}" in text
    assert r"europe\_pmc" not in text and "note = {Retrieved from pubmed (pubmed:42789486)" in text
    # Special characters are escaped, so the file still parses.
    tricky = ex.to_bibtex([{**ARTICLE, "title": "100% of {braces} & $math$ _and_ #hash"}])
    title = tricky.split("title = {", 1)[1].split("},\n", 1)[0]
    # Every special character in the value is escaped: none appears without a backslash before it.
    assert not re.search(r"(?<!\\)[%{}$&#_~^]", title), title
    assert r"100\%" in title and r"\{braces\}" in title and r"\&" in title and r"\$math\$" in title
    assert ex.to_bibtex([]) == ""


def test_ris_has_one_reference_per_record_ending_in_er(tmp_path):
    text = ex.to_ris(catalog(tmp_path).all_records())
    assert text.count("ER  - \n") == 2
    lines = text.splitlines()
    assert "TY  - JOUR" in lines and "AU  - Chen Y" in lines and "AU  - Chen F" in lines
    assert "JO  - The American journal of case reports" in lines and "DO  - 10.12659/AJCR.952933" in lines
    assert "DB  - pubmed" in lines and "AN  - 42789486" in lines      # the source and its own id
    assert "TY  - DBASE" in lines                                     # the clinical trial
    assert all("  - " in line for line in lines if line)              # every line is a valid RIS tag
    assert "\n" not in [l for l in lines if l.startswith("AB")][0][6:]   # the abstract was flattened


def test_csv_has_a_header_and_quotes_commas(tmp_path):
    rows = list(csv.DictReader(io.StringIO(ex.to_csv(catalog(tmp_path).all_records()))))
    assert len(rows) == 2 and list(rows[0]) == list(ex.CSV_COLUMNS)
    article = next(r for r in rows if r["source"] == "pubmed")
    assert article["authors"] == "Chen Y; Chen F; Luo R" and article["year"] == "2026"
    assert article["citation_key"] == "chen2026pubmed42789486" and article["record_type"] == "article"
    assert article["terms_url"] == ARTICLE["terms_url"] and "\n" not in article["abstract"]
    assert next(r for r in rows if r["source"] == "clinicaltrials.gov")["record_type"] == "clinical_trial"


def test_jsonl_keeps_authors_as_a_list_and_carries_provenance(tmp_path):
    rows = catalog(tmp_path).all_records()
    lines = ex.to_jsonl(rows, exported_at=1790934000.0, code_fingerprint="a" * 64).splitlines()
    assert len(lines) == 2
    row = json.loads(next(l for l in lines if '"pubmed"' in l))
    assert row["authors"] == ["Chen Y", "Chen F", "Luo R"] and row["year"] == "2026"
    p = row["provenance"]
    assert p["source_id"] == "pubmed:42789486" and p["exported_at"] == 1790934000.0
    stored = next(r for r in rows if r["source"] == "pubmed")
    assert p["retrieved_at"] == round(stored["retrieved_at"], 3) and p["code_fingerprint"] == "a" * 64
    assert p["terms_url"] and p["rights_status"]
    assert not contracts.errors(p, "provenance-v1", "recordProvenance")
    # Without a fingerprint the field is absent rather than empty.
    assert "code_fingerprint" not in json.loads(ex.to_jsonl([ARTICLE]).splitlines()[0])["provenance"]


def test_every_format_carries_the_source_id_and_url(tmp_path):
    records = catalog(tmp_path).all_records()
    for fmt in ex.FORMATS:
        text = ex.export(records, fmt)
        assert "42789486" in text and "https://pubmed.ncbi.nlm.nih.gov/42789486/" in text, fmt
        assert "NCT03078036" in text, fmt
    with pytest.raises(ValueError, match="format must be one of"):
        ex.export(records, "endnote")


def test_citation_keys_are_stable_and_distinct():
    assert ex.citation_key(ARTICLE) == ex.citation_key(dict(ARTICLE))      # same record, same key
    assert ex.citation_key(ARTICLE) != ex.citation_key({**ARTICLE, "external_id": "999"})
    assert ex.citation_key({"source": "x", "external_id": "1"}) == "x1"    # no author or year
    assert ex.citation_key({}) == "record"
    assert ex.year_of({"published_at": "2017-03-13"}) == "2017"
    assert ex.year_of({"published_at": "2026 Sep 25"}) == "2026"
    assert ex.year_of({"published_at": "n.d."}) == ""                      # no guessing
    assert ex.record_type_of({"source": "nih_reporter"}) == "grant"        # inferred for older records


# -- the citation backfill -----------------------------------------------------------------------------
def test_the_backfill_fills_missing_citations_and_skips_what_it_cannot_know(tmp_path):
    cat = ResearchCatalog(tmp_path / "c.sqlite3")
    cat.add_records([
        {"source": "pubmed", "external_id": "40000001", "title": "Older PubMed record",
         "source_url": "https://pubmed.ncbi.nlm.nih.gov/40000001/", "classification": "public"},
        {"source": "clinicaltrials.gov", "external_id": "NCT1", "title": "A trial",
         "source_url": "https://clinicaltrials.gov/study/NCT1", "classification": "public"},
        ARTICLE,                                             # already has citation fields
    ])
    assert sorted(cat.missing_citations()) == [("clinicaltrials.gov", "NCT1"), ("pubmed", "40000001")]

    def fake_summaries(pmids):
        assert pmids == ["40000001"]                          # only PMIDs are looked up
        return [{"pmid": "40000001", "authors": ["Chen Y"], "container": "A journal",
                 "doi": "10.1/x", "record_type": "article"}]

    result = ex.backfill_citations(cat, summaries=fake_summaries)
    assert result == {"checked": 2, "updated": 1, "skipped": 1, "not_found": 0}
    assert author_list(ex.select(cat, query="Older")[0]) == ["Chen Y"]
    assert cat.missing_citations() == [("clinicaltrials.gov", "NCT1")]    # never guessed at


def test_the_backfill_reports_a_source_failure_instead_of_losing_data(tmp_path):
    cat = ResearchCatalog(tmp_path / "c.sqlite3")
    cat.add_records([{"source": "pubmed", "external_id": "1", "title": "t",
                      "source_url": "https://pubmed.ncbi.nlm.nih.gov/1/", "classification": "public"}])
    messages = []

    def unreachable(pmids):
        raise OSError("the source is unreachable")

    result = ex.backfill_citations(cat, summaries=unreachable, log=messages.append)
    assert result["updated"] == 0 and "unreachable" in messages[0]
    assert cat.missing_citations() == [("pubmed", "1")]        # still marked as needing a backfill


# -- the command line ----------------------------------------------------------------------------------
def test_the_command_line_writes_a_file_and_refuses_an_empty_selection(tmp_path, capsys):
    cat = catalog(tmp_path)
    out = tmp_path / "refs.bib"
    assert ex.main(["--format", "bibtex", "--catalog", str(cat.path), "--out", str(out)]) == 0
    assert "@article{chen2026pubmed42789486" in out.read_text(encoding="utf-8")
    assert "2 record(s)" in capsys.readouterr().err
    assert ex.main(["--format", "csv", "--catalog", str(cat.path), "--source", "pubmed"]) == 0
    assert capsys.readouterr().out.count("\n") == 2                       # header plus one record
    assert ex.main(["--format", "csv", "--catalog", str(cat.path), "--query", "nothingmatchesthis"]) == 1
    assert "No records matched" in capsys.readouterr().err
    assert ex.main(["--format", "csv", "--catalog", str(tmp_path / "absent.sqlite3")]) == 1
    assert "No research catalog at" in capsys.readouterr().err


def test_exporting_records_that_are_not_public_warns(tmp_path):
    cat = ResearchCatalog(tmp_path / "c.sqlite3")
    cat.add_records([{**ARTICLE, "classification": "restricted"}])
    text = ex.export(cat.all_records(classification="restricted"), "csv")
    assert "42789486" in text
    assert "not classified public" in ex.NOT_PUBLIC_WARNING.format(n=1)


# -- the published provenance format -------------------------------------------------------------------
def test_the_provenance_schema_matches_what_the_project_really_writes(tmp_path):
    from audit_trail import AuditTrail

    entry = AuditTrail(str(tmp_path / "audit.jsonl")).log(
        "research_export", "records_exported", "local", {"count": 2, "format": "jsonl"})
    assert not contracts.errors(entry, "provenance-v1", "auditEntry")
    manifest = {"schema": "rabbitsoft-code.v1", "project": "RabbitSoftware", "version": "0.11.0",
                "commit": "a" * 40, "author": "A", "license": "UPL-1.0", "file_count": 1,
                "fingerprint": "b" * 64, "files": {"VERSION": "c" * 64}}
    assert not contracts.errors(manifest, "provenance-v1", "codeFingerprint")
    assert contracts.errors({**manifest, "files": [{"path": "VERSION", "sha256": "c" * 64}]},
                            "provenance-v1", "codeFingerprint")          # a list is not the real shape
    release = {"dataset": "depmap-crispr-gene-effect", "sha256": "d" * 64, "url": "https://depmap.org/",
               "license": "CC BY 4.0", "access": "open", "personal_data": False, "publishable": True}
    assert not contracts.errors(release, "provenance-v1", "datasetRelease")


def test_the_provenance_block_needs_its_source_and_time():
    block = ex.provenance_block(ARTICLE, exported_at=time.time())
    assert not contracts.errors(block, "provenance-v1", "recordProvenance")
    for missing in ("source", "source_id", "exported_at"):
        assert contracts.errors({k: v for k, v in block.items() if k != missing},
                                "provenance-v1", "recordProvenance"), missing
    assert contracts.errors({**block, "source_id": "no-colon"}, "provenance-v1", "recordProvenance")


def test_source_markup_is_cleaned_out_of_exports(tmp_path):
    """Sources put markup in titles: Europe PMC HTML-escapes its tags, PubMed sends them raw. Neither
    should reach a reference manager as angle brackets."""
    messy = {**ARTICLE, "title": "A &lt;i&gt;BRCA1&lt;/i&gt; study &amp; <sub>2</sub> more",
             "abstract": "line one\nline two", "container": "J <i>Onc</i>"}
    assert ex.plain_text(messy["title"]) == "A BRCA1 study & 2 more"
    assert ex.plain_text(None) == "" and ex.plain_text("  a   b ") == "a b"
    bib = ex.to_bibtex([messy])
    assert "BRCA1 study" in bib and "lt;i&gt" not in bib and "<sub>" not in bib
    assert r"\&" in bib                                   # the real ampersand is still escaped for BibTeX
    for text in (ex.to_ris([messy]), ex.to_csv([messy]), ex.to_jsonl([messy])):
        assert "&lt;" not in text and "<i>" not in text and "<sub>" not in text
    row = json.loads(ex.to_jsonl([messy]).splitlines()[0])
    assert row["title"] == "A BRCA1 study & 2 more" and row["container"] == "J Onc"
    assert "\n" not in row["abstract"]


def test_the_documented_commands_and_links_exist():
    """The docs promise specific commands and files; a promise that drifts is worse than none."""
    root = __import__("pathlib").Path(__file__).resolve().parent.parent
    for page in ("docs/integration.md", "docs/sources/README.md", "docs/api/provenance.md",
                 "docs/tutorials/literature-to-reference-manager.md", "examples/research/README.md"):
        assert (root / page).exists(), page
    readme = (root / "README.md").read_text(encoding="utf-8")
    for link in ("docs/integration.md", "docs/sources/README.md", "docs/api/provenance.md",
                 "docs/tutorials/literature-to-reference-manager.md", "examples/research/README.md"):
        assert link in readme, link
    # Every file the docs link to, relative to the page, resolves.
    import re
    for page in ("docs/integration.md", "docs/tutorials/literature-to-reference-manager.md",
                 "examples/research/README.md", "docs/sources/README.md", "docs/api/provenance.md"):
        text = (root / page).read_text(encoding="utf-8")
        for target in re.findall(r"\]\((\.\.?/[^)#]+)\)", text):
            assert ((root / page).parent / target).resolve().exists(), f"{page} -> {target}"
    # The flags the tutorial tells people to type really exist.
    tutorial = (root / "docs/tutorials/literature-to-reference-manager.md").read_text(encoding="utf-8")
    import rabbit
    with __import__("pytest").raises(SystemExit):
        rabbit.main(["export", "--help"])
    assert "--backfill" in tutorial and "--fingerprint" in tutorial
    assert "research-search" in tutorial and "--confirm-public-query" in tutorial


def test_the_documented_adapters_exist_where_the_docs_say():
    """docs/sources/ names a module and function per source. A doc that points at the wrong module sends
    a contributor hunting, so the claim is checked rather than trusted."""
    import importlib
    import re

    root = __import__("pathlib").Path(__file__).resolve().parent.parent
    page = (root / "docs" / "sources" / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"\|\s*\[`([a-z_]+\.py)`\]\([^)]+\)\s*`?(\w+)`?", page)
    assert len(rows) >= 5, rows
    for module_name, function in rows:
        module = importlib.import_module(module_name[:-3])
        assert hasattr(module, function), f"{module_name} has no {function}"
    # And the hint printed when there is no catalog must name a command that really fills one.
    import research_export
    source = (root / "research_export.py").read_text(encoding="utf-8")
    assert "research-search" in source and "research_fetch.py --help" not in source
