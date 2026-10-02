# Public cancer genomic datasets with before/after-treatment samples, CRISPR datasets, access tiers and privacy rules for a local digital twin

Research date: 2026-10-02. About 18 tool calls (web search and fetch). Figures come from official portals, dataset papers and policy pages unless marked otherwise. Access tiers used below:
- **OPEN**: download with no application, sometimes after a click-through terms-of-use page or a free account.
- **CONTROLLED**: needs a Data Access Committee (DAC) application through dbGaP, EGA or the project's own DAC, with an institutional signature.

## Paired pre/post-treatment and longitudinal cancer genomic datasets (catalogue)

### Takeaway
Raw genomes or exomes taken from the same patient before and after treatment are almost always CONTROLLED: TRACERx, POG570 raw data, Hartwig, and TCGA/GDC BAM/VCF files. The OPEN material is processed data: somatic MAFs, gene-expression matrices in GEO, the GENIE and MSK-CHORD panel mutations with clinical outcomes, and the POG570 mutation catalogue. These are enough for a local twin that compares a sample against a reference at the level of variants and genes, but not at the level of raw reads.

### Cited Findings

**Riaz et al. 2017 (Cell), melanoma, nivolumab, pre/on-treatment**
- 68 patients with advanced melanoma, either ipilimumab-progressed or ipilimumab-naive, were sampled before and after starting nivolumab (trial CA209-038). Methods were WES, RNA-seq and TCR-seq. — [Cell](https://www.cell.com/cell/fulltext/S0092-8674(17)31122-4); [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0092867417311224)
- GEO **GSE91061** holds the expression data: 109 samples from 65 patients, 51 pre-treatment and 58 on-treatment. On-treatment means day 29 of cycle 1. — [J Transl Med systematic review](https://link.springer.com/article/10.1186/s12967-022-03409-4); [Sci Rep 2025](https://www.nature.com/articles/s41598-025-94931-0)
- Outcome labels: responders had lower mutational and neoantigen loads. On-treatment samples showed immune-cell expansion and higher checkpoint expression. — [Cell](https://www.cell.com/cell/fulltext/S0092-8674(17)31122-4)
- MSK lists a related catalogue entry, "Molecular portraits of tumor mutational and micro-environmental sculpting by immune checkpoint blockade therapy". — [MSK Data Catalog](https://datacatalog.mskcc.org/dataset/10509)
- Access tier: the GEO processed expression is OPEN.

**GEO neoadjuvant breast cancer pairs**
- **GSE192341**:
  - RNA-seq of 87 pre-treatment biopsies.
  - Deep WES plus RNA-seq of 22 matched pre/post-treatment tumour pairs.
  - Part of a study of 317 HER2-negative, treatment-naive biopsies from patients who went on to neoadjuvant chemotherapy.
  - — [GEO GSE192341](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE192341); [Genome Medicine 2024](https://genomemedicine.biomedcentral.com/articles/10.1186/s13073-024-01286-8)
- **GSE240671**: stranded bulk RNA-seq before and after neoadjuvant chemotherapy. There are 95 pre-treatment tumours. The 29 tumours that did not respond completely were sequenced again as residual disease. The outcome label is pathological complete response vs residual disease. — [GEO GSE240671](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE240671)
- npj Breast Cancer 2022: WES and RNA-seq of 233 samples from 50 breast cancer patients with matched pre/post-NAC tumours and strictly defined response. — [npj Breast Cancer](https://www.nature.com/articles/s41523-022-00428-8)
- dbGaP **phs001291**, neoadjuvant trastuzumab response in breast cancer, is CONTROLLED. — [OmicsDI](https://www.omicsdi.org/dataset/dbgap/phs001291)

**TRACERx (lung, longitudinal, ctDNA)**
- Prospective NSCLC study that follows patients from diagnosis to cure or relapse:
  - multi-region sampling of primary and metastatic tumours;
  - longitudinal ctDNA;
  - clinical outcomes.
- The TRACERx 421 cohort is the first 421 patients recruited. — [Nature 2023, metastases](https://www.nature.com/articles/s41586-023-05729-x); [Nature 2023, ctDNA](https://www.nature.com/articles/s41586-023-05776-4); [Nature 2023, subclonal selection](https://www.nature.com/articles/s41586-023-05783-5)
- Data locations: WES in EGA **EGAS00001006494** and RNA-seq in **EGAS00001006517**, e.g. dataset [EGAD00001009862](https://ega-archive.org/datasets/EGAD00001009862).
- Access tier: CONTROLLED. The TRACERx DAC at the Francis Crick Institute reviews each request against patient consent and scientific purpose, and a signed Data Access Agreement is required. — [Nature](https://www.nature.com/articles/s41586-023-05729-x)
- The longitudinal cohort was reported complete at AACR 2025. — [Cancer Res abstract 6421](https://aacrjournals.org/cancerres/article/85/8_Supplement_1/6421/757394)

**POG570 (Personalized OncoGenomics, BC Cancer)**
- 570 patients with advanced or metastatic cancer across 25 histologies, profiled by WGS plus transcriptome:
  - 82% had prior systemic therapy;
  - 72% had more than one drug;
  - 110 distinct drugs in total;
  - treatment lasted from 4 days to over 4 years.
  - — [Nature Cancer 2020 / PubMed](https://pubmed.ncbi.nlm.nih.gov/35121966/); [BCGSC main text](https://www.bcgsc.ca/sites/default/files/Main_Text.pdf)
- Access tiers:
  - Raw reads in EGA **EGAS00001001159**: CONTROLLED.
  - Small-mutation catalogue and expression TPMs at bcgsc.ca/downloads/POG570/: OPEN.
  - POG cBioPortal at personalizedoncogenomics.org/cbioportal/: OPEN.
  - — [Nature Cancer](https://www.nature.com/articles/s43018-020-0050-6); [EGA request process](https://ega-archive.org/access/request-data/how-to-request-data/)
- Design: these are mostly single post-treatment biopsies linked to treatment history, not true within-patient pre/post pairs.

**Hartwig Medical Foundation (Netherlands, metastatic)**
- WGS of tumour and blood for more than 8,000 patients with metastatic cancer, linked to clinical treatment and outcome data from hospitals. Hartwig calls it the largest such database. — [Hartwig Database](https://www.hartwigmedicalfoundation.nl/en/data/database/)
- Access tier: CONTROLLED.
  - The Scientific Board and the Data Access Board review each request.
  - The applicant signs a licence agreement and a publication pledge.
  - The research has to serve the public interest in cancer treatment.
  - An anonymised subset can be browsed in the [Hartwig Data Catalogue](https://catalog.hartwigmedicalfoundation.nl/).
  - — [Hartwig Database](https://www.hartwigmedicalfoundation.nl/en/data/database/); [Data Access Request Guide](https://hartwigmedical.github.io/documentation/data-access-request-guide.html)
- Data quality: the clinical eCRF records are not guaranteed to be complete. — [Hartwig approved requests](https://www.hartwigmedicalfoundation.nl/en/data/research-and-science/datarequests/)
- Example approved request DR-509 links WGS (plus RNA where present) to response vs non-response to chemotherapy and targeted therapy in metastatic colorectal cancer. — [Hartwig approved requests](https://www.hartwigmedicalfoundation.nl/en/data/research-and-science/datarequests/)

**AACR Project GENIE (main registry) and GENIE BPC**
- **19.0-public** (data guide dated 2026-01-23):
  - 271,837+ sequenced samples from 227,696+ patients;
  - adds cfDNA samples;
  - retracts 30 samples that were in 18.0;
  - contributed by 19 international cancer centres.
  - — [GENIE 19.0 data guide](https://www.aacr.org/wp-content/uploads/2026/02/19.0_public_data_guide.pdf); [cBioPortal GENIE news](https://docs.cbioportal.org/news-genie/)
- Access tier: OPEN after a free Synapse account and click-through terms.
  - Users agree not to try to identify or contact participants.
  - Users agree not to redistribute the data without written permission from the GENIE Coordinating Center.
  - Downloads are at genie.synapse.org; data can also be explored on genie.cbioportal.org.
  - — [GENIE FAQ](https://www.aacr.org/professionals/research/aacr-project-genie/aacr-project-genie-frequently-asked-questions/); [GENIE 16.0 data guide](https://www.aacr.org/wp-content/uploads/2024/07/data_guide.pdf)
- Contents: targeted panels only (no WGS). The main registry has limited clinical data.
- **BPC** (Biopharma Collaborative): started in 2019 with 10 pharma companies. It adds curated real-world treatment data with real-world PFS and OS.
  - Program target: about 50,000 patients.
  - It produced 10 cancer cohorts.
  - The NSCLC cohort has 1,846 patients and was the first public release.
  - A breast cancer cohort has 1,045 patients.
  - The data are processed with the genieBPC R package.
  - — [Clin Cancer Res 2023](https://aacrjournals.org/clincancerres/article/29/17/3418/728542/The-GENIE-BPC-NSCLC-Cohort-A-Real-World-Repository); [BPC overview, PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12836680/); [genieBPC](https://genie-bpc.github.io/genieBPC/); [MSK Biostatistics](https://www.mskcc.org/departments/epidemiology-biostatistics/biostatistics/project-genie-bpc-genomics-evidence-neoplasia-information-exchange-biopharma-collaborative)
- Some BPC patients have more than one sequenced sample, so before and after a therapy line can be reconstructed. This is my inference from the multi-sample, regimen-level design and was not confirmed as a counted figure.

**MSK-IMPACT / MSK-CHORD**
- 25,040 tumours from 24,950 patients, sequenced with MSK-IMPACT against matched normal blood.
- Covers NSCLC, breast, colorectal, prostate and pancreatic cancer.
- Treatment and registry data are included, some of them derived by NLP, with overall survival.
- Access tier: OPEN on cBioPortal under **CC BY-NC-ND 4.0**, which means no commercial use and no derivatives redistributed.
- — [Nature 2024](https://www.nature.com/articles/s41586-024-08167-5); [MSK Data Catalog](https://datacatalog.mskcc.org/dataset/11458)
- Example downstream use: the OncoTraj benchmark (arXiv 2606.11144) pooled 813 EGFR-mutant NSCLC patients on osimertinib: 672 from MSK-CHORD, 34 from GENIE BPC and 107 from FLAURA. Version 1 uses single-timepoint features, not serial ctDNA, which shows how scarce public serial ctDNA data are. — [arXiv 2606.11144](https://arxiv.org/abs/2606.11144)

**TCGA / GDC**
- File tiers:
  - Open-access "Masked Somatic Mutation" MAFs are filtered to remove low-quality and possible germline calls and may be freely redistributed.
  - VCFs, unmasked MAFs and BAMs are CONTROLLED through dbGaP.
  - — [GDC MAF format](https://docs.gdc.cancer.gov/Data/File_Formats/MAF_Format); [GDC Data User's Guide](https://docs.gdc.cancer.gov/Data/PDF/Data_UG.pdf); [AWS Open Data TCGA](https://registry.opendata.aws/tcga/)

**ICGC/PCAWG and CPTAC**
- I did not fetch current pages for either in this pass. See Gaps.

### Inferences
- TCGA is almost entirely primary, pre-treatment, surgically resected tumours. It is a good source of "reference" tumour profiles but not of before/after pairs. I could not cite a figure for this in this pass; see Gaps.
- The datasets most useful for an open local twin of "before vs after treatment" are:
  - GSE91061 (immunotherapy, expression);
  - GSE192341 and GSE240671 (neoadjuvant chemotherapy, expression);
  - GENIE BPC and MSK-CHORD (panel variants plus treatment and survival);
  - the POG570 open mutation catalogue (post-treatment metastatic variants).
- True paired raw WGS/WES (TRACERx, Hartwig, POG raw) needs an institutional DAC application. An individual hobbyist or a non-institutional project generally cannot get it. All of these DACs require an institution to co-sign.

### Gaps
- No verified current figures were found for ICGC ARGO/PCAWG (2,658 WGS; the 25K portal was retired) or for CPTAC treatment data. Check portal.gdc.cancer.gov and platform.icgc-argo.org.
- No authoritative count was found of TCGA samples taken after neoadjuvant therapy or of recurrent tumours.
- Not confirmed whether the Riaz 2017 WES raw reads are in open SRA or controlled. GEO normally carries only processed expression for human patients.
- No public longitudinal ctDNA dataset with variant-level, open data was confirmed. TRACERx ctDNA is controlled, and OncoTraj notes that serial ctDNA is missing.
- Total download sizes (GB) for each dataset were not verified.

## CRISPR datasets (screens and editing outcomes)

### Takeaway
The CRISPR data is the most open part of this catalogue, because it comes from cell lines and synthetic target libraries rather than patients:
- DepMap: CC BY 4.0;
- BioGRID ORCS: MIT licence;
- the FORECasT and inDelphi raw reads: ENA/SRA.

None of it needs a DAC, and it is safe to fingerprint on a public ledger.

### Cited Findings
- **DepMap (Broad; Achilles CRISPR KO plus CCLE characterisation)**:
  - Released quarterly. The CRISPRGeneEffect matrix is batch-corrected with Chronos.
  - Available through the portal, an API and bulk downloads.
  - Licence: **CC BY 4.0**.
  - — [DepMap portal](https://depmap.org/portal/); [Figshare 22Q4](https://figshare.com/articles/dataset/DepMap_22Q4_Public/21637199); [Bioconductor depmap](https://www.bioconductor.org/packages//release/data/experiment/manuals/depmap/man/depmap.pdf)
- **DepMap 26Q1** CRISPRGeneEffect: 1,208 models, of which 1,192 are cancer cell lines once 16 non-cancer models are excluded. — [DepMap 26Q1 announcement](https://forum.depmap.org/t/announcing-the-26q1-release/4606); a secondary [GitHub analysis](https://github.com/liranfei/DepMap-26Q1-Analysis) gives the counts.
- **DepMap 25Q3** added 3 genome-wide KO screens in rare and paediatric cancers and 7 Sanger KY screens. — [25Q3 announcement](https://forum.depmap.org/t/announcing-the-25q3-release/4476)
- **BioGRID ORCS v2.0.18**: 2,217 CRISPR screens from 418 publications.
  - Covers 94,219 genes, 825 cell lines, 145 cell types, 29 phenotypes and 5 organisms.
  - Files are released under the **MIT licence** and are free for academic and commercial use.
  - Download from downloads.thebiogrid.org.
  - — [BioGRID ORCS](https://orcs.thebiogrid.org/); [ORCS 2.0.18 news](https://thebiogrid.org/news/334)
- **FORECasT** (Allen et al. 2019) repair-outcome reads are in ENA **PRJEB29746**. **inDelphi** (Shen et al. 2018) reads are in SRA **SRP141144**.
  - Benchmark sizes used in later work: 5,900 FORECasT wild-type mESC target profiles for training, tested on 3,954 FORECasT and 1,961 inDelphi targets.
  - — [X-CRISP, Bioinformatics Advances 2025](https://academic.oup.com/bioinformaticsadvances/article/5/1/vbaf157/8182141); [bioRxiv](https://www.biorxiv.org/content/10.1101/2025.02.06.636858v2.full)
- **Leenay et al. 2019** published a large repair-outcome dataset in primary human T cells. — [ResearchGate record](https://www.researchgate.net/publication/334750459_Large_dataset_enables_prediction_of_repair_after_CRISPR-Cas9_editing_in_primary_T_cells)

### Inferences
- A twin can treat DepMap CRISPRGeneEffect, a cell-line × gene CSV, as a "dependency" layer. Mutations from a patient profile (MAF from GENIE or MSK-CHORD) can be matched to cell lines with similar alterations, to suggest which genes the matched lines depend on. This is a research hypothesis, not clinical advice.
- FORECasT and inDelphi data let the twin predict the indel distribution for a given guide plus target sequence. That is a natural "edit simulation" on a reference FASTA.

### Gaps
- Exact current file sizes were not verified, e.g. the CRISPRGeneEffect.csv size per release (on the order of hundreds of MB; unverified).
- The licence of the processed FORECasT/inDelphi tables on figshare or GitHub was not checked. ENA/SRA raw data has no licence restriction, but the code repositories carry their own licences.

## Access tiers and what the terms of use forbid

### Takeaway
Open processed data still comes with conditions:
- GENIE forbids re-identification and redistribution.
- MSK-CHORD is non-commercial and no-derivatives.
- Only DepMap (CC BY 4.0), BioGRID ORCS (MIT) and the GDC open somatic MAFs (freely redistributable) can clearly be republished.

Controlled-access data (dbGaP, EGA, Hartwig, TRACERx) must stay inside the approved user's secured environment. Re-identification is forbidden, and the security rules also cover third-party and cloud systems. Uploading that data, or anything derived from individual records, to a public blockchain is incompatible with these terms.

### Cited Findings
- **NIH GDS policy, controlled data**:
  - Users sign a Data Use Certification with an institutional co-signature and the Genomic Data User Code of Conduct, and must use the data in line with participants' consent.
  - Users must not try to identify participants.
  - Since 25 January 2025, users must follow the NIH Security Best Practices for Users of Controlled-Access Data.
  - Any cloud or third-party IT system must meet the same standards.
  - — [NIH: Using Genomic Data Responsibly](https://grants.nih.gov/policy-and-compliance/policy-topics/sharing-policies/accessing-data/using-genomic-data); [GDS Policy overview](https://osp.od.nih.gov/wp-content/uploads/NIH_GDS_Policy_Overview.pdf); [NOT-OD-14-124](https://grants.nih.gov/grants/guide/notice-files/not-od-14-124.html)
- **NIH revisions in 2026**: NIH proposed a Controlled-Access Data Policy and revisions to GDS (RFI NOT-OD-26-023). Comments from ASHG and APLU were submitted in March 2026. — [ASHG response](https://www.ashg.org/wp-content/uploads/2026/03/ASHG_NIH-Genomic-Data-Sharing-Policy-RFI_03.17.2026-FINAL.pdf); [APLU response](https://www.aplu.org/wp-content/uploads/APLU-RFI-NOT-OD-26-023.pdf)
- **GENIE**: users may not identify or contact participants and may not redistribute without written AACR permission. — [GENIE FAQ](https://www.aacr.org/professionals/research/aacr-project-genie/aacr-project-genie-frequently-asked-questions/)
- **MSK-CHORD**: CC BY-NC-ND 4.0. — [MSK Data Catalog](https://datacatalog.mskcc.org/dataset/11458)
- **GDC**: open masked somatic MAFs may be freely distributed. VCF and BAM files are controlled through dbGaP. — [GDC MAF format](https://docs.gdc.cancer.gov/Data/File_Formats/MAF_Format)
- **Hartwig and TRACERx**: both require a signed licence or Data Access Agreement and approval by their access boards. — [Hartwig](https://www.hartwigmedicalfoundation.nl/en/data/database/); [TRACERx, Nature](https://www.nature.com/articles/s41586-023-05729-x)
- **DepMap**: CC BY 4.0. **BioGRID ORCS**: MIT. — [DepMap Figshare](https://figshare.com/articles/dataset/DepMap_22Q4_Public/21637199); [BioGRID ORCS](https://orcs.thebiogrid.org/)

### Inferences
- Under GENIE's no-redistribution rule, pushing GENIE rows, or per-patient derived records, to the project's public, permanent chain would be redistribution. Even a hash of a single record is risky (see the privacy section). A safe pattern is to put on chain only a dataset-level fingerprint (e.g. SHA-256 of the downloaded release file plus the release name), a citation and the licence. That pattern matches the project's existing "fingerprints only" rule.
- For CC BY-NC-ND data (MSK-CHORD), derived per-patient data should not be republished. Aggregate statistics and publications are the normal accepted use, but read the licence text.

### Gaps
- I did not fetch the full text of the dbGaP Code of Conduct or the EGA/DAC agreements. The rules on time limits, destruction at project close and annual reporting are not quoted here.

## File formats and typical sizes for a small Python tool

### Takeaway
The open tiers come as tab-separated MAF, VCF, gene-expression matrices (counts/TPM) and CSV dependency matrices. All of these can be parsed with the Python standard library or pandas. Only the controlled tiers ship BAM/CRAM in the 10–100+ GB per genome range, which a small local tool should not handle.

### Cited Findings
- GDC MAF is a tab-delimited format with a documented column specification. Open masked somatic MAFs are filtered of germline calls. — [GDC MAF Format v1.0.0](https://docs.gdc.cancer.gov/Data/File_Formats/MAF_Format)
- GENIE releases on Synapse contain mutation (MAF), copy-number, structural-variant and clinical files, described in each release's data guide. — [GENIE 19.0 data guide](https://www.aacr.org/wp-content/uploads/2026/02/19.0_public_data_guide.pdf)
- The POG570 open download is a small-mutation catalogue plus expression TPMs. — [Nature Cancer](https://www.nature.com/articles/s43018-020-0050-6)
- DepMap CRISPRGeneEffect is a matrix with models as rows and genes as columns. — [DepMap Bioconductor manual](https://www.bioconductor.org/packages//release/data/experiment/manuals/depmap/man/depmap.pdf)

### Inferences
- Use cases in a local twin:
  - Reference FASTA (GRCh38): compare against it.
  - MAF/VCF: per-patient variant sets "before" and "after". Compute variants gained or lost, variant allele frequency (VAF) shift and changes in tumour mutational burden (TMB).
  - Expression matrices: compute pre/post differential expression.
- Rough sizes. These are order-of-magnitude estimates, not verified in this pass:
  - GENIE MAF: hundreds of MB.
  - GEO count matrices: a few MB.
  - DepMap gene effect CSV: hundreds of MB.
  - A tumour WGS BAM: about 100 GB.

### Gaps
- Exact byte sizes per release were not verified.

## Privacy: identifiability of genomic data, and GDPR/HIPAA/NIH positions on public ledgers and hashes

### Takeaway
Individual-level genomic data is identifiable:
- NIH explicitly says that de-identified genomic data can be re-identified.
- Gymrek 2013 recovered surnames from genomes.
- Under the EDPB's July 2026 blockchain guidelines (v2.0), even a hash of personal data is personal data. Personal data should not be stored on-chain, and erasure must stay possible.

So the chain should hold only dataset-level fingerprints and public metadata, never per-person genotypes or hashes of them.

### Cited Findings
- The 2014 NIH GDS policy acknowledges that genomic data can be re-identified even when de-identified to HIPAA and Common Rule standards. NIH therefore relies on data use agreements and Certificates of Confidentiality. — [NIH GDS Policy overview](https://osp.od.nih.gov/wp-content/uploads/NIH_GDS_Policy_Overview.pdf); [Federal Register, Final GDS Policy](https://www.federalregister.gov/documents/2014/08/28/2014-20385/final-nih-genomic-data-sharing-policy)
- Gymrek et al. (Science 2013;339:321–324) took Y-STR haplotypes from personal genomes and queried genealogy databases. They inferred surnames with about 12% success for 911 men, and combined with age and state this could identify individuals. — [Semantic Scholar](https://www.semanticscholar.org/paper/Identifying-Personal-Genomes-by-Surname-Inference-Gymrek-McGuire/c5a4e5024a90aeae16298d8228d67dd9c9182080); [Nature Rev Genet commentary](https://www.nature.com/articles/nrg3439)
- **EDPB Guidelines 02/2025** on blockchain:
  - First adopted on 8 April 2025; version 2.0 adopted on 7 July 2026.
  - They advise against storing personal data on-chain. Where something must go on-chain, it should be a salted or keyed hash, with the data and the key or salt kept off-chain.
  - The hash itself is still personal data.
  - Controllers must be able to make on-chain data effectively anonymous when someone asks for erasure, e.g. by deleting the key or off-chain data.
  - Technical impossibility does not excuse non-compliance.
  - — [EDPB Guidelines v2 PDF](https://www.edpb.europa.eu/system/files/2026-07/edpb_guidelines_202502_blockchain_v2_en.pdf); [Bird & Bird 2026](https://www.twobirds.com/en/insights/2026/netherlands/edpb-adopts-final-guidelines-on-blockchain-and-personal-data-a-practical-guide-for-organisations); [EDPB v1 PDF](https://www.edpb.europa.eu/system/files/2025-04/edpb_guidelines_202502_blockchain_en.pdf)

### Inferences
- Genetic data is a GDPR Article 9 "special category". That is standard GDPR text and was not fetched in this pass.
- Combined with the EDPB guidance, an unkeyed SHA-256 of an individual's variant list on a permanent public chain is (a) personal data and (b) impossible to erase. It would therefore conflict with GDPR for EU data subjects. For example, Hartwig is Dutch and TRACERx is UK, where UK GDPR applies.
- The project's current design already fits the EDPB-recommended pattern: keyed digests only on the ledger, raw data in the encrypted local vault, and enforcement in `research_provenance.personal_information`. Two safe things to put on chain are a dataset-release fingerprint and a keyed digest of a local analysis result. Destroying the key must make that digest unlinkable.
- Under HIPAA, genomic sequence is not one of the 18 Safe Harbor identifiers. NIH's position is still that genomic data can be re-identified, so "HIPAA-de-identified" should not be treated as "anonymous". This is inferred from the NIH statement above. I did not fetch the HIPAA text itself.

### Gaps
- I did not fetch HHS/OCR guidance on whether genomic data counts as PHI or on hashing it.
- I found no regulator statement specific to cancer genomic data on public ledgers. The conclusion rests on the general EDPB blockchain guidance plus NIH re-identification statements.
- I did not check the ICO's (UK) view on hashes as pseudonymous data.
