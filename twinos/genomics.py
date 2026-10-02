"""Public cancer-genomics datasets, before/after comparison, and candidate guide design.

NOT A TREATMENT TOOL. Everything here is computation on public research data, upstream of any
laboratory. A variant list is not a diagnosis, and a candidate guide is an untested hypothesis for a
laboratory to evaluate, never a therapy. No software can edit, repair or signal to DNA in a body: that
needs molecules physically delivered into cells, which is the unsolved problem of the field
(docs/research/dna-editing-and-cancer-remission.md). Treatment decisions belong with an oncologist.

    catalogue      the datasets in twinos/datasets.json with their licence and access tier
    fetch          where to get a dataset, and whether this twin may download it at all
    record         fingerprint a dataset file you downloaded, into the twin's ledger (SHA-256, licence)
    compare        a cancer variant set against a normal reference: gained, lost, allele-frequency
                   shifts, mutational burden
    guides         for one variant, the candidate Cas9 guides in its region and their predicted
                   edit outcomes, each marked as an untested hypothesis

Access tiers: `open` can be fetched; `registered` needs the owner's own account and click-through, so
this prints the page to visit; `controlled` needs an institution's data access committee, so this
refuses and says so. A dataset marked personal_data stays on this PC, and only aggregates and release
fingerprints may be published (research_provenance rules; the chain holds fingerprints only).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

CATALOGUE = Path(__file__).resolve().parent / "datasets.json"
TIERS = ("open", "registered", "controlled")
BASES = set("ACGT")
PAM = re.compile(r"(?=([ACGT]{21})GG)")      # 20-base protospacer + NGG, overlapping matches
GUIDE_LENGTH = 20
MAX_GUIDES = 20
HYPOTHESIS = ("A candidate for laboratory testing, not a treatment. Computed from a reference sequence; "
              "nothing here has been tested in cells, and no edit list leads to remission on its own.")


def catalogue(path: Path = CATALOGUE) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))["datasets"]
    for d in data:
        if d["access"] not in TIERS:
            raise ValueError(f"{d['name']}: access must be one of {', '.join(TIERS)}")
    return data


def dataset(name: str, path: Path = CATALOGUE) -> dict:
    for d in catalogue(path):
        if d["name"] == name:
            return d
    raise KeyError(f"no dataset {name!r} in the catalogue (python -m twinos datasets)")


def fetch_plan(entry: dict) -> tuple[bool, str]:
    """Whether twinos may download this dataset, and the reason either way."""
    if entry["access"] == "controlled":
        return False, (f"{entry['name']} is controlled access: an institution's data access committee must "
                       f"approve it, so this twin won't download it. Apply at {entry['url']}.")
    if entry["access"] == "registered":
        return False, (f"{entry['name']} needs your own account and agreement first. Download it yourself from "
                       f"{entry['url']}, then point --from at the file.")
    if not entry.get("files"):
        return False, (f"{entry['name']} is open, but the catalogue has no direct file URL yet. Download it from "
                       f"{entry['url']}, then point --from at the file.")
    return True, f"{entry['name']} is open ({entry['license']})."


def record_entry(entry: dict, path: Path, sha256: str) -> dict:
    """What goes in the ledger for a downloaded dataset file: the release and its fingerprint, never its
    contents. A dataset holding personal data is recorded as a local release, so nothing identifying is
    published even as a digest."""
    return {"dataset": entry["name"], "title": entry["title"], "file": Path(path).name,
            "bytes": Path(path).stat().st_size, "sha256": sha256, "license": entry["license"],
            "access": entry["access"], "personal_data": entry["personal_data"],
            "publishable": entry["redistribute"] and not entry["personal_data"], "url": entry["url"]}


# -- variants ------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Variant:
    chrom: str
    pos: int
    ref: str
    alt: str
    gene: str = ""
    frequency: float | None = None      # variant allele frequency, 0..1, when the file gives one

    @property
    def key(self) -> tuple[str, int, str, str]:
        return (self.chrom, self.pos, self.ref, self.alt)

    def __str__(self) -> str:
        where = f"{self.gene} " if self.gene else ""
        return f"{where}{self.chrom}:{self.pos} {self.ref}>{self.alt}"


def read_variants(path: Path) -> list[Variant]:
    """Variants from a VCF (CHROM POS ID REF ALT, with AF in INFO) or a MAF/TSV with named columns."""
    text = Path(path).read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    if lines[0].startswith("##fileformat=VCF") or any(l.startswith("#CHROM") for l in lines):
        return _read_vcf(lines)
    return _read_table(lines)


def _frequency(text: str) -> float | None:
    match = re.search(r"(?:^|;)AF=([0-9.]+)", text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if 0.0 <= value <= 1.0 else None


def _read_vcf(lines: list[str]) -> list[Variant]:
    variants = []
    for line in lines:
        if line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        chrom, pos, _, ref, alt = parts[:5]
        if not pos.isdigit():
            continue
        info = parts[7] if len(parts) > 7 else ""
        gene = (re.search(r"(?:^|;)GENE=([^;]+)", info) or re.search(r"(?:^|;)SYMBOL=([^;]+)", info))
        for one in alt.split(","):
            variants.append(Variant(chrom, int(pos), ref.upper(), one.upper(),
                                    gene.group(1) if gene else "", _frequency(info)))
    return variants


_COLUMNS = {"chrom": ("chromosome", "chrom", "chr"), "pos": ("start_position", "position", "pos", "start"),
            "ref": ("reference_allele", "ref", "ref_allele"), "alt": ("tumor_seq_allele2", "alt", "alt_allele",
            "tumor_seq_allele"), "gene": ("hugo_symbol", "gene", "symbol"),
            "freq": ("vaf", "variant_allele_frequency", "af", "tumor_vaf")}


def _read_table(lines: list[str]) -> list[Variant]:
    rows = [l.split("\t") for l in lines if not l.startswith("#")]
    header = [h.strip().lower() for h in rows[0]]
    index = {field: next((header.index(n) for n in names if n in header), None)
             for field, names in _COLUMNS.items()}
    missing = [f for f in ("chrom", "pos", "ref", "alt") if index[f] is None]
    if missing:
        raise ValueError(f"{', '.join(missing)} column(s) not found; header was: {', '.join(header[:12])}")
    variants = []
    for row in rows[1:]:
        if len(row) <= max(i for i in index.values() if i is not None):
            continue
        pos = row[index["pos"]].strip()
        if not pos.isdigit():
            continue
        frequency = None
        if index["freq"] is not None:
            try:
                value = float(row[index["freq"]])
                frequency = value / 100 if value > 1.0 else value
            except ValueError:
                frequency = None
        variants.append(Variant(row[index["chrom"]].strip().strip("chr") or "?", int(pos),
                                row[index["ref"]].strip().upper(), row[index["alt"]].strip().upper(),
                                row[index["gene"]].strip() if index["gene"] is not None else "",
                                frequency if frequency is None or 0.0 <= frequency <= 1.0 else None))
    return variants


@dataclass
class Comparison:
    gained: list[Variant] = field(default_factory=list)       # in the cancer set only
    lost: list[Variant] = field(default_factory=list)         # in the normal/earlier set only
    shared: list[Variant] = field(default_factory=list)
    shifted: list[tuple[Variant, Variant]] = field(default_factory=list)   # shared, frequency moved

    def summary(self, shift: float) -> dict:
        return {"gained": len(self.gained), "lost": len(self.lost), "shared": len(self.shared),
                "frequency_shifts": len(self.shifted), "shift_threshold": shift}


def compare(cancer: list[Variant], reference: list[Variant], shift: float = 0.2) -> Comparison:
    """What differs between a cancer variant set and a normal/earlier one. A difference is a fact about
    two files, not a finding about a person, and not a target list."""
    by_key = {v.key: v for v in reference}
    cancer_keys = {v.key for v in cancer}
    result = Comparison()
    for v in cancer:
        other = by_key.get(v.key)
        if other is None:
            result.gained.append(v)
            continue
        result.shared.append(v)
        if v.frequency is not None and other.frequency is not None and abs(v.frequency - other.frequency) >= shift:
            result.shifted.append((other, v))
    result.lost = [v for v in reference if v.key not in cancer_keys]
    return result


def mutational_burden(variants: list[Variant], megabases: float) -> float | None:
    """Mutations per megabase of sequenced territory. Needs the panel or exome size, which the file
    doesn't carry, so the caller supplies it; without it this is not comparable between datasets."""
    if megabases <= 0:
        return None
    return round(len(variants) / megabases, 2)


