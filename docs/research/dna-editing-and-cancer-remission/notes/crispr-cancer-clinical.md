# CRISPR and other gene-editing approaches against cancer: human clinical evidence (as of October 2026)

Scope notes for the report-writer:
- Human trial data unless a line is explicitly labelled preclinical (mouse/cell line).
- Figures are aggregate trial-level only; no individual case detail is reproduced here.
- Not medical advice.
- Several primary pages (NEJM full text, CRISPR Therapeutics IR page, UCL news, the Innovative Genomics Institute 2025 trial round-up) returned HTTP 403 or timed out during this research, so a few figures come from institutional press releases or trade press rather than the paper itself. Those are flagged.
- Research budget was ~15 tool calls; remaining gaps are listed per question.

## Q1. Which CRISPR-edited cell therapies for cancer have reported human results, and what were the response rates, durability, sample sizes and safety events?

### Takeaway
Every human cancer result to date comes from immune cells edited outside the body (ex vivo) and then infused — not from editing the tumour in place. The strongest signals are in blood cancers: base-edited universal CAR7 for T-ALL (~82% deep remission, ~11 patients, NEJM 2025), and allogeneic CRISPR CD19 CAR-T in large B-cell lymphoma (CTX112/zugo-cel 70% complete response at the top dose, n=10; Caribou vispa-cel 64% complete response, n=22). Solid-tumour editing trials (PD-1 knockout T cells, multiplex-edited NY-ESO-1 T cells, CISH-knockout TILs) established safety and feasibility but produced mostly stable disease with isolated durable complete responses.

### Cited Findings

