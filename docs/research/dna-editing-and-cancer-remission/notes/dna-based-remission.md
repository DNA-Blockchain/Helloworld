# How DNA-based cancer research (other than CRISPR editing) bears on remission: ctDNA/MRD, genomic profiling, personalized neoantigen vaccines (as of 2 October 2026)

Scope note: human clinical data only. Each result carries the year it was reported. These are research notes, not medical advice. Searches ran on 2026-10-02. Several paywalled primary papers (Nature Medicine GALAXY 2024, Medscape 2026) could not be opened in full, so some figures come from abstracts, press releases or trade-press summaries, and those are marked as such.

## ctDNA / MRD: what the tests measure, lead time over imaging, trials that use ctDNA to guide treatment, false-negative limits

### Takeaway
After surgery, tumor-informed ctDNA is the strongest single prognostic marker in colorectal cancer. ctDNA-positive patients have 3-year DFS of about 17% versus about 84% for ctDNA-negative patients (GALAXY), and ctDNA detects relapse a median of roughly 4.7 months (142 days) before imaging. Randomized trials, however, have shown only partial clinical utility. DYNAMIC (stage II, 2022) safely cut chemotherapy use. DYNAMIC-III (stage III, 2025) did not formally prove de-escalation was non-inferior, and escalation gave no benefit. ALTAIR (2026) found that treating ctDNA-positive relapse risk with trifluridine/tipiracil did not significantly improve DFS. A single post-operative draw misses about 25–33% of the patients who later relapse.

### Cited Findings
**What the tests measure**
- clonoSEQ (Adaptive Biotechnologies) is a blood-cancer MRD test. It sequences the patient's clonal immunoglobulin/T-cell receptor rearrangements, usually in bone marrow, and measures MRD down to about 1 cancer cell in 1,000,000 (<10^-6). Patients reaching MRD <10^-6 have more durable responses and better EFS/OS than those with MRD ≥10^-4. — [FDA review DEN170080](https://www.accessdata.fda.gov/cdrh_docs/reviews/DEN170080.pdf); [ASH Clinical News: FDA approves NGS-based test for ALL or MM](https://ashpublications.org/ashclinicalnews/news/4122/FDA-Approves-NGS-Based-Test-for-Patients-With-ALL); [FDA 510(k) review K200009](https://www.accessdata.fda.gov/cdrh_docs/reviews/K200009.pdf); [clonoSEQ CLL page](https://www.clonoseq.com/chronic-lymphocytic-leukemia/)
  - Regulatory: FDA de novo authorization (DEN170080) for ALL and multiple myeloma, later extended to CLL through 510(k) K200009. I took the indications from the ASH News headline and the clonoSEQ CLL page. I did not open the FDA documents to confirm the dates (2018 and 2020 come from document numbering and background knowledge, so verify them).