# -- candidate guides ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Guide:
    protospacer: str
    pam: str
    strand: str
    start: int                       # 0-based offset in the sequence given
    gc: float
    distance_to_target: int
    hypothesis: str = HYPOTHESIS


def reverse_complement(sequence: str) -> str:
    return sequence.translate(str.maketrans("ACGT", "TGCA"))[::-1]


def candidate_guides(sequence: str, target_offset: int, window: int = 30, limit: int = MAX_GUIDES) -> list[Guide]:
    """SpCas9 (NGG) protospacers whose cut site falls within `window` bases of target_offset, nearest first.

    This is the standard first computational step of guide design. It accounts for neither off-target
    sites across the genome, nor chromatin, nor delivery, each of which decides whether a guide is
    usable at all. Every result carries HYPOTHESIS for that reason."""
    sequence = sequence.upper()
    if set(sequence) - BASES:
        raise ValueError("the sequence must be A, C, G and T only")
    if not 0 <= target_offset < len(sequence):
        raise ValueError(f"the target offset must be inside the sequence (0..{len(sequence) - 1})")
    guides = []
    for strand, text in (("+", sequence), ("-", reverse_complement(sequence))):
        for match in PAM.finditer(text):
            protospacer = match.group(1)[:GUIDE_LENGTH]
            at = match.start()
            cut = at + 17                                     # Cas9 cuts 3 bases 5' of the PAM
            # On the minus strand the match is in the reverse complement, so map back: the protospacer
            # occupies sequence[len - at - 20 : len - at], and rc index i is sequence index len - 1 - i.
            start = at if strand == "+" else len(sequence) - at - GUIDE_LENGTH
            cut_in_sequence = cut if strand == "+" else len(sequence) - cut - 1
            guides.append(Guide(protospacer, text[at + GUIDE_LENGTH:at + GUIDE_LENGTH + 3], strand, start,
                                round(sum(c in "GC" for c in protospacer) / GUIDE_LENGTH, 2),
                                abs(cut_in_sequence - target_offset)))
    return sorted((g for g in guides if g.distance_to_target <= window),
                  key=lambda g: (g.distance_to_target, -g.gc))[:limit]


def edit_outcome_note() -> str:
    """What the measured datasets say about predicting an edit's outcome, for printing beside guides."""
    return ("Measured repair outcomes for Cas9 edits are public (FORECasT: ENA PRJEB29746; inDelphi: SRA "
            "SRP141144), so a prediction can be checked against data rather than assumed. Predicting the "
            "outcome of one edit says nothing about whether editing would help a cancer: no trial has "
            "treated a solid tumour by editing it in the body, and delivery into tumour cells is unsolved "
            "(docs/research/dna-editing-and-cancer-remission.md).")
