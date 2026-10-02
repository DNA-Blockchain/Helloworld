# Cancer genomics in the twin: datasets, comparison, candidate guides

> **Not medical advice, and not a treatment tool.** Everything here is computation on public research
> data, upstream of any laboratory. A variant list is not a diagnosis. A candidate guide is an untested
> hypothesis for a laboratory to evaluate, not a therapy. **No software can edit, repair or signal to DNA
> inside a body**: that needs molecules physically delivered into cells, which is the unsolved problem of
> the whole field. Treatment decisions belong with an oncologist who knows the diagnosis and history.

This is the software layer the evidence actually supports, drawn from
[docs/research/dna-editing-and-cancer-remission.md](../research/dna-editing-and-cancer-remission.md).
That report found that as of October 2026 every case of DNA research producing remission worked through
a physical intervention: edited immune cells infused into a vein, a drug or vaccine chosen from a
sequenced tumour, or fields and heat applied to tissue. The digital layer still matters, because
sequencing data is what designs those vaccines, tracks residual disease in blood and finds drug
targets. So the twin works at that layer.

```
public datasets ─▶ record (SHA-256, licence, tier) ─▶ compare (gained / lost / shifted variants)
                                                   └▶ guides (candidate Cas9 sites + predicted outcomes)
                                                              │
                                              laboratory testing by researchers ─▶ trials ─▶ clinic
```

The twin's work ends at the first arrow into "laboratory testing". It never reaches a patient.

## Commands

```powershell
python -m twinos datasets [--all]                  # the catalogue: licence, access tier, what it's for
python -m twinos fetch depmap-crispr-gene-effect   # where to get it, and whether this twin may
python -m twinos record <name> --file <path>       # fingerprint a file you downloaded, into the ledger
python -m twinos compare cancer.vcf normal.vcf [--megabases 1.1] [--shift 0.2]
python -m twinos guides region.fa --at 150 [--window 30]
```

Other agents can also ask this twin to search the research reports (`research_search`), which runs
without approval because the reports hold public research only.

## The dataset catalogue

[`twinos/datasets.json`](../../twinos/datasets.json) lists the datasets the report found, each with its
access tier, which decides what the twin may do:

| Tier | Meaning | What `fetch` does |
|---|---|---|
| `open` | Public, no application | Offers to download it, after a yes |
| `registered` | A free account and click-through agreement first | Prints the page for you to download yourself |
| `controlled` | An institution's data access committee must approve | **Refuses**, and gives the application URL |

Useful entries: **DepMap** (CRISPR gene-effect scores for 1,208 cell lines, CC BY 4.0),
**BioGRID ORCS** (2,217 published screens, MIT), **FORECasT** and **inDelphi** (measured Cas9 repair
outcomes), the **GDC open TCGA mutation tables**, and three true before/after studies in GEO:
**GSE91061** (65 melanoma patients before and during nivolumab, with response labels), **GSE192341**
(22 matched breast tumour pairs) and **GSE240671** (29 non-responders resequenced). **TRACERx** and
**Hartwig**, the strongest longitudinal human sets, are controlled access.

## Privacy, licences and the chain

- **Cell-line data carries no personal data**, so CRISPR screens and editing-outcome datasets are the
  safest material here. Their release fingerprints can go on the chain.
- **GENIE** forbids redistribution and **MSK-CHORD** is non-commercial with no derivatives: use them
  locally and publish only aggregates and release fingerprints.
- **A personal genome never goes on the chain, not even as a hash.** EU guidance (July 2026) treats a
  hash of personal data as personal data, and a 2013 study recovered surnames from genomes about 12% of
  the time. Personal sequences and reports belong in the encrypted vault
  (`python dna_shell.py data-vault-store`), with keyed digests at most.
- `record` marks each dataset `publishable` only when its licence allows redistribution **and** it holds
  no personal data.

## What `compare` does and doesn't mean

It reads two variant files (VCF, or a MAF/TSV with named columns) and reports variants **gained**, variants
**lost**, variants **shared**, and **allele-frequency shifts** above a threshold, plus mutations per
megabase when you give the sequenced size. Those are facts about two files. They are not a diagnosis, not
a ranked target list, and they carry no claim that changing any of them would help anyone.

## What `guides` does and doesn't mean

For a position in a reference sequence, it finds SpCas9 (NGG) protospacers whose predicted cut falls
within a window, nearest first, with GC content and strand. This is the standard **first** computational
step of guide design. It accounts for none of the following, each of which decides whether a guide is
usable at all:

- **off-target sites** elsewhere in the genome (needs a genome-wide search, not in this tool);
- **chromatin and cell type**, which change whether a site can be cut;
- **delivery** into the target cells, the field's central unsolved problem;
- **what the edit would do biologically**, which laboratory work establishes, not arithmetic.

Measured repair outcomes are public (FORECasT, inDelphi), so a prediction can be checked against data
rather than assumed. Predicting one edit's outcome still says nothing about whether editing would help a
cancer: **no trial has treated a solid tumour by editing it inside the body.**

## Why the twin cannot plan a path to remission

The research is explicit, and the software must not imply otherwise:

1. **Cancer is not one edit.** A tumour carries thousands of mutations across cells that keep changing.
2. **Nothing reaches the tumour.** Every human CRISPR cancer result edited immune cells *outside* the
   body and infused them. The one in-body CRISPR success targeted the liver, chosen for accessibility.
3. **A target is not a treatment.** The best-known target found by CRISPR screens (WRN in MSI cancers)
   entered trials as a conventional small-molecule drug, not an edit.
4. **Radio carries data, not biology.** The project's own radio module says it plainly: "the DNA has no
   radio frequency of its own". A 2.4 GHz photon carries roughly 2,700 times less energy than the
   thermal motion of molecules at body temperature, and cells have nothing that decodes digital data.

What is real and reachable through an oncologist today: tumour genomic profiling, residual-disease
(ctDNA/MRD) blood testing, and trials of CRISPR-edited cell therapies and personalised neoantigen
vaccines. [ClinicalTrials.gov](https://clinicaltrials.gov) lists them.
