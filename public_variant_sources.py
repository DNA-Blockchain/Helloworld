"""Public variant and gene lookup connectors used by the local research catalog."""

from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError

import certifi

NCBI_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
ENSEMBL_LOOKUP = "https://rest.ensembl.org/lookup/symbol/homo_sapiens/"
GNOMAD_GRAPHQL = "https://gnomad.broadinstitute.org/api"
USER_AGENT = "OpenResearchCatalog/1.0 (local research client)"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
MAX_SUMMARY_CHARS = 4000
_NCBI_LAST_REQUEST = 0.0


def _get_json(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20, context=SSL_CONTEXT) as response:
            data = json.loads(response.read())
    except HTTPError as error:
        host = urllib.parse.urlsplit(url).hostname or "NCBI"
        raise RuntimeError(f"research provider {host} returned HTTP {error.code}") from None
    except (URLError, OSError, TimeoutError) as error:
        host = urllib.parse.urlsplit(url).hostname or "research provider"
        raise RuntimeError(
            f"request to {host} failed ({type(error).__name__})"
        ) from None
    if not isinstance(data, dict):
        raise ValueError("research provider returned a non-object JSON response")
    return data


def _post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
            data = json.loads(response.read())
    except HTTPError as error:
        host = urllib.parse.urlsplit(url).hostname or "research provider"
        raise RuntimeError(f"research provider {host} returned HTTP {error.code}") from None
    except (URLError, OSError, TimeoutError) as error:
        host = urllib.parse.urlsplit(url).hostname or "research provider"
        raise RuntimeError(
            f"request to {host} failed ({type(error).__name__})"
        ) from None
    if not isinstance(data, dict):
        raise ValueError("research provider returned a non-object JSON response")
    return data


def _ncbi_prepare(params: dict[str, str]) -> dict[str, str]:
    """Wait out NCBI's request-rate guideline and add the optional API key."""
    now = time.monotonic()
    wait = 0.11 if os.environ.get("NCBI_API_KEY", "").strip() else 0.36
    delay = wait - (now - _NCBI_LAST_REQUEST)
    if delay > 0:
        time.sleep(delay)
    api_key = os.environ.get("NCBI_API_KEY", "").strip()
    request_params = dict(params)
    if api_key:
        request_params["api_key"] = api_key
    return request_params


def _ncbi_get_json(url: str, params: dict[str, str]) -> dict:
    global _NCBI_LAST_REQUEST
    data = _get_json(f"{url}?{urllib.parse.urlencode(_ncbi_prepare(params))}")
    _NCBI_LAST_REQUEST = time.monotonic()
    return data


NCBI_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
MAX_FASTA_BYTES = 8 * 1024 * 1024
_NUCCORE_ACCESSION_RE = re.compile(r"[A-Z]{1,2}_?[0-9]{5,9}\.[0-9]{1,3}")