**Base-edited universal CAR7 (BE-CAR7), T-cell acute lymphoblastic leukaemia (T-ALL) — GOSH/UCL, NCT05397184 "TvT CAR7"**
- Editing design: base editing inactivates three genes — the T-cell receptor beta chain, CD7, and CD52 — respectively to prevent graft-versus-host disease, avoid fratricide, and allow the cells to survive alemtuzumab lymphodepletion. — [Blood 146 Suppl 1:1041 (ASH 2025 abstract)](https://ashpublications.org/blood/article/146/Supplement%201/1041/549942/Universal-base-edited-CAR7-T-cells-for-T-cell); [ClinicalTrials.gov NCT05397184](https://clinicaltrials.gov/study/NCT05397184)
- First report, 2023: Chiesa et al., NEJM, published online 13 June 2023, DOI 10.1056/NEJMoa2300709 — 3 patients dosed; 2 of 3 reached molecular/complete remission by day 28; 1 death on day 33 from an opportunistic fungal infection. Toxicities recorded included grade 2 cytokine release syndrome (CRS), grade 1 immune effector cell-associated neurotoxicity, grade 2 graft-versus-host disease, opportunistic infection and multilineage cytopenia. — [CGTLive summary of the NEJM report](https://www.cgtlive.com/view/base-edited-cd7-car-t-cells-show-early-efficacy-in-t-all)
- Full report, 2025: Qasim et al. (lead author Waseem Qasim), NEJM 2025, DOI 10.1056/NEJMoa2505478, presented at the 67th ASH Annual Meeting (December 2025). — [NEJM DOI](https://doi.org/10.1056/NEJMoa2505478); [ScienceDaily, 11 Dec 2025](https://www.sciencedaily.com/releases/2025/12/251211040438.htm)
- Cohort and outcomes (2025 report): "82% of patients achieved very deep remissions after BE-CAR7"; "82% proceeded to stem cell transplant without disease"; and 63% (GOSH figure) / 64% (ScienceDaily figure) "remain disease-free". Earliest-treated patients are described as three years disease-free and off treatment. — [GOSH news release](https://www.gosh.nhs.uk/news/ready-made-t-cell-gene-therapy-tackles-incurable-t-cell-leukaemia/); [ScienceDaily](https://www.sciencedaily.com/releases/2025/12/251211040438.htm)
- Cohort size: the ASH 2025 abstract states nine children under 16 with relapsed/refractory T-ALL were dosed between 1 April 2022 and 31 May 2025. GOSH describes a total of about 11 recipients (the 2022 first patient plus eight further children and two adults at GOSH and King's College Hospital). These two counts do not match and should be reconciled against the NEJM paper before publication. — [Blood ASH 2025 abstract](https://ashpublications.org/blood/article/146/Supplement%201/1041/549942/Universal-base-edited-CAR7-T-cells-for-T-cell); [GOSH](https://www.gosh.nhs.uk/news/ready-made-t-cell-gene-therapy-tackles-incurable-t-cell-leukaemia/)
- Safety characterisation in the 2025 cohort: "low blood counts, cytokine release syndrome and rashes were tolerable", with "greatest risks arising from virus infections until immunity recovered". — [GOSH](https://www.gosh.nhs.uk/news/ready-made-t-cell-gene-therapy-tackles-incurable-t-cell-leukaemia/)
- Funding note: GOSH Charity committed over £2 million to treat an additional 10 patients. — [GOSH](https://www.gosh.nhs.uk/news/ready-made-t-cell-gene-therapy-tackles-incurable-t-cell-leukaemia/)

**CTX110 (allogeneic CRISPR-Cas9 CD19 CAR-T), CARBON trial NCT04035434 — CRISPR Therapeutics**
- At dose level 2 and above in large B-cell lymphoma (LBCL), intent-to-treat: 58% overall response rate (ORR), 38% complete response (CR). Six-month CR rate 21%; longest response ongoing beyond 18 months. — [CRISPR Therapeutics CARBON results release](https://crisprtx.gcs-web.com/news-releases/news-release-details/crispr-therapeutics-reports-positive-results-its-phase-1-carbon)
- Safety: no grade 3 or higher CRS; all CRS grade 1-2; no graft-versus-host disease; low rates of infection and ICANS. — [same release](https://crisprtx.gcs-web.com/news-releases/news-release-details/crispr-therapeutics-reports-positive-results-its-phase-1-carbon)
- CTX110 was discontinued; CRISPR Therapeutics cut it in favour of next-generation candidates and expanded into autoimmune disease. — [Fierce Biotech](https://www.fiercebiotech.com/biotech/crispr-therapeutics-cuts-2-cancer-programs-pipeline-expands-autoimmune-disease)

**CTX112 / zugocaptagene geleucel ("zugo-cel") — next-generation allogeneic CRISPR-Cas9 CD19 CAR-T**
- Edits: allogeneic CD19 CAR-T with added "potency edits" (CRISPR Therapeutics' description) beyond the TRAC/B2M knockouts of CTX110. — [ASH 2024 abstract, Blood 144 Suppl 1:4829](https://ashpublications.org/blood/article/144/Supplement%201/4829/533290/CTX112-a-Next-Generation-Allogeneic-CRISPR-Cas9)
- Phase 1 dose escalation (ASH 2024): with >3 months follow-up, 67% objective response rate and 44% confirmed complete response; response lasted beyond 6 months in four patients; one patient at dose level 1 remained in CR more than a year after infusion. No dose-limiting toxicities, no grade ≥3 infections, no graft-versus-host disease. — [ASH 2024 abstract](https://ashpublications.org/blood/article/144/Supplement%201/4829/533290/CTX112-a-Next-Generation-Allogeneic-CRISPR-Cas9); [Blood Cancer Today](https://www.bloodcancertoday.com/post/ctx112-yields-clinically-meaningful-results-in-relapsed-or-refractory-b-cell-malignancies)
- Update dated 22 December 2025: at the 600 million cell dose in relapsed/refractory LBCL — ORR 90% (9/10) and complete response rate 70% (7/10); of those reaching the 12-month timepoint, 67% (2/3) remained in CR at 12 months. Well tolerated with no high-grade CRS or ICANS. Further updates guided for the second half of 2026. — [CRISPR Therapeutics zugo-cel update, GlobeNewswire 22 Dec 2025](https://www.globenewswire.com/news-release/2025/12/22/3209224/0/en/CRISPR-Therapeutics-Provides-Broad-Update-on-Zugocaptagene-Geleucel-Zugo-cel-formerly-CTX112-in-Autoimmune-Diseases-and-Hematologic-Malignancies.html)
- Regulatory: FDA granted Regenerative Medicine Advanced Therapy (RMAT) designation to CTX112 for relapsed/refractory follicular lymphoma and marginal zone lymphoma. RMAT is a development/review designation, not an approval. — [RMAT designation report](https://www.barchart.com/story/news/29971865/crispr-therapeutics-announces-rmat-designation-for-ctx112-following-promising-phase-1-data-in-cd19-positive-b-cell-malignancies)
- Caution: the 12-month durability denominator is 3 patients. The headline 70% CR rests on 10 patients. These are very small numbers for a phase 1 dose cohort.

**CTX130 / CTX131 (allogeneic anti-CD70 CAR-T, solid tumours and haematologic malignancies)**
- CTX131 incorporated edits to evade the immune system, prevent fratricide, enhance potency and reduce exhaustion. — [ClinicalTrials.gov NCT05795595](https://clinicaltrials.gov/study/NCT05795595)
- CRISPR Therapeutics redirected resources away from CTX131 (reported as abandoned in November 2025); the phase 1/2 solid-tumour trial was listed complete as of 18 September 2025 with no data reported at the time of that report. — [Oncology Pipeline](https://www.oncologypipeline.com/apexonco/crispr-cans-next-gen-project); [CRISPR Therapeutics Q3 2025 update](https://ir.crisprtx.com/news-releases/news-release-details/crispr-therapeutics-provides-business-update-and-reports-third-6/)

**CB-010 / vispa-cel (allogeneic CRISPR-edited CD19 CAR-T with PD-1 knockout) — Caribou Biosciences, ANTLER phase 1**
- Data as of 29 September 2025 (announced 3 November 2025): confirmatory cohort (n=22) — 64% complete response rate, 82% overall response rate. In patients receiving vispa-cel with an "optimized profile" (n=35): 63% CR, 86% ORR. — [Caribou press release, 3 Nov 2025](https://www.globenewswire.com/news-release/2025/11/03/3179104/0/en/Caribou-Biosciences-Announces-Positive-Data-from-ANTLER-Phase-1-Trial-Demonstrating-Efficacy-and-Durability-of-Vispa-cel-CB-010-an-Allogeneic-CAR-T-Cell-Therapy-on-Par-with-Autolog.html)
- Durability: 51% progression-free survival at 12 months in the confirmatory cohort; the longest-responding patient remains in complete response at 3 years post-infusion. Dosing was at the recommended phase 2 dose of 80x10^6 CAR-T cells with partially matched donors (≥4 matched HLA alleles). — [same release](https://www.globenewswire.com/news-release/2025/11/03/3179104/0/en/Caribou-Biosciences-Announces-Positive-Data-from-ANTLER-Phase-1-Trial-Demonstrating-Efficacy-and-Durability-of-Vispa-cel-CB-010-an-Allogeneic-CAR-T-Cell-Therapy-on-Par-with-Autolog.html)
- Caribou's framing is that this is "on par with approved autologous CAR-T cell therapies" — a company claim from a single-arm phase 1, not a randomised comparison.

**PD-1 knockout autologous T cells, advanced non-small-cell lung cancer (NSCLC) — West China Hospital, Sichuan University (Lu You), NCT02793856**
- Published in Nature Medicine, online 27 April 2020. PD-1-edited T cells were made ex vivo by electroporating Cas9 and single-guide-RNA plasmids. — [Nature Medicine](https://www.nature.com/articles/s41591-020-0840-5); [West China Hospital release](https://www.wchscu.cn/details/52604.html)
- 12 patients with advanced lung cancer who had failed third-line or later treatment completed therapy. All treatment-related adverse events were grade 1/2; no grade 3+ cell-therapy-related toxicity and no treatment-related death. — [Nature Medicine](https://www.nature.com/articles/s41591-020-0840-5); [West China Hospital](https://www.wchscu.cn/details/52604.html)
- Efficacy: median progression-free survival 7.7 weeks; median overall survival 42.6 weeks. Primary endpoints were safety and feasibility; efficacy was secondary. — [West China Hospital](https://www.wchscu.cn/details/52604.html); [PMC review of the trial](https://pmc.ncbi.nlm.nih.gov/articles/PMC7772009/)
- This is the first-in-human CRISPR-Cas9 PD-1-edited T-cell trial in advanced NSCLC. — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7772009/)

**Multiplex-edited NY-ESO-1 TCR T cells ("NYCE"), UPenn — Stadtmauer et al., Science 2020, NCT03399448**
- Edits: Cas9 ribonucleoprotein against TRAC, TRBC (removing the endogenous T-cell receptor) and PDCD1 (PD-1), plus lentiviral transduction of a transgenic NY-ESO-1-specific TCR. — [Science 367:eaba7365](https://www.science.org/doi/10.1126/science.aba7365); [ClinicalTrials.gov NCT03399448](https://clinicaltrials.gov/study/NCT03399448)
- Four products were manufactured at clinical scale; three patients were infused (two with advanced refractory myeloma, one with metastatic sarcoma). Cells were well tolerated with durable engraftment over the study duration. Editing efficiency varied by guide, highest for TRAC and lowest for TRBC. — [Science](https://www.science.org/doi/10.1126/science.aba7365); [PubMed 32029687](https://pubmed.ncbi.nlm.nih.gov/32029687/)
- The authors frame the result as demonstrating that multiplex human genome engineering is safe and feasible — a feasibility result, not an efficacy result. — [Science](https://www.science.org/doi/10.1126/science.aba7365)

**CISH-knockout tumour-infiltrating lymphocytes (TILs), metastatic colorectal/GI cancer — Intima Biosciences / University of Minnesota; Lancet Oncology 2025**
- First-in-human, single-centre phase 1 targeting the intracellular immune checkpoint CISH with CRISPR-Cas9-edited TILs. — [Lancet Oncology](https://www.thelancet.com/journals/lanonc/article/PIIS1470-2045(25)00083-X/abstract)
- Manufacturing and dosing: CISH-knockout TIL products were successfully manufactured for 19 of 22 enrolled patients (86%); 12 of those 19 (63%) received a single infusion. — [Lancet Oncology](https://www.thelancet.com/journals/lanonc/article/PIIS1470-2045(25)00083-X/abstract); [ASCO Post](https://ascopost.com/news/may-2025/crispr-cas9-edited-tils-targeting-intracellular-immune-checkpoint-cish-in-metastatic-colorectal-cancer/)
- Efficacy: 6 of 12 infused patients had stable disease at day 28; 4 still had stable disease at day 56; one patient had a durable complete radiographic response exceeding 21 months. — [ASCO Post](https://ascopost.com/news/may-2025/crispr-cas9-edited-tils-targeting-intracellular-immune-checkpoint-cish-in-metastatic-colorectal-cancer/); [OncLive](https://www.onclive.com/view/first-in-human-data-support-cish-knockout-strategy-to-enhance-til-activity-circumvent-ici-resistance-in-metastatic-gi-cancers)
- Safety: no cytokine release syndrome and no neurotoxicity; the maximum tolerated dose was not reached (all dose levels tolerated). — [Lancet Oncology](https://www.thelancet.com/journals/lanonc/article/PIIS1470-2045(25)00083-X/abstract)
- Conflicting/critical commentary exists: a correspondence piece "CRISPR-engineered T-cell therapies: some clarifications needed" was published in Lancet Oncology in response. The report-writer should note that the trial's interpretation was challenged. — [Lancet Oncology correspondence](https://www.thelancet.com/journals/lanonc/article/PIIS1470-2045(25)00362-6/abstract)

**BEAM-201 (quadruplex base-edited allogeneic anti-CD7 CAR-T), relapsed/refractory T-ALL / T-LL — Beam Therapeutics**
- Described as the first quadruplex-edited allogeneic CAR-T to enter clinical development; base edits remove CD7, TRAC, PDCD1 and CD52 expression, to reduce fratricide and graft-versus-host disease, limit exhaustion, evade anti-CD52 lymphodepletion, and enable an allogeneic source. — [CRISPR Medicine News](https://crisprmedicinenews.com/news/clinical-trial-update-beam-therapeutics-doses-first-patient-with-base-editing-cancer-therapy/); [Targeted Oncology, IND clearance](https://www.targetedonc.com/view/fda-clears-ind-for-beam-201-in-relapsed-refractory-t-all-t-ll)
- Trial design: phase 1/2 aiming to enrol 102 adults and children with CD7-positive T-ALL/T-LL, across phase 1 dose-exploration, dose-expansion, a paediatric cohort, and a phase 2 cohort. — [CGTLive](https://www.cgtlive.com/view/beam-201-car-t-first-treatment-lymphoma-leukemia)
- Preclinical (not human): 96-99% on-target editing at clinical scale and dose-dependent tumour control in vitro and in xenograft models. — [Beam investor release](https://investors.beamtx.com/news-releases/news-release-details/beam-therapeutics-names-first-car-t-base-editing-development/)
- Clinical data were slated for the 66th ASH Annual Meeting (7-10 December 2024), and the program previously went through an FDA clinical hold. I did not retrieve the actual response/remission figures. — [Fierce Biotech on the clinical hold](https://www.fiercebiotech.com/biotech/beam-sheds-more-light-clinical-hold-slapped-gene-edited-car-t)

**Genome-edited "universal" CAR19 T cells for relapsed/refractory B-ALL (predecessor platform, TALEN/base-edited lineage at the same paediatric centre)**
- A long-term outcomes paper exists for genome-edited universal CAR19 T cells in relapsed/refractory B-ALL at a single paediatric centre; useful for durability context on the universal-donor approach. — [PMC12496233](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12496233/)

### Inferences
- The therapeutic pattern is consistent: CRISPR in cancer is currently a manufacturing improvement to cell therapy (allogeneic/off-the-shelf, fratricide-resistant, checkpoint-disabled), not a way of correcting cancer-causing mutations in a patient's tumour.
- Blood cancers dominate because the target antigens (CD19, CD7, CD70) are lineage markers and the edited cells can reach the malignant compartment. Solid tumours remain the bottleneck: the three solid-tumour-facing trials above (NSCLC PD-1 KO, NY-ESO-1 multiplex, CISH-KO TIL) report feasibility and stable disease rather than high response rates.
- The allogeneic CRISPR CAR-T response rates reported in 2025 (64-70% CR) are approaching the autologous benchmark, but all are single-arm phase 1 with 10-35 evaluable patients and short durability denominators, and two of the four CRISPR Therapeutics oncology programs (CTX110, CTX131) were discontinued for portfolio reasons despite "encouraging" phase 1 data — a signal that commercial viability, not just efficacy, gates this field.

### Gaps
- Exact patient count for the 2025 BE-CAR7 NEJM paper: ASH abstract says 9 children dosed 1 Apr 2022-31 May 2025; GOSH/UCL press material implies ~11 including 2 adults. NEJM full text was not retrievable (403). The percentages (82%/63-64%) also differ slightly between GOSH and ScienceDaily, and neither gives the denominator explicitly.
- BE-CAR7 2025 relapse count, CD7-negative relapse rate, and total deaths are not stated in the accessible press material.
- BEAM-201 human efficacy figures (ASH 2024) were not retrieved.
- CTX130 (anti-CD70, renal cell carcinoma and T-cell lymphoma) human response figures were not retrieved; CTX131 has no reported data.
- Chinese trials beyond the Lu You NSCLC study (there are multiple registered CRISPR PD-1 knockout trials in China) were not surveyed, and NMPA regulatory status of any domestic CRISPR cancer product was not established.
- No EMA-specific documentation was retrieved.

## Q2. Has any CRISPR-based cancer therapy been approved by FDA, EMA or NMPA as of 2026?

### Takeaway
No. As of 2026 there is no approved CRISPR-based (or base-edited/prime-edited) therapy for any cancer anywhere I could verify. Casgevy, the first approved CRISPR medicine, treats sickle cell disease and beta-thalassemia — not cancer. All seven FDA-approved CAR-T products are autologous and none is gene-edited with CRISPR.

### Cited Findings
- Casgevy (exagamglogene autotemcel), from Vertex Pharmaceuticals and CRISPR Therapeutics, was approved by the FDA on 8 December 2023 for sickle cell disease — the first FDA-approved therapy using CRISPR-Cas9 genome editing. — [STAT News, 8 Dec 2023](https://www.statnews.com/2023/12/08/fda-approves-casgevy-crispr-based-medicine-for-treatment-of-sickle-cell-disease/); [Casgevy FDA approval history, Drugs.com](https://www.drugs.com/history/casgevy.html)
- Casgevy's mechanism is unrelated to cancer: CRISPR-Cas9 inactivates BCL11A expression in red-blood-cell precursors, releasing fetal haemoglobin expression to compensate for the mutated beta-globin gene. — [American Journal of Medicine](https://www.amjmed.com/article/S0002-9343(23)00798-2/fulltext)
- Casgevy pivotal efficacy: of 31 patients evaluated, 29 (93.5%) were free from severe vaso-occlusive crises for at least 12 consecutive months during 24-month follow-up. List price reported at $2.2 million. — [GEN](https://www.genengnews.com/topics/genome-editing/fda-approves-the-first-crispr-therapy-for-sickle-cell-disease/)
- As of early-to-mid 2026 there are seven FDA-approved CAR-T therapies, all for blood-cancer indications and all autologous; no allogeneic CAR-T has been approved. — [Cell & Gene Therapy Insights industry review](https://www.insights.bio/cell-and-gene-therapy-insights/journal/article/3912/industry-insights-expanding-access-across-the-field-from-pediatric-approvals-to-the-first-solid-tumor-cart)
- The most advanced gene-edited allogeneic CAR-T on a regulatory path is Cellectis' lasmecabtagene timgedleucel (lasme-cel), a CD22-targeting allogeneic CAR-T, which received FDA RMAT designation for relapsed/refractory B-ALL in June 2026; Cellectis anticipates a Biologics License Application in 2028. Note lasme-cel's platform is TALEN-based editing (Cellectis' technology), not CRISPR. — [Cellectis SEC Form 6-K FY2026](https://www.sec.gov/Archives/edgar/data/0001627281/000117184326004006/exh_991.htm)
- For context on non-CRISPR allogeneic cell therapy: Atara's tabelecleucel (Ebvallo), the first approved allogeneic T-cell therapy, was launched in the EU in 2022 and approved by FDA in 2025 for relapsed/refractory EBV-positive post-transplant lymphoproliferative disease — but it is not a CAR-T and not gene-edited. — [Cell & Gene Therapy Insights](https://www.insights.bio/cell-and-gene-therapy-insights/journal/article/3912/industry-insights-expanding-access-across-the-field-from-pediatric-approvals-to-the-first-solid-tumor-cart)

### Inferences
- The distinction worth stating plainly in the report: "first CRISPR medicine approved" (Casgevy, 2023, sickle cell/beta-thalassemia) is routinely conflated with "CRISPR cures cancer". The first claim is true; the second has no approved instance. The nearest thing to a cancer approval is an RMAT designation (CTX112 in follicular/marginal zone lymphoma), which only accelerates development and review.
- RMAT designations for both CTX112 (CRISPR-edited) and lasme-cel (TALEN-edited) suggest regulators consider the gene-edited allogeneic CAR-T class credible, with BLA filings plausibly 2027-2029 rather than 2026.

### Gaps
- I did not verify EMA or NMPA registers directly. The claim "no approval anywhere" rests on the absence of any report of one in the sources retrieved plus the explicit FDA-side statements; the report should phrase it as "no approved CRISPR cancer therapy has been reported as of October 2026" rather than asserting an exhaustive register search.
- EMA's approval date for Casgevy (Feb 2024) was not independently retrieved in this research; it should be confirmed before citing.

## Q3. What is the evidence status of in vivo CRISPR editing of tumours themselves?

### Takeaway
There is no human efficacy evidence for editing a tumour inside the body. In vivo CRISPR has been proven in humans only in the liver (a naturally accessible organ), via lipid nanoparticles; tumour-directed in vivo editing remains preclinical, with delivery as the limiting problem.

### Cited Findings
- The landmark first-in-human in vivo CRISPR trial, NTLA-2001 (Intellia), targeted transthyretin (TTR) amyloidosis using lipid nanoparticles carrying Cas9 mRNA and an anti-TTR single guide RNA, achieving dose-dependent liver editing and serum TTR reduction of up to 87%. This is not a cancer indication. — [Annals of Medicine and Surgery review, "Nanoparticle-enhanced CRISPR delivery"](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12768121/)
- The same review states explicitly that this completed human in vivo CRISPR trial targeted liver cells "rather than solid tumors because of their natural accessibility", and that most tumour in vivo editing data come from mouse models; delivery to dense or poorly vascularised tumours (pancreas, brain) remains a major hurdle. — [PMC12768121](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12768121/)
- Preclinical (mouse): CRISPR-Cas9 genome editing using targeted lipid nanoparticles for cancer therapy — Rosenblum et al., Science Advances, 2020. — [Science Advances](https://www.science.org/doi/10.1126/sciadv.abc9450); [PubMed 33208369](https://pubmed.ncbi.nlm.nih.gov/33208369/)
- Preclinical (mouse/cell): targeted CRISPR-Cas9 lipid nanoparticles eliciting therapeutic genome editing in head and neck cancer — Masarwy et al., Advanced Science, 2025. — [Advanced Science](https://advanced.onlinelibrary.wiley.com/doi/10.1002/advs.202411032)
- Preclinical (cancer stem cells): RNA lipid nanoparticles as an in vivo CRISPR-Cas9 tool for therapeutic target validation in glioblastoma cancer stem cells — used for target validation, not therapy. — [Journal of Controlled Release](https://www.sciencedirect.com/science/article/pii/S0168365924006291)
- The cancer-relevant in vivo-adjacent human milestone reported in May 2025 was Intima Biosciences' phase 1/2 of CRISPR-edited tumour-infiltrating immune cells in metastatic colon cancer — which is ex vivo editing of immune cells, not editing of the tumour. — [Innovative Genomics Institute, CRISPR Clinical Trials 2025](https://innovativegenomics.org/news/crispr-clinical-trials-2025/) (page returned 403 on fetch; summary taken from the search snippet — verify before citing)

### Inferences
- The engineering gap is delivery specificity, not nuclease performance: a liver-tropic lipid nanoparticle works because hepatocytes take up LNPs naturally, whereas a solid tumour requires targeted tropism plus penetration of stroma and poor vasculature.
- A corollary for the report: even if a tumour-driver mutation were perfectly editable in principle, editing only a fraction of tumour cells leaves the unedited fraction to repopulate — which is why in vivo oncology CRISPR is mostly used as a target-discovery tool rather than a therapy.

### Gaps
- I found no registered first-in-human trial of in vivo CRISPR editing directed at a tumour. Absence of evidence in these searches is not proof none is registered; a direct ClinicalTrials.gov query would be needed to assert it.

## Q4. How are CRISPR screens (e.g. DepMap) used to find cancer drug targets, and which targets reached the clinic?

### Takeaway
Genome-wide CRISPR knockout screens across cancer cell-line panels (the DepMap approach) find synthetic-lethal dependencies — genes a tumour needs only because of a specific genetic context. The clearest success is WRN helicase in microsatellite-instability (MSI) cancers, discovered by CRISPR screens and now in human trials as the inhibitor HRO761 (NCT05838768). Note what reached the clinic is a small-molecule drug, not an editing therapy.

### Cited Findings
- WRN (Werner syndrome RecQ helicase) was identified as a synthetic-lethal target in cancer cells with microsatellite instability "by several genetic screens". — [Nature, "Discovery of WRN inhibitor HRO761 with synthetic lethality in MSI cancers"](https://www.nature.com/articles/s41586-024-07350-y); [PMC11078746](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11078746/)
- HRO761 (Novartis) is a potent, selective, allosteric WRN inhibitor binding at the D1/D2 helicase domain interface, locking WRN inactive; pharmacological inhibition recapitulated the genetic-suppression phenotype, causing DNA damage and selective growth inhibition in MSI cells in a p53-independent manner. — [Nature 2024](https://www.nature.com/articles/s41586-024-07350-y)
- Clinical status: trial NCT05838768 is ongoing, assessing safety, tolerability and preliminary anti-tumour activity of HRO761 in patients with MSI colorectal cancer and other MSI solid tumours. — [Nature 2024 / PMC11078746](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11078746/)
- Screens continue to refine the target: genome-wide CRISPR screens identified non-homologous end-joining factors and the checkpoint phosphatase WIP1 as synthetic vulnerabilities that potentiate WRN inhibition, and SMARCAL1 as a modulator of WRN dependency (SMARCAL1 depletion confers resistance). — [CRISPR screening identifies SMARCAL1 and MRN as modulators of WRN dependency in MSI-H colorectal cancer, PubMed 42484294](https://pubmed.ncbi.nlm.nih.gov/42484294/)
- Resistance is already mapped preclinically: discrete resistance hotspots within WRN were found, with single-allele mutations at the drug-binding site sufficient to abrogate WRN-inhibitor cytotoxicity, and resistance profiles diverging between HRO761 and VVD-214 (a second WRN inhibitor). — [Molecular Cancer Therapeutics, PMC13434289](https://pmc.ncbi.nlm.nih.gov/articles/PMC13434289/); [bioRxiv preprint, Jan 2026](https://www.biorxiv.org/content/10.64898/2026.01.22.700152v1.full)

### Inferences
- WRN/HRO761 is the cleanest example of the full chain: CRISPR screen → context-specific dependency → small-molecule inhibitor → human trial. It should be presented as CRISPR's largest indirect contribution to oncology to date, and arguably a larger near-term clinical contribution than CRISPR therapies themselves.
- The resistance work (on-target binding-site mutations) suggests the same escape dynamics as kinase inhibitors; screens are being used to pre-empt that by nominating combination partners (NHEJ factors, WIP1).

### Gaps
- I did not retrieve human efficacy data (response rates) from NCT05838768, nor its enrolment, phase, or dates. The Nature paper describes the trial as ongoing; whether results have since been reported is unresolved.
- I did not verify which DepMap release or which specific screen papers (e.g. Chan et al. and Behan et al. 2019) first nominated WRN; the Nature paper's "several genetic screens" is as specific as my sources got. Other CRISPR-screen-derived targets (e.g. PRMT5/MTAP-deleted cancers, Werner-adjacent dependencies) were not surveyed.

## Q5. What are the main limitations: off-target edits, chromosomal loss, p53 selection, delivery, cost?

### Takeaway
The documented limitations are genomic (large structural changes, not just point off-targets), selective (p53-functional cells resist editing, so edited populations can be enriched for p53-impaired cells — a particular concern in oncology), practical (delivery, manufacturing success rates) and economic (a $2.2M precedent price, and programs cancelled despite positive data).

### Cited Findings

**Chromosomal loss / aneuploidy**
- Tsuchida et al., "Mitigation of chromosome loss in clinical CRISPR-Cas9-engineered T cells", Cell 2023, 186:4567-4582 — aneuploid human TCR-alpha (TRAC, chromosome 14) knockout T cells occurred at frequencies of up to 20% after CRISPR editing. — [reported in Cell Reports Medicine / review literature](https://www.cell.com/cell-reports-medicine/fulltext/S2666-3791(24)00617-7)
- Nahmad et al., "Frequent aneuploidy in primary human T cells after CRISPR-Cas9 cleavage", Nature Biotechnology 2022. — [Nature Biotechnology](https://www.nature.com/articles/s41587-022-01377-0)
- A 2025 review frames the issue as "the hidden risks of CRISPR/Cas: structural variations and genome integrity" — i.e. the risk is large-scale structural variation, not only small off-target indels. — [Nature Communications 2025](https://www.nature.com/articles/s41467-025-62606-z)
- Mitigation is being engineered: modulating TCR stimulation plus pifithrin-alpha (a p53 inhibitor) improved the genomic safety profile of CRISPR-engineered human T cells. — [Cell Reports Medicine](https://www.cell.com/cell-reports-medicine/fulltext/S2666-3791(24)00617-7)

**p53-mediated selection**
- Haapaniemi et al., "CRISPR-Cas9 genome editing induces a p53-mediated DNA damage response", Nature Medicine 2018, 24:927-930 — editing induces a p53-mediated DNA damage response and cell-cycle arrest in immortalised human retinal pigment epithelial cells, "leading to a selection against cells with a functional p53 pathway". — [Semantic Scholar record](https://www.semanticscholar.org/paper/CRISPR%E2%80%93Cas9-genome-editing-induces-a-p53-mediated-Haapaniemi-Botla/9e449274b3e69f5d78d924179d96a4941932b19b)
- Ihry et al., "p53 inhibits CRISPR-Cas9 engineering in human pluripotent stem cells", Nature Medicine 2018, 24:939-946. — [p53 activation: a checkpoint for precision genome editing?, PMC6098583](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6098583/)
- The claim was contested in part: a published exchange "CRISPR screens are feasible in TP53 wild-type cells" and the authors' reply indicates the strength of the p53-selection effect is cell-type dependent and was disputed. — [PubMed 31464368 (Reply)](https://pubmed.ncbi.nlm.nih.gov/31464368/)

**Delivery**
- Delivering nanoparticles to dense or poorly vascularised tumours (pancreas, brain) remains a major hurdle; most tumour-editing data are from mouse models. — [PMC12768121](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12768121/)
- Base and prime editing in T-cell immunotherapy carry their own distinct challenge set, reviewed in 2025. — [Nature Reviews Clinical Oncology, "Next-generation T cell immunotherapies engineered with CRISPR base and prime editing: challenges and opportunities"](https://www.nature.com/articles/s41571-025-01072-4)

**Manufacturing feasibility (a practical limit with hard numbers)**
- In the CISH-knockout TIL trial, products could be manufactured for only 19 of 22 enrolled patients (86%), and only 12 of those 19 (63%) actually received an infusion — so 12 of 22 enrolled (55%) were treated. — [Lancet Oncology](https://www.thelancet.com/journals/lanonc/article/PIIS1470-2045(25)00083-X/abstract)
- In the NY-ESO-1 multiplex trial, four products were manufactured but only three patients were infused. — [Science](https://www.science.org/doi/10.1126/science.aba7365)

**Cost and commercial attrition**
- Casgevy, the only approved CRISPR medicine, carries a reported $2.2 million price tag and "an arduous clinical process". — [GEN](https://www.genengnews.com/topics/genome-editing/fda-approves-the-first-crispr-therapy-for-sickle-cell-disease/)
- CRISPR Therapeutics discontinued two oncology programs (CTX110, CTX131) despite describing the CTX131 phase 1 data as "encouraging", explicitly redirecting resources to programs "with the greatest potential for long-term value creation". — [CRISPR Therapeutics Q3 2025 update](https://ir.crisprtx.com/news-releases/news-release-details/crispr-therapeutics-provides-business-update-and-reports-third-6/); [Fierce Biotech](https://www.fiercebiotech.com/biotech/crispr-therapeutics-cuts-2-cancer-programs-pipeline-expands-autoimmune-disease)
- The allogeneic CAR-T field is under commercial pressure generally: "'The only thing that saves us is data': Allogeneic CAR-T biotechs fight for relevance as industry moves on". — [Fierce Biotech](https://www.fiercebiotech.com/biotech/only-thing-saves-us-data-allogeneic-car-t-biotechs-fight-relevance-industry-moves)

**Safety events actually observed in cancer trials (from Q1, consolidated)**
- Deaths from opportunistic infection during immune reconstitution after lymphodepletion plus CD7/CD52-directed editing (BE-CAR7 2023 report: 1 death on day 33). — [CGTLive](https://www.cgtlive.com/view/base-edited-cd7-car-t-cells-show-early-efficacy-in-t-all)
- Across the allogeneic CRISPR CD19 programs, the reported pattern is absence of high-grade CRS/ICANS and absence of graft-versus-host disease — the editing appears to be achieving its intended safety purpose (TCR removal preventing GvHD). — [CTX110 CARBON](https://crisprtx.gcs-web.com/news-releases/news-release-details/crispr-therapeutics-reports-positive-results-its-phase-1-carbon); [zugo-cel update](https://www.globenewswire.com/news-release/2025/12/22/3209224/0/en/CRISPR-Therapeutics-Provides-Broad-Update-on-Zugocaptagene-Geleucel-Zugo-cel-formerly-CTX112-in-Autoimmune-Diseases-and-Hematologic-Malignancies.html)

### Inferences
- The p53 finding has a specific oncology irony worth stating: because editing selects against cells with intact p53, an edited cell product may be enriched for cells with a compromised tumour-suppressor pathway — the exact lesion that predisposes to malignant transformation. This is a theoretical risk in cell products, and the mitigation literature (pifithrin-alpha, reduced TCR stimulation) treats it as real enough to engineer around.
- Note the tension: pifithrin-alpha mitigates genomic damage by inhibiting p53, which is also the pathway whose loss is oncogenic. The report should not present this as a settled fix.
- The 55% enrolled-to-infused rate in the CISH TIL trial is arguably a more binding near-term limitation than off-target editing: patients with aggressive disease can progress or die during the weeks of manufacturing.

### Gaps
- No systematic figure for clinically observed off-target editing rates in the cancer trials above (the trials report editing efficiency, not measured off-target burden in the infused products).
- No reported case of malignant transformation attributable to CRISPR editing in a cancer cell product was found; also no source explicitly stating that none has occurred. The report should not claim either way.
- Cost of the investigational allogeneic CRISPR CAR-T products is not public; the $2.2M figure is for Casgevy (a non-cancer product) and should not be presented as the price of a CRISPR cancer therapy.

## Q6. Does editing a person's DNA "data" — a digital sequence — have any effect on their body?

### Takeaway
No. Gene editing is a physical process: molecular tools (a Cas protein or its mRNA, plus a guide RNA, and sometimes a repair template) must be physically delivered into living cells, where they act on the DNA molecules in those cells. A sequence stored in a file is a representation; altering the file alters the record, not the organism. Every therapy in these notes required either removing cells from the body, editing them in a laboratory, and infusing them back, or injecting a delivery vehicle such as a lipid nanoparticle.

### Cited Findings
- Genome editing is defined as "a group of technologies that give scientists the ability to change an organism's DNA", allowing genetic material to be "added, removed, or altered at particular locations in the genome" — i.e. an operation on the genome in cells. — [MedlinePlus Genetics, gene therapy](https://medlineplus.gov/genetics/understanding/therapy/genetherapy/)
- MedlinePlus states the mechanism explicitly: "Instead of introducing new genetic material into cells, genome editing introduces molecular tools to change the existing DNA in the cell." Molecular tools must enter cells. — [MedlinePlus Genetics](https://medlineplus.gov/genetics/understanding/therapy/genetherapy/)
- Concrete illustration of the physical requirement, from a human trial: PD-1-edited T cells were "manufactured ex vivo by cotransfection using electroporation of Cas9 and single guide RNA plasmids" — electroporation is a physical technique that opens cell membranes so the editing molecules can enter. — [Nature Medicine 2020](https://www.nature.com/articles/s41591-020-0840-5)
- Second illustration: in the UPenn trial, T cells were "transfected with Cas9 protein complexed with single guide RNAs" and then transduced with a lentiviral vector — again, molecules delivered into cells. — [Science 2020](https://www.science.org/doi/10.1126/science.aba7365)
- Third illustration, in vivo: NTLA-2001 delivered Cas9 mRNA and a guide RNA inside lipid nanoparticles injected into the patient, which are taken up by liver cells; serum TTR fell by up to 87% only because the nanoparticles physically reached hepatocytes. — [PMC12768121](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12768121/)
- The delivery problem is treated throughout the literature as the central obstacle precisely because physical access to the target cells is required — "delivering nanoparticles to dense or poorly vascularized tumors in the pancreas or brain remains a major hurdle". — [PMC12768121](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12768121/)

### Inferences
- The causal direction is one-way: a sequence file is produced by reading (sequencing) a biological sample, so biology determines the file. There is no return path from the file to the cells without a laboratory step that synthesises and delivers physical molecules.
- The practical corollary for any "digital twin" framing: a digital genome can be used to *decide* what edit to attempt (guide design, off-target prediction — see the guide-RNA design literature), but the decision still has to be executed with reagents on cells. The computation is upstream of the intervention, never a substitute for it.
- Mentioning the delivery bottleneck is the strongest evidence for this answer: an entire field's principal difficulty is getting molecules into the right cells. If editing a digital record had any somatic effect, that difficulty would not exist.

### Gaps
- I did not find a source that addresses the "editing a digital sequence affects the body" proposition directly, because no scientific literature entertains it. The answer above is assembled from authoritative descriptions of how editing works (MedlinePlus) plus the physical delivery methods documented in each human trial. The report-writer should present it that way rather than citing a source that refutes the claim by name.
- Related but distinct topics I did not research, in case the report needs them: AI/computational guide-RNA design and off-target prediction (one arXiv preprint appeared in searches: [arXiv 2508.20130](https://arxiv.org/pdf/2508.20130)), and the separate privacy/security question of someone altering a genomic record in a clinical database, which could affect care decisions without affecting the body.

## Cross-cutting notes for the report-writer

### Timeline of human milestones (all dates as given by sources)
- 2016-2020: first-in-human CRISPR PD-1 knockout T cells, advanced NSCLC, West China Hospital (NCT02793856; published Nature Medicine 27 April 2020; 12 patients). — [Nature Medicine](https://www.nature.com/articles/s41591-020-0840-5)
- Feb 2020: first US multiplex CRISPR-edited T-cell trial reported, 3 patients, UPenn (Science). — [Science](https://www.science.org/doi/10.1126/science.aba7365)
- 2021: CTX110 allogeneic CRISPR CD19 CAR-T phase 1 (CARBON) reports 58% ORR / 38% CR at DL2+ in LBCL. — [CRISPR Therapeutics](https://crisprtx.gcs-web.com/news-releases/news-release-details/crispr-therapeutics-reports-positive-results-its-phase-1-carbon)
- May 2022: first patient dosed with base-edited CAR7 at GOSH. — [GOSH](https://www.gosh.nhs.uk/news/ready-made-t-cell-gene-therapy-tackles-incurable-t-cell-leukaemia/)
- 13 June 2023: first base-editing cancer therapy report, 3 patients (NEJM). — [CGTLive](https://www.cgtlive.com/view/base-edited-cd7-car-t-cells-show-early-efficacy-in-t-all)
- 8 December 2023: Casgevy approved by FDA — first approved CRISPR medicine, for sickle cell disease, not cancer. — [STAT](https://www.statnews.com/2023/12/08/fda-approves-casgevy-crispr-based-medicine-for-treatment-of-sickle-cell-disease/)
- Dec 2024: CTX112 phase 1 dose escalation reported at ASH (67% ORR / 44% confirmed CR at >3 months). — [Blood ASH 2024](https://ashpublications.org/blood/article/144/Supplement%201/4829/533290/CTX112-a-Next-Generation-Allogeneic-CRISPR-Cas9)
- May 2025: first-in-human CISH-knockout TIL results, metastatic colorectal cancer (Lancet Oncology). — [Lancet Oncology](https://www.thelancet.com/journals/lanonc/article/PIIS1470-2045(25)00083-X/abstract)
- 3 November 2025: Caribou vispa-cel confirmatory cohort, 64% CR (n=22), 51% 12-month PFS. — [Caribou](https://www.globenewswire.com/news-release/2025/11/03/3179104/0/en/Caribou-Biosciences-Announces-Positive-Data-from-ANTLER-Phase-1-Trial-Demonstrating-Efficacy-and-Durability-of-Vispa-cel-CB-010-an-Allogeneic-CAR-T-Cell-Therapy-on-Par-with-Autolog.html)
- Nov 2025: CRISPR Therapeutics discontinues CTX131. — [Oncology Pipeline](https://www.oncologypipeline.com/apexonco/crispr-cans-next-gen-project)
- December 2025 (ASH 67th, NEJM): full base-edited CAR7 cohort, ~82% deep remission, ~63-64% disease-free. — [ScienceDaily](https://www.sciencedaily.com/releases/2025/12/251211040438.htm)
- 22 December 2025: zugo-cel (CTX112) 600M-cell dose, 90% ORR / 70% CR (n=10) in LBCL; RMAT designation in follicular and marginal zone lymphoma. — [GlobeNewswire](https://www.globenewswire.com/news-release/2025/12/22/3209224/0/en/CRISPR-Therapeutics-Provides-Broad-Update-on-Zugocaptagene-Geleucel-Zugo-cel-formerly-CTX112-in-Autoimmune-Diseases-and-Hematologic-Malignancies.html)
- June 2026: Cellectis lasme-cel (TALEN-edited, not CRISPR) receives RMAT for r/r B-ALL; BLA anticipated 2028. — [Cellectis 6-K](https://www.sec.gov/Archives/edgar/data/0001627281/000117184326004006/exh_991.htm)

### Three-way separation requested in the brief
- **Approved therapies for cancer using CRISPR: none.** Casgevy (2023) is CRISPR but is for sickle cell disease and beta-thalassemia. All seven approved CAR-T products are autologous and non-CRISPR.
- **Clinical-trial results (human):** base-edited CAR7 in T-ALL; CTX110 and CTX112/zugo-cel; CB-010/vispa-cel; BEAM-201 (dosed, figures not retrieved); PD-1-knockout T cells in NSCLC; NY-ESO-1 multiplex-edited T cells; CISH-knockout TILs. All phase 1 or phase 1/2, all single-arm, largest efficacy cohort ~35 patients.
- **Preclinical:** all tumour-directed in vivo editing (lipid-nanoparticle CRISPR in head and neck cancer, glioblastoma cancer stem cells, the 2020 Science Advances LNP work); BEAM-201's 96-99% editing and xenograft tumour clearance; the WRN resistance-mutation mapping.

### Caveats the report should carry
- Company press releases and investor updates supplied several of the headline figures (CTX112, CB-010, CTX110). These are not peer-reviewed, are selected by the sponsor, and in the CTX112 case rest on 10 patients at the quoted dose with a 3-patient 12-month denominator.
- Two reputable sources give slightly different numbers for the same BE-CAR7 cohort (63% vs 64% disease-free; 9 vs ~11 patients). Flag rather than silently choose.
- "Response rate on par with autologous CAR-T" is a sponsor comparison across trials, not a head-to-head result.
- Base editing and prime editing are distinct from Cas9 nuclease editing: base editing (used in BE-CAR7 and BEAM-201) chemically converts single bases without cutting both DNA strands, which is the stated reason it is expected to cause fewer translocations when multiple genes are edited at once. I found no human cancer trial of prime editing, and no human cancer trial of epigenome editing; both appear to remain preclinical as of these searches. — [Nature Reviews Clinical Oncology 2025](https://www.nature.com/articles/s41571-025-01072-4); [Trends in Cancer, CRISPR tools for T cells: genome, epigenome, transcriptome](https://www.cell.com/trends/cancer/abstract/S2405-8033(25)00199-2)