- Signatera (Natera) is a tumor-informed ctDNA assay. It is built from the patient's own tumor sequencing and then tracks those patient-specific variants in plasma. In CIRCULATE-Japan/GALAXY, stage II–III CRC:
  - A single post-surgery test had 67.6% sensitivity for later recurrence. Updated data showed 75% detection with one draw at 4 weeks after surgery, and serial monitoring raised detection to 88–93% ([Natera / SSO plenary press release, 2023](https://www.prnewswire.com/news-releases/natera-announces-updated-signatera-mrd-data-from-circulate-japan-presented-in-plenary-talk-at-the-society-of-surgical-oncology-conference-and-activation-of-circulate-us-trial-301506387.html); [Natera CIRCULATE-Japan release](https://www.natera.com/company/news/landmark-circulate-japan-study-shows-nateras-signatera-mrd-test-is-predictive-of-chemotherapy-benefit-in-colorectal-cancer-2/)). The figures are from company releases.
  - Lead time: the median from the first ctDNA-positive result after surgery to radiographic recurrence was 142 days ([GALAXY update, JCO 2023 ASCO abstract 3521](https://ascopubs.org/doi/abs/10.1200/JCO.2023.41.16_suppl.3521); [Natera](https://www.natera.com/company/news/landmark-circulate-japan-study-shows-nateras-signatera-mrd-test-is-predictive-of-chemotherapy-benefit-in-colorectal-cancer-2/)).
  - Prognosis: 36-month DFS was 16.7% if ctDNA-positive after surgery versus 83.5% if negative. Post-op ctDNA positivity was the most significant prognostic factor for DFS ([Natera](https://www.natera.com/company/news/landmark-circulate-japan-study-shows-nateras-signatera-mrd-test-is-predictive-of-chemotherapy-benefit-in-colorectal-cancer-2/)).
  - The expanded cohort (2024) had n = 2,240 with stage II–III resectable CRC and 23-month median follow-up (Nakamura et al., Nature Medicine, published 16 Sep 2024). MRD predicted survival and adjuvant chemotherapy benefit, and ctDNA-positive patients who cleared ctDNA on adjuvant chemo had lower recurrence risk. After propensity adjustment, adjuvant chemo gave a survival benefit in ctDNA-positive stage II and III patients ([Nature Medicine 2024](https://www.nature.com/articles/s41591-024-03254-6); [National Cancer Center Japan press release](https://www.ncc.go.jp/en/information/press_release/2024/0917_1/index.html)). Exact HRs could not be read (paywall).
  - GALAXY also showed that post-surgery Signatera status predicts overall survival ([Natera ESMO release](https://www.natera.com/company/news/first-of-its-kind-colorectal-cancer-data-from-prospective-galaxy-study-released-at-esmo-demonstrates-signateras-ability-to-predict-overall-survival/)).
- Guardant Reveal (Guardant Health) is a tumor-uninformed (plasma-only) assay that combines genomic and epigenomic signals.
  - COSMOS study (Clinical Cancer Research, 2024): longitudinal sensitivity for recurrence was 81% (95% CI 58.1–94.6%) in stage ≥II colon cancer and 60% (95% CI 36.1–80.9%) in rectal cancer. Specificity was 98.2% (95% CI 97.3–98.9%) across 1,461 post-treatment samples — [Targeted Oncology](https://www.targetedonc.com/view/guardant-reveal-ctdna-test-shows-high-sensitivity-in-colorectal-cancer); [Guardant press release 2024](https://investors.guardanthealth.com/press-releases/press-releases/2024/Guardant-Health-COSMOS-Study-Published-in-Clinical-Cancer-Research-Validates-Utility-of-Guardant-Reveal-Liquid-Biopsy-Test-for-Predicting-Recurrence-in-Colorectal-Cancer/default.aspx)
  - A tumor-uninformed assay subset was also analyzed inside GALAXY — [Tempus publication page](https://www.tempus.com/publications/a-tumor-uninformed-ctdna-assay-detecting-mrd-in-patients-with-resected-stage-ii-or-iii-colorectal-cancer-predicts-recurrence-subset-analysis-from-the-galaxy-study-in-circulate-japan/)

**Randomized trials where ctDNA guided treatment**
- DYNAMIC (Tie et al., NEJM 2022; stage II colon cancer; randomized 2:1 to ctDNA-guided or standard management):
  - Chemotherapy was given to 15% of the ctDNA-guided arm versus 28% of the standard arm.
  - 2-year RFS was 93.5% versus 92.4%, i.e. non-inferior.
  - 3-year RFS was 86.4% in ctDNA-positive patients treated with chemo and 92.5% in ctDNA-negative patients left untreated.
  - Sources: [NEJM](https://www.nejm.org/doi/pdf/10.1056/nejmoa2200075); [ASCO Post 2022](https://ascopost.com/issues/july-10-2022/circulating-tumor-dna-guided-approach-to-treating-stage-ii-colon-cancer/)
- DYNAMIC-III (Nature Medicine 2025, presented at ESMO 2025; phase 2/3, stage III colon cancer; n = 1,002 randomized in Australia, NZ and Canada):
  - Of 968 evaluable patients, 702 (72.5%) were ctDNA-negative. At 47 months median follow-up, 3-year RFS was 87% for ctDNA-negative versus 49% for ctDNA-positive patients (P < 0.001).
  - De-escalation in ctDNA-negative patients did not meet non-inferiority: 3-year RFS was 85.3% versus 88.1% (difference −2.8%, 97.5% lower CI −8.0%).
  - The ctDNA-guided arm used much less oxaliplatin (34.8% vs 88.6%), had fewer grade ≥3 adverse events (6.2% vs 10.6%) and fewer hospitalizations (8.5% vs 13.2%).
  - Patients with persistent ctDNA after treatment had 3-year RFS of 14% versus 79%.
  - Escalated chemotherapy in ctDNA-positive patients gave no RFS benefit.
  - Sources: [Nature Medicine](https://www.nature.com/articles/s41591-025-04030-w); [GI Cancer Trials](https://gicancer.org.au/news/dynamic-iii-trial-results/); [ASCO Post Nov 2025](https://ascopost.com/issues/november-25-2025/postsurgical-ctdna-testing-in-stage-iii-colon-cancer-for-treatment-de-escalation/); [ESMO Daily Reporter: "not ready for prime time?"](https://dailyreporter.esmo.org/esmo-congress-2025/gastrointestinal-cancers/ctdna-guided-adjuvant-chemotherapy-in-colon-cancer-not-ready-for-prime-time); [Targeted Oncology](https://www.targetedonc.com/view/ctdna-guided-chemo-escalation-fails-to-improve-rfs-in-colon-cancer)
- ALTAIR (CIRCULATE-Japan, EPOC1905; randomized, double-blind phase 3; Nature Medicine 2026):
  - Design: 243 patients who became ctDNA-positive during surveillance after adjuvant therapy were randomized from July 2020 to June 2023 to trifluridine/tipiracil (n = 122) or placebo (n = 121).
  - The primary endpoint was not met; DFS was not significantly prolonged.
  - Median DFS was 9.30 versus 5.55 months. 12-month DFS was 31.8% versus 26.8%, and 24-month DFS 16.9% versus 14.5%.
  - Stage IV and MSS subgroups showed benefit. The treatment arm had high rates of neutropenia and leukopenia.
  - Sources: [Nature Medicine 2026](https://www.nature.com/articles/s41591-026-04428-0); [Targeted Oncology](https://www.targetedonc.com/view/trifluridine-tipiracil-demonstrates-numerically-improved-dfs-after-resection-in-ctdna-crc); [OncLive](https://www.onclive.com/view/adjuvant-trifluridine-tipiracil-benefit-is-limited-to-select-subgroups-in-mrd-crc)
- CIRCULATE-US had been activated by 2023 (per Natera) — [PR Newswire](https://www.prnewswire.com/news-releases/natera-announces-updated-signatera-mrd-data-from-circulate-japan-presented-in-plenary-talk-at-the-society-of-surgical-oncology-conference-and-activation-of-circulate-us-trial-301506387.html). I found no results.

**False-negative limits**
- A single landmark draw misses about 25–32% of patients who later recur in stage II–III CRC (67.6–75% sensitivity). Serial testing raises detection to 88–93% — [Natera](https://www.prnewswire.com/news-releases/natera-announces-updated-signatera-mrd-data-from-circulate-japan-presented-in-plenary-talk-at-the-society-of-surgical-oncology-conference-and-activation-of-circulate-us-trial-301506387.html)
- Sensitivity depends on the site of recurrence and the tumor type. Guardant Reveal reached 81% in colon cancer but only 60% in rectal cancer — [Targeted Oncology](https://www.targetedonc.com/view/guardant-reveal-ctdna-test-shows-high-sensitivity-in-colorectal-cancer)
- In DYNAMIC-III, ctDNA-negative patients who received less treatment still had 85.3% 3-year RFS, so about 15% relapsed despite a negative test — [Nature Medicine 2025](https://www.nature.com/articles/s41591-025-04030-w)

### Inferences
- ctDNA status has excellent prognostic value. Its predictive value, meaning whether changing therapy based on it changes outcomes, is established only for de-escalation in stage II colon cancer (DYNAMIC). In stage III, the de-escalation result was close but not proven (DYNAMIC-III). Escalation or salvage therapy for ctDNA-positive patients has failed so far (DYNAMIC-III escalation, ALTAIR). The limit is the lack of effective therapy for molecular relapse, not the ability to detect it.
- A lead time of about 4–5 months is a window to act. It translates into better remission or survival only if an effective intervention exists. This motivates combining MRD detection with vaccines or other targeted interventions (see the BNT122 colorectal trial below, which also failed).
- "ctDNA-negative" should be read as "lower risk", not "cured", especially after a single draw.

### Gaps
- I could not find exact clinical sensitivity or specificity for clonoSEQ from FDA labeling. I also did not verify the dates of FDA actions on the clonoSEQ indications from the FDA documents themselves.
- I did not find FDA approval status for Signatera or Guardant Reveal. They are generally understood to be laboratory-developed tests with Medicare coverage, but I found no source for that in this session.
- GALAXY 2024 hazard ratios (e.g., for DFS in ctDNA-positive vs negative patients, and adjuvant chemo benefit in ctDNA-positive patients) were behind a paywall.
- I found no DYNAMIC 5-year update and no CIRCULATE-US or CIRCULATE-NA (NRG-GI008) results as of October 2026.
- I gathered no data on ctDNA MRD outside CRC (breast, lung, bladder, e.g. IMvigor011) or on lead time in those cancers.

## Precision oncology: share of patients with actionable mutations and benefit; example targeted therapies

### Takeaway
In NCI-MATCH, tumor DNA sequencing found an "actionable" alteration in 37.6% of patients, but only 17.8% were assigned to a matched therapy. Most arms produced modest response rates, so the share of all screened patients who achieve a durable response is small (single-digit percent, an inference). Some alterations are exceptions with large effects, such as BRAF V600E treated with dabrafenib + trametinib (ORR 38% across tumor types, median duration of response 25.1 months), which led to a tumor-agnostic FDA approval.

### Cited Findings
- **NCI-MATCH (EAY131; JCO 2020, Flaherty et al.):**
  - Molecular profiling succeeded in 93.0% of specimens, and 37.6% had an actionable alteration.
  - 17.8% were assigned to a treatment arm; 26.4% could have been assigned if every subprotocol had been open at once.
  - Of those assigned, 70% (n = 686) enrolled and were treated.
  - Actionability varied by histology, from >35% in urothelial cancer to <6% in pancreatic and small-cell lung cancer.
  - 11.9% of specimens had multiple actionable mutations, and 71.3% had resistance-conferring mutations.
  - Sources: [JCO](https://ascopubs.org/doi/10.1200/JCO.19.03010); [PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7676882/)
- NCI-MATCH set its "promising" threshold at an ORR of 5/31 (16%), and most arms responded at lower rates — [JNCI: lessons for genomic trial design](https://academic.oup.com/jnci/article/112/10/1021/5699915); [Tumor-specific activity of precision medicines in NCI-MATCH (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10081392/)
- **NCI-MATCH Subprotocol H (BRAF V600E, dabrafenib + trametinib):**
  - Confirmed ORR was 37.9% (90% CI 22.9–54.9%; p < .0001 against a null of 5%), and the disease control rate 75.9%.
  - Median duration of response was 25.1 months, with responses in 7 different tumor types.
  - The combination became the first BRAF/MEK combination with a tumor-agnostic approval for BRAF V600E solid tumors.
  - Sources: [OncLive](https://www.onclive.com/view/dabrafenib-plus-trametinib-elicits-encouraging-responses-in-braf-v600e-mutant-tumors); [PubMed 32758030](https://pubmed.ncbi.nlm.nih.gov/32758030/); [Updated results (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12810769/); [ECOG-ACRIN blog](https://blog-ecog-acrin.org/nci-match-precision-medicine-trial-leads-to-fda-drug-approval-for-braf-v600e-mutated-tumors/); [ROAR trial, Nature Medicine 2023](https://www.nature.com/articles/s41591-023-02321-8)
- **ASCO TAPUR (NCT02693535; phase 2 basket):**
  - 2025 results for olaparib in BRCA1/2-altered solid tumors: disease control rates were 41–69% across cohorts, rejecting the 15% null in every cohort. Of 119 patients, 36 had grade 3–4 treatment-related adverse events or SAEs ([JCO Precision Oncology 2025](https://ascopubs.org/doi/10.1200/PO-25-00649)).
  - Olaparib in ATM-altered tumors met the bar only in the lung and histology-pooled cohorts, not in colorectal or pancreatic ([JCO PO 2025](https://ascopubs.org/doi/10.1200/PO-25-00716)).
  - A separate prevalence-of-targetable-alterations analysis was published in [npj Precision Oncology 2025](https://www.nature.com/articles/s41698-025-00962-1).

### Inferences
- Multiplying the NCI-MATCH figures gives assignment (17.8%) × treatment (70%) × typical ORR (≤16–38%). By that arithmetic, roughly 2–5% of all screened patients had an objective response. This is a rough inference, not a reported figure.
- The same DNA alteration responds differently in different tissues (TAPUR ATM: lung yes, pancreatic and CRC no). The tumor DNA sequence alone does not determine whether a drug will work.
- Targeted therapy in advanced disease mostly gives response or disease control rather than durable remission. Its biggest remission effects are in the adjuvant and first-line settings for strong drivers (e.g., EGFR, ALK, BRAF), which I did not source in this session.

### Gaps
- I did not retrieve a TAPUR-wide aggregate (share of all enrolled patients who benefited).
- I gathered no sourced figures for flagship DNA-matched therapies in early-stage disease (e.g., osimertinib in ADAURA, alectinib in ALINA, larotrectinib for NTRK fusions) or for population-level actionability from large registries (e.g., MSK-IMPACT, OncoKB levels).
- I did not search for FDA-approved companion diagnostics (FoundationOne CDx, Guardant360 CDx) or their indications.

## Personalized neoantigen vaccines: mRNA-4157/V940 (intismeran autogene) and autogene cevumeran

### Takeaway
Intismeran autogene (Moderna/Merck) is the first individualized neoantigen therapy with a positive phase 3. INTerpath-001, announced 19 August 2026, met its primary endpoint of RFS and its key secondary endpoint of DMFS when added to pembrolizumab in resected stage IIB–IV melanoma. In phase 2b KEYNOTE-942, the 5-year HR for recurrence or death was 0.51. The hazard ratios from INTerpath-001 had not been released as of October 2026, and the therapy is not yet approved. BioNTech/Genentech's autogene cevumeran has mixed results. In pancreatic cancer, 8 of 16 phase 1 patients mounted vaccine T cells, 7 of those 8 were alive at about 6 years (AACR 2026), and phase 2 IMcode003 is recruiting. The colorectal trial in ctDNA-positive patients (vaccine alone) was stopped in August 2026 after crossing the futility boundary, with a numerical overall-survival imbalance.

### Cited Findings
**Intismeran autogene (mRNA-4157 / V940), Moderna + Merck**
- Construct: one synthetic mRNA encoding up to 34 neoantigens, tailored to each patient's tumor — [Merck release, 19 Aug 2026](https://www.merck.com/news/merck-and-moderna-announce-phase-3-interpath-001-trial-of-intismeran-autogene-plus-keytruda-met-endpoints-of-recurrence-free-survival-rfs-and-distant-metastasis-free-survival-dmfs-in-patient/)
- **KEYNOTE-942 / mRNA-4157-P201 (NCT03897881), phase 2b, resected high-risk melanoma:**
  - 18-month RFS was 78.6% (95% CI 69.0–85.6%) with the vaccine plus pembrolizumab versus 62.2% (46.9–74.3%) with pembrolizumab alone.
  - HR 0.561 (95% CI 0.309–1.017; 1-sided p = 0.0266), a 44% lower risk of recurrence or death (Lancet, 17 Feb 2024; Weber et al.).
  - Sources: [OncLive](https://www.onclive.com/view/adjuvant-mrna-4157-plus-pembrolizumab-improves-rfs-in-resected-high-risk-melanoma); [Lancet PDF via UPenn](https://www.med.upenn.edu/cstr/assets/user-content/Fall%202025/Individualised%20neoantigen%20therapy%20mRNA-4157%20(V940)%20plus%20pembrolizumab%20versus%20pembrolizumab%20monotherapy%20in%20resected%20melanoma%20(KEYNOTE-942)-%20a%20randomised,%20phase%202b%20study.pdf); [ClinicalTrials.gov](https://clinicaltrials.gov/study/NCT03897881)
- The FDA granted Breakthrough Therapy designation in February 2023 — [OncLive/Targeted Oncology summary](https://www.targetedonc.com/view/improved-rfs-in-resected-melanoma-with-mrna-vaccine-pembrolizumab)
- KEYNOTE-942 5-year follow-up (ASCO 2026):
  - Recurrence or death: HR 0.51 (95% CI 0.294–0.887), a 49% risk reduction.
  - Distant metastasis or death: HR 0.411 (95% CI 0.200–0.843), a 59% risk reduction.
  - Source: [Merck release](https://www.merck.com/news/merck-and-moderna-announce-phase-3-interpath-001-trial-of-intismeran-autogene-plus-keytruda-met-endpoints-of-recurrence-free-survival-rfs-and-distant-metastasis-free-survival-dmfs-in-patient/)
- **INTerpath-001 (V940-001, NCT05933577), phase 3:**
  - Design: 1,137 patients with resected stage IIB–IV cutaneous melanoma, randomized 2:1 and double-blind. Intismeran 1 mg every 3 weeks for up to 9 doses plus pembrolizumab 400 mg every 6 weeks for up to 9 cycles, versus placebo plus pembrolizumab, for about 1 year.
  - Results: met RFS (primary) and DMFS (key secondary) at a prespecified interim analysis, with no new safety signals. No HR was disclosed; data will go to a medical meeting.
  - Merck and Moderna describe it as the first positive phase 3 for an individualized neoantigen therapy and for any mRNA cancer therapy.
  - Sources: [Merck](https://www.merck.com/news/merck-and-moderna-announce-phase-3-interpath-001-trial-of-intismeran-autogene-plus-keytruda-met-endpoints-of-recurrence-free-survival-rfs-and-distant-metastasis-free-survival-dmfs-in-patient/); [ClinicalTrials.gov](https://clinicaltrials.gov/study/NCT05933577); [CancerNetwork](https://www.cancernetwork.com/view/novel-cancer-vaccine-meets-primary-secondary-end-points-in-resected-melanoma)
- The INTerpath program has 9 phase 2/3 trials (melanoma, NSCLC, bladder, RCC) plus phase 1 studies in pancreatic and gastric cancer. One example is INTerpath-012 (NCT06961006) — [Merck](https://www.merck.com/news/merck-and-moderna-announce-phase-3-interpath-001-trial-of-intismeran-autogene-plus-keytruda-met-endpoints-of-recurrence-free-survival-rfs-and-distant-metastasis-free-survival-dmfs-in-patient/); [ClinicalTrials.gov](https://clinicaltrials.gov/study/NCT06961006)

**Autogene cevumeran (BNT122 / RO7198457), BioNTech + Genentech**
- Pancreatic phase 1 (MSK; Rojas et al., Nature 2023; Sethna et al., Nature 2025):
  - Regimen: surgery, then atezolizumab, autogene cevumeran (uridine mRNA–lipoplex) and mFOLFIRINOX.
  - At 3.2 years median follow-up, the 8 responders with vaccine-induced T cells had longer RFS than non-responders, whose median RFS was 13.4 months (P = 0.007). Six of the 8 responders were cancer-free.
  - Vaccine-induced CD8+ clones had an estimated average lifespan of 7.7 years (range 1.5 to about 100), and about 20% of clones had multi-decade lifespans.
  - Sources: [Nature 2025](https://www.nature.com/articles/s41586-024-08508-4); [Nature 2023](https://www.nature.com/articles/s41586-023-06063-y); [BioNTech 2024 release](https://www.biontech.com/int/en/home/mediaroom/news/press-releases/2024/04/three-year-phase-1-follow-data-mrna-based-individualized.html); [NCI Cancer Currents 2025](https://www.cancer.gov/news-events/cancer-currents-blog/2025/neoantigen-vaccine-pancreatic-kidney-cancer)
- About 6-year follow-up (AACR 2026, Balachandran): 7 of the 8 responders (87.5%) were alive. The vaccine was designed from each patient's unique tumor DNA changes — [Medscape 2026](https://www.medscape.com/viewarticle/pancreatic-cancer-vaccine-still-shows-promise-6-years-out-2026a1000d2b). Only the search summary was available (paywall); non-responder survival at 6 years was not retrieved. See also [MSK](https://www.mskcc.org/news/can-mrna-vaccines-fight-pancreatic-cancer-msk-clinical-researchers-are-trying-find-out).
- IMcode003 (NCT05968326; phase 2, resected PDAC): autogene cevumeran + atezolizumab + mFOLFIRINOX versus mFOLFIRINOX alone. It was recruiting and "continues as planned" as of August 2026 — [ClinicalTrials.gov](https://clinicaltrials.gov/study/NCT05968326); [BioNTech statement, 28 Aug 2026](https://www.biontech.com/int/en/home/mediaroom/news/statements/2026/08/BioNTech-Provides-Update-on-Phase-2-Clinical-Trial-of-Autogene-Cevumeran-in-Resected-Colorectal-Cancer.html)
- **BNT122-01 (NCT04486378), colorectal, terminated 28 Aug 2026:**
  - Design: ctDNA-positive patients with resected high-risk stage II or stage III CRC, given vaccine alone as adjuvant therapy versus watchful waiting.
  - Stopped by DSMB recommendation after "a numerical imbalance in overall survival between treatment arms". The futility boundary had been crossed in October 2025, and there was no safety concern. BioNTech released no efficacy figures.
  - Sources: [BioNTech](https://www.biontech.com/int/en/home/mediaroom/news/statements/2026/08/BioNTech-Provides-Update-on-Phase-2-Clinical-Trial-of-Autogene-Cevumeran-in-Resected-Colorectal-Cancer.html); [CancerNetwork](https://www.cancernetwork.com/view/autogene-cevumeran-trial-terminated-in-resected-colorectal-cancer)

### Inferences
- Positive results so far come from combining a neoantigen vaccine with a PD-1/PD-L1 inhibitor in a population with high immunogenicity or low disease burden (resected melanoma, the pancreatic responders). Vaccine alone in ctDNA-positive CRC failed. This suggests neoantigen vaccines work as amplifiers of checkpoint blockade rather than standalone remission therapy. This is an inference; the BNT122-01 data are not public.
- The pancreatic data come from 16 patients and compare responders with non-responders, not randomized arms. The difference could reflect host immune fitness as well as the vaccine. IMcode003 is the randomized test.
- Earliest plausible approval for intismeran would follow regulatory filing on INTerpath-001 data. No filing or approval was confirmed as of October 2026.

### Gaps
- The INTerpath-001 HR, RFS rates, and filing timeline were not disclosed as of 2 Oct 2026.
- I did not verify whether EMA PRIME or other designations exist.
- I have no exact 6-year RFS for non-responders in the pancreatic trial, and I could not check IMcode003 enrollment numbers or readout timing.
- Other personalized vaccine platforms (e.g., Gritstone, the Neo-Vax kidney cancer data mentioned in the NCI blog, and UK NHS Cancer Vaccine Launch Pad enrollment) were not researched in depth.

## The "digital copy" of a patient's tumor DNA: how sequencing data flows into vaccine or drug choice

### Takeaway
Yes. In all three workflows, the sequenced tumor (and usually matched normal) DNA becomes a digital record, and bioinformatics turns that record into a decision. For MRD, the patient's variant list becomes a bespoke assay. For precision oncology, the variant calls are matched to drugs and trial arms through rules. For vaccines, the variant calls are ranked into neoantigens and encoded into an mRNA construct. The sources confirm the inputs and outputs: tumor-informed tracking, "up to 34 neoantigens", and "unique changes in tumor DNA". The internal algorithms are proprietary and are not described in detail in the sources gathered here.

### Cited Findings
- Tumor-informed MRD (Signatera) is built from the individual patient's tumor sequencing and then tracks that patient's variants in plasma. Tumor-uninformed assays (Guardant Reveal) need no tumor tissue — [Natera patient page](https://www.natera.com/oncology/signatera-advanced-cancer-detection/patients/crc-early-stage-cancer/); [Tempus/GALAXY tumor-uninformed subset](https://www.tempus.com/publications/a-tumor-uninformed-ctdna-assay-detecting-mrd-in-patients-with-resected-stage-ii-or-iii-colorectal-cancer-predicts-recurrence-subset-analysis-from-the-galaxy-study-in-circulate-japan/)
- clonoSEQ first identifies the patient's dominant clonal immune-receptor sequences at diagnosis and then counts them in later samples to give a per-million cell quantity — [FDA DEN170080](https://www.accessdata.fda.gov/cdrh_docs/reviews/DEN170080.pdf)
- NCI-MATCH sequenced tumor biopsies centrally, with 93% assay success. Rules then assigned each "actionable" alteration to a subprotocol drug, and exclusion rules (e.g., co-occurring resistance mutations) cut assignment from 37.6% to 17.8% — [JCO 2020](https://ascopubs.org/doi/10.1200/JCO.19.03010)
- Intismeran is a single mRNA encoding up to 34 patient-specific neoantigens "tailored to the unique biology of an individual patient's tumor" — [Merck 2026](https://www.merck.com/news/merck-and-moderna-announce-phase-3-interpath-001-trial-of-intismeran-autogene-plus-keytruda-met-endpoints-of-recurrence-free-survival-rfs-and-distant-metastasis-free-survival-dmfs-in-patient/)
- Autogene cevumeran is personalized from each patient's tumor DNA changes and delivered as an mRNA-lipoplex — [Medscape 2026](https://www.medscape.com/viewarticle/pancreatic-cancer-vaccine-still-shows-promise-6-years-out-2026a1000d2b); [Nature 2023](https://www.nature.com/articles/s41586-023-06063-y)

### Inferences
Concrete pipeline, combining the sources above with standard practice. Steps marked (standard practice) are not individually sourced here.
1. **Sample:** resected tumor tissue plus a normal sample (blood) (standard practice).
2. **Sequencing:** whole-exome or panel DNA sequencing of tumor and normal, and for vaccines usually tumor RNA-seq to confirm expression (standard practice). This produces the patient's "digital tumor genome" (FASTQ, then BAM, then VCF of somatic variants).
3. **Bioinformatics branch A, MRD:** select a set of clonal, patient-specific somatic variants and design patient-specific PCR/NGS primers. Serial plasma draws then report ctDNA positive or negative, and sometimes mean tumor molecules per mL (tumor-informed; sourced in concept). Treatment decisions follow trial rules such as DYNAMIC's.
4. **Bioinformatics branch B, drug matching:** annotate variants against an actionability knowledge base and match them to a drug or trial arm, applying exclusion rules for resistance co-mutations (NCI-MATCH logic, sourced).
5. **Bioinformatics branch C, vaccine design:** call somatic mutations, predict the patient's HLA type, predict which mutant peptides bind and are expressed, rank them, and encode the top neoantigens (≤34 for intismeran) into one mRNA sequence. GMP manufacture of that mRNA follows. The ranking-algorithm specifics are proprietary (standard practice plus the sourced count).
6. **Feedback loop:** ctDNA from branch A can be used to select patients for branch C (BNT122-01 enrolled ctDNA-positive patients) or to monitor response. This is the closest existing analogue of a running "digital twin" of the tumor's DNA, though no source calls it a digital twin.
- The digital record is clinical-grade, identifiable genomic data. Storing or sharing it is a privacy matter. For this repository, that means a fingerprint at most on any chain, never sequence data (inference tied to the project's own rules).

### Gaps
- I found no source in this session giving vendor-specific pipeline details: Signatera's number of tracked variants (often cited as 16), Moderna's or BioNTech's neoantigen-ranking algorithms, or needle-to-needle manufacturing turnaround times (often cited at about 6 weeks). These are unverified here and should not be quoted without a source.
- I found no formal regulatory definition of a "digital twin" of tumor DNA in these workflows.

## Limits and open questions

### Takeaway
DNA-based tools now detect residual disease reliably and months early. Turning that detection into more remissions is the unsolved step: treatments triggered by ctDNA have mostly failed or are unproven, matched targeted therapy helps a minority, and personalized vaccines have one positive phase 3 (in melanoma) with effect sizes not yet public.

### Cited Findings
- De-escalation guided by ctDNA in stage III colon cancer did not meet non-inferiority, and escalation did not help — [Nature Medicine 2025](https://www.nature.com/articles/s41591-025-04030-w); [ESMO Daily Reporter](https://dailyreporter.esmo.org/esmo-congress-2025/gastrointestinal-cancers/ctdna-guided-adjuvant-chemotherapy-in-colon-cancer-not-ready-for-prime-time)
- Salvage chemotherapy for ctDNA-positive patients (ALTAIR) missed its DFS endpoint — [Nature Medicine 2026](https://www.nature.com/articles/s41591-026-04428-0)
- A personalized vaccine alone in ctDNA-positive CRC was terminated for futility with a numerical OS imbalance — [BioNTech 2026](https://www.biontech.com/int/en/home/mediaroom/news/statements/2026/08/BioNTech-Provides-Update-on-Phase-2-Clinical-Trial-of-Autogene-Cevumeran-in-Resected-Colorectal-Cancer.html)
- Single-draw sensitivity of 67.6–75%, and 60% in rectal cancer for a tumor-uninformed assay — [Natera](https://www.prnewswire.com/news-releases/natera-announces-updated-signatera-mrd-data-from-circulate-japan-presented-in-plenary-talk-at-the-society-of-surgical-oncology-conference-and-activation-of-circulate-us-trial-301506387.html); [Targeted Oncology](https://www.targetedonc.com/view/guardant-reveal-ctdna-test-shows-high-sensitivity-in-colorectal-cancer)
- Precision oncology: only 17.8% of screened patients were matched in NCI-MATCH, and actionability was below 6% in pancreatic and small-cell lung cancer — [JCO 2020](https://ascopubs.org/doi/10.1200/JCO.19.03010)
- Much of the MRD evidence (sensitivity, lead time) comes from company-sponsored studies and press releases (Natera, Guardant), so independent replication matters — sources as above.

### Inferences
- Open questions:
  - Do ctDNA-negative patients need adjuvant therapy in stage III? (Answer pending longer follow-up and other trials.)
  - Is there any therapy that converts ctDNA-positive MRD into durable remission?
  - Will INTerpath-001's effect size match phase 2 (HR about 0.5)?
  - Does vaccine benefit extend beyond melanoma (NSCLC, bladder, RCC INTerpath trials) and to PDAC (IMcode003)?
  - Can cost and turnaround of bespoke assays and vaccines scale?
- Prospective evidence that serial ctDNA monitoring, as opposed to a single post-op draw, improves survival is still missing.

### Gaps
- No data on cost-effectiveness, reimbursement or turnaround times was gathered.
- I found no independent (non-company) head-to-head comparison of MRD assays.
- I gathered no regulatory filing dates for intismeran autogene.