def fetch_nuccore_fasta(accession: str) -> bytes:
    """FASTA for one versioned NCBI nucleotide accession (e.g. the RefSeq
    transcript NM_007294.4). Public reference data only; raises on request
    failure or a non-FASTA reply."""
    global _NCBI_LAST_REQUEST
    if not _NUCCORE_ACCESSION_RE.fullmatch(accession):
        raise ValueError("accession must be a versioned NCBI nucleotide accession such as NM_007294.4")
    params = _ncbi_prepare({"db": "nuccore", "id": accession, "rettype": "fasta", "retmode": "text"})
    request = urllib.request.Request(
        f"{NCBI_EFETCH}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
            data = response.read(MAX_FASTA_BYTES + 1)
    except HTTPError as error:
        raise RuntimeError(f"NCBI returned HTTP {error.code} for {accession}") from None
    except (URLError, OSError, TimeoutError) as error:
        raise RuntimeError(f"request to NCBI failed ({type(error).__name__})") from None
    finally:
        _NCBI_LAST_REQUEST = time.monotonic()
    if len(data) > MAX_FASTA_BYTES:
        raise ValueError(f"{accession} FASTA exceeds {MAX_FASTA_BYTES} bytes")
    if not data.startswith(b">"):
        raise ValueError(f"NCBI did not return FASTA for {accession}")
    return data


def _safe_summary(summary: dict, *, database: str) -> str:
    if database == "clinvar":
        allowed = ("accession", "clinical_significance", "variation_type", "genes", "trait_set")
    else:
        allowed = ("snp_id", "snp_class", "clinical_significance", "genes", "allele_origin")
    values = {key: summary[key] for key in allowed if key in summary}
    return json.dumps(values, ensure_ascii=True, sort_keys=True)[:MAX_SUMMARY_CHARS]


def search_ncbi_variants(query: str, *, database: str, max_results: int = 10) -> list[dict]:
    """Search ClinVar or dbSNP through NCBI E-utilities using an optional env API key."""
    if database not in {"clinvar", "snp"}:
        raise ValueError("database must be 'clinvar' or 'snp'")
    if not query.strip():
        raise ValueError("query cannot be empty")
    if not 1 <= max_results <= 100:
        raise ValueError("max_results must be between 1 and 100")

    search = _ncbi_get_json(NCBI_ESEARCH, {
        "db": database,
        "term": query,
        "retmode": "json",
        "retmax": str(max_results),
    })
    ids = search.get("esearchresult", {}).get("idlist", [])
    if not isinstance(ids, list) or not ids:
        return []

    summary_response = _ncbi_get_json(NCBI_ESUMMARY, {
        "db": database,
        "id": ",".join(str(item) for item in ids),
        "retmode": "json",
    })
    result = summary_response.get("result", {})
    if not isinstance(result, dict):
        raise ValueError(f"NCBI {database} response did not contain record summaries")

    return [
        _ncbi_variant_record(uid, result[str(uid)], database=database)
        for uid in ids[:max_results]
        if isinstance(result.get(str(uid)), dict)
    ]


def clinvar_records_by_id(uids: list[str]) -> list[dict]:
    """ClinVar records for known variation UIDs (e.g. from research_store.json),
    in the same form search_ncbi_variants returns. Raises on request failure;
    UIDs NCBI does not return are omitted."""
    clean = [str(uid).strip() for uid in uids if str(uid).strip().isdigit()]
    if not clean:
        return []
    if len(clean) > 200:
        raise ValueError("at most 200 ClinVar UIDs per request")
    summary_response = _ncbi_get_json(NCBI_ESUMMARY, {
        "db": "clinvar",
        "id": ",".join(clean),
        "retmode": "json",
    })
    result = summary_response.get("result", {})
    if not isinstance(result, dict):
        raise ValueError("NCBI clinvar response did not contain record summaries")
    return [
        _ncbi_variant_record(uid, result[uid], database="clinvar")
        for uid in clean
        if isinstance(result.get(uid), dict)
    ]


CLINVAR_SIGNIFICANCES = (
    "Pathogenic", "Likely pathogenic", "Uncertain significance",
    "Likely benign", "Benign", "Conflicting interpretations of pathogenicity",
)


def clinvar_classifications(gene: str, *, max_results: int = 10,
                            significance: str | None = None) -> list[dict]:
    """ClinVar's own classification of variants in one gene.

    Every field here is ClinVar's assessment (from its submitters), carried
    with its review status, when it was last evaluated, and a link to the
    record. It is attributed to ClinVar, never presented as this project's
    judgment, and it describes a variant's reported significance, not what
    would treat anyone.
    """
    symbol = gene.strip().upper()
    if not symbol or not re.fullmatch(r"[A-Z][A-Z0-9-]{0,14}", symbol):
        raise ValueError("gene must be a gene symbol such as BRCA1")
    if not 1 <= max_results <= 100:
        raise ValueError("max_results must be between 1 and 100")
    term = f"{symbol}[gene]"
    if significance is not None:
        if significance not in CLINVAR_SIGNIFICANCES:
            raise ValueError(f"significance must be one of {CLINVAR_SIGNIFICANCES}")
        term += f' AND "{significance}"[Clinical_significance]'

    search = _ncbi_get_json(NCBI_ESEARCH, {
        "db": "clinvar", "term": term, "retmode": "json", "retmax": str(max_results),
    })
    ids = search.get("esearchresult", {}).get("idlist") or []
    if not isinstance(ids, list) or not ids:
        return []
    summary = _ncbi_get_json(NCBI_ESUMMARY, {
        "db": "clinvar", "id": ",".join(str(i) for i in ids), "retmode": "json",
    }).get("result", {})
    if not isinstance(summary, dict):
        raise ValueError("NCBI clinvar response did not contain record summaries")
    return [
        _clinvar_classification(str(uid), summary[str(uid)], symbol)
        for uid in ids
        if isinstance(summary.get(str(uid)), dict)
    ]


def _clinvar_classification(uid: str, item: dict, gene: str) -> dict:
    """One ClinVar summary reduced to its attributed classification."""
    germline = item.get("germline_classification") or item.get("clinical_significance") or {}
    if not isinstance(germline, dict):
        germline = {"description": str(germline)}
    traits = germline.get("trait_set") or item.get("trait_set") or []
    conditions = sorted({
        str(trait.get("trait_name") or "").strip()
        for trait in traits if isinstance(trait, dict) and trait.get("trait_name")
    })
    variation = (item.get("variation_set") or [{}])[0]
    if not isinstance(variation, dict):
        variation = {}
    genes = [
        str(entry.get("symbol") or "").strip()
        for entry in (item.get("genes") or []) if isinstance(entry, dict) and entry.get("symbol")
    ]
    return {
        "source": "clinvar",
        "uid": uid,
        "accession": str(item.get("accession") or uid),
        "gene": gene,
        "gene_symbols": sorted({g for g in genes if g}) or [gene],
        "title": str(item.get("title") or f"ClinVar variation {uid}"),
        "variant_type": str(variation.get("variant_type") or item.get("obj_type") or ""),
        "protein_change": str(item.get("protein_change") or ""),
        "canonical_spdi": str(variation.get("canonical_spdi") or ""),
        # ClinVar's own words, kept verbatim:
        "clinvar_classification": str(germline.get("description") or "not provided"),
        "clinvar_review_status": str(germline.get("review_status") or ""),
        "clinvar_last_evaluated": str(germline.get("last_evaluated") or ""),
        "conditions": conditions[:10],
        "source_url": f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{uid}/",
        "asserted_by": "ClinVar (NCBI) and its submitters, not this project",
        "classification": "public",
    }


def _ncbi_variant_record(uid, item: dict, *, database: str) -> dict:
    if database == "clinvar":
        source = "clinvar"
        external_id = str(item.get("accession") or item.get("uid") or uid)
        title = str(item.get("title") or f"ClinVar variation {external_id}")
        url = f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{uid}/"
        terms = "https://www.ncbi.nlm.nih.gov/home/about/policies/"
    else:
        source = "dbsnp"
        snp_id = str(item.get("snp_id") or item.get("rs") or item.get("uid") or uid)
        external_id = (
            snp_id if snp_id.lower().startswith("rs")
            else f"rs{snp_id}" if snp_id.isdigit()
            else snp_id
        )
        title = str(item.get("title") or f"dbSNP record {external_id}")
        url = f"https://www.ncbi.nlm.nih.gov/snp/{urllib.parse.quote(external_id)}"
        terms = "https://www.ncbi.nlm.nih.gov/home/about/policies/"
    return {
        "source": source,
        "external_id": external_id,
        "title": title,
        "abstract": _safe_summary(item, database=database),
        "source_url": url,
        "published_at": "",
        "classification": "public",
        "rights_status": "public metadata; review source terms",
        "terms_url": terms,
    }


def lookup_ensembl_gene(symbol: str) -> list[dict]:
    """Look up one human gene symbol through the public Ensembl REST API."""
    symbol = symbol.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", symbol):
        raise ValueError("Ensembl lookup requires a gene symbol or identifier")
    result = _get_json(ENSEMBL_LOOKUP + urllib.parse.quote(symbol, safe=""))
    stable_id = result.get("id")
    if not isinstance(stable_id, str) or not stable_id:
        return []
    summary = {
        key: result[key]
        for key in ("display_name", "description", "biotype", "seq_region_name", "start", "end", "strand")
        if key in result
    }
    return [{
        "source": "ensembl",
        "external_id": stable_id,
        "title": f"Ensembl gene {result.get('display_name') or symbol} ({stable_id})",
        "abstract": json.dumps(summary, ensure_ascii=True, sort_keys=True)[:MAX_SUMMARY_CHARS],
        "source_url": f"https://rest.ensembl.org/lookup/id/{urllib.parse.quote(stable_id, safe='')}",
        "published_at": "",
        "classification": "public",
        "rights_status": "public metadata; review source terms",
        "terms_url": "https://www.ensembl.org/info/about/legal/",
    }]


def lookup_gnomad_variant(variant_id: str) -> list[dict]:
    """Look up one normalized variant ID in the public gnomAD v4 GraphQL API."""
    variant_id = variant_id.strip()
    if not re.fullmatch(r"(?:[0-9]+|X|Y|MT)-[1-9][0-9]*-[ACGTN]+-[ACGTN]+", variant_id, re.I):
        raise ValueError("gnomAD lookup requires a variant ID like 7-140753336-A-T")
    query = """
    query VariantLookup($variantId: String!, $dataset: DatasetId!) {
      variant(variantId: $variantId, dataset: $dataset) {
        variant_id
        genome { ac an af }
        exome { ac an af }
      }
    }
    """
    response = _post_json(GNOMAD_GRAPHQL, {
        "query": query,
        "variables": {"variantId": variant_id, "dataset": "gnomad_r4"},
    })
    if response.get("errors"):
        raise RuntimeError("gnomAD rejected the variant lookup")
    variant = response.get("data", {}).get("variant")
    if not isinstance(variant, dict):
        return []
    external_id = str(variant.get("variant_id") or variant_id)
    return [{
        "source": "gnomad",
        "external_id": external_id,
        "title": f"gnomAD v4 variant {external_id}",
        "abstract": json.dumps(
            {key: variant[key] for key in ("genome", "exome") if key in variant},
            ensure_ascii=True,
            sort_keys=True,
        )[:MAX_SUMMARY_CHARS],
        "source_url": (
            f"https://gnomad.broadinstitute.org/variant/{urllib.parse.quote(external_id, safe='')}"
            "?dataset=gnomad_r4"
        ),
        "published_at": "",
        "classification": "public",
        "rights_status": "public aggregate data; review source terms",
        "terms_url": "https://gnomad.broadinstitute.org/terms",
    }]
