# Digital twins in oncology (as of October 2026): what they are, what they can and cannot do, how well they are validated

Scope note: these are research notes, not medical advice. Each result is labeled with its publication year. Prediction accuracy (retrospective or in silico) is kept separate from proven clinical benefit (prospective use that changed outcomes). Category labels: (a) mechanistic tumor-growth/treatment-response models; (b) AI/ML predictive twins built from imaging, genomics and EHR data; (c) "virtual patient", synthetic or external control arms in trials.

## 1. Definitions and mechanism: what a digital twin is and how it could affect outcomes

### Takeaway
The authoritative definition, from the National Academies (2024), requires a twin to be updated with data from its physical counterpart, to have a predictive capability and to *inform decisions*. A twin therefore affects patient outcomes only through the treatment decisions (choice, dose, timing) that clinicians make from it. In oncology no twin acts autonomously on a patient.

### Cited Findings
- National Academies (2024) definition: a digital twin is "a set of virtual information constructs that mimics the structure, context, and behavior of a natural, engineered, or social system ..., is dynamically updated with data from its physical twin, has a predictive capability, and informs decisions that realize value." — [NASEM, Foundational Research Gaps and Future Directions for Digital Twins (2024), NCBI Bookshelf](https://www.ncbi.nlm.nih.gov/books/NBK605515/); [Summary chapter](https://www.ncbi.nlm.nih.gov/books/NBK605502/)
- NASEM (2024) treats bidirectional interaction as central: information flows from the physical system to the virtual one, and "from the virtual back to the physical system to enable decision-making, either automatic or with a human- or humans-in-the-loop." — [NASEM report, Digital Twin Landscape chapter](https://www.ncbi.nlm.nih.gov/books/NBK605499/); [report highlights PDF](https://nap.nationalacademies.org/resource/26894/RH-digital-twins.pdf)
- NCI (blog, Jan 6, 2025) defines a twin as "a real-time, virtual representation of a living physical system" with "an ongoing series of model updates, insights, and decisions — all tied to a specific system or object, such as a patient, a tumor, or even a cell." It notes that the National Academies named cancer as the exemplar biomedical application, and that healthcare digital-twin publications rose from 0 in 2016 to more than 80 in 2023. — [NCI CBIIT, "Digital Twins for Cancer—When, How, and Why?" (2025)](https://www.cancer.gov/about-nci/organization/cbiit/news-events/blog/2025/digital-twins-cancer-not-if-when-how-and-why)
- A review in J. Personalized Medicine (Oct 2025) describes twins as tools that "allow clinicians to test different treatment strategies virtually before making decisions", as "cognitive tools for clinical reasoning and decision support". — [Digital Twins in Personalized Medicine: Bridging Innovation and Clinical Reality (2025), PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12653454/)
- Pash, Villa, Hormuth, Yankeelov and Willcox (arXiv, May 2025) frame oncology twins around "patient-specific decision making": imaging is assimilated into a reaction-diffusion model, and the twin is used to evaluate decisions such as how often to image (an optimal-experimental-design question). — [Predictive Digital Twins with Quantified Uncertainty for Patient-Specific Decision Making in Oncology (2025)](https://arxiv.org/abs/2505.08927)
- Regulatory frameworks also tie credibility to a decision. ASME V&V 40 sets the required verification and validation (V&V) and uncertainty quantification (UQ) by "model risk", defined as the model's influence on the decision combined with the consequence of a wrong decision, all anchored in a stated question of interest and context of use. — [FDA CM&S credibility guidance (final, Nov 2023)](https://www.fda.gov/media/154985/download); [ASME V&V 40 overview](https://dmd.umn.edu/2023/vv-40)

### Inferences
- Combining these definitions gives a defensible mechanism statement: a cancer digital twin changes remission or survival only if (1) its predictions are accurate enough for the context of use, (2) clinicians act on them by changing drug, dose, schedule or radiation plan, and (3) the changed decision is better than standard care. Evidence for step (3) requires a comparison of twin-guided versus standard-guided care. Prediction accuracy alone is not that evidence.
- Many published "digital twins" are calibrated models without continuous data assimilation or a decision loop. Under the NASEM definition they are better called "virtual patients" or "patient-specific models".

### Gaps
- I found no FDA document that defines "digital twin" specifically for oncology therapeutics. FDA documents use "computational modeling and simulation" and "AI model" with a context of use.

## 2. Mechanistic twins (category a): examples, inputs and measured accuracy

### Takeaway
The most mature mechanistic oncology twins are image-calibrated reaction-diffusion models from the Yankeelov/Hormuth group (UT Austin) for breast cancer and glioma, and PSA-driven evolutionary models from Moffitt for prostate cancer. Their retrospective predictive accuracy is high (CCC around 0.94–0.95 for TNBC volume and cellularity change; pCR AUC 0.82–0.89). Their "optimized treatment" benefits are so far simulated, not delivered to patients.

### Cited Findings
**Breast cancer, TNBC, neoadjuvant chemotherapy (UT Austin / MD Anderson)**
- Wu, Jarrett et al., *Cancer Research* (2022). A reaction-diffusion PDE model (tumor-cell movement, proliferation, treatment-induced death, tissue mechanics) is calibrated to each patient's multiparametric MRI.
  - Data: patients from the ARTEMIS trial (NCT02276443; 56 originally, 50 in Framework 1, 37 in Framework 2: 18 pCR and 19 non-pCR).
  - Inputs: DCE-MRI and DW-MRI (b = 100 and 800 s/mm²) at three timepoints: baseline, after 2 cycles of A/C and after 4 cycles of A/C.
  - Results: CCC 0.95 for change in total tumor cellularity and 0.94 for change in tumor volume. Final pCR prediction AUC 0.89 (95% CI 0.78–0.99), sensitivity 0.72, specificity 0.95, against AUC 0.78 for measured volume alone.
  - Stated limitations: drug delivery is estimated from DCE-MRI rather than from a pharmacokinetic model; the model cannot predict lymph-node involvement; 4 early complete responders were excluded; the Framework 2 cohort was enriched for pCR; paclitaxel parameters were taken from the literature rather than calibrated.
  — [Wu et al., Cancer Res 2022 (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9481712/); [AACR](https://aacrjournals.org/cancerres/article/82/18/3394/709036/MRI-Based-Digital-Models-Forecast-Patient-Specific)
- Wu et al., *npj Digital Medicine* (Apr 7, 2025). The study had 105 TNBC patients.
  - Prediction: the twins predicted pCR with AUC 0.82, and generalizability was shown on an external I-SPY2 multi-institutional dataset.
  - Optimization: each twin was used to "theoretically optimize" the A/C-T schedule among 128 options. The optimized schedules gave a simulated pCR-rate improvement of 20.95–24.76%.
  - Groups: 26 patients were classed as "Escalation" and 79 as "Non-escalation", with pCR rates of 30.77% and 68.35%.
  - The validation is retrospective: twins were "virtually treated" with schedules from historical trials.
  — [Wu et al., npj Digit Med 2025 (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11976917/); [Nature](https://www.nature.com/articles/s41746-025-01579-1)
- A companion 2025 paper in *npj Systems Biology and Applications* personalizes TNBC neoadjuvant regimens with a biology-based twin. Details were not extracted. — [Nature npj SBA 2025](https://www.nature.com/articles/s41540-025-00531-z)

**High-grade glioma, radiotherapy (UT Austin, Oden Institute)**
- Chaudhuri, Pash, Hormuth, Yankeelov, Willcox et al., *Frontiers in AI* (2023). Population-derived priors are personalized by Bayesian calibration to the patient's MRI. Multi-objective risk-based optimization under uncertainty then proposes a radiotherapy regimen.
  - The test was entirely in silico: a cohort of 100 synthetic patients; no real patients were involved.
  - Result: a median increase in time to progression of about 6 days, or a median 16.7% (10 Gy) dose reduction against the standard 60 Gy, with equivalent tumor control.
  — [arXiv 2308.12429 / Front. AI 2023](https://arxiv.org/abs/2308.12429)
- Software: "TumorTwin", a Python framework for patient-specific oncology twins, published in BMC Med Inform Decis Mak (2026). — [Springer 2026](https://link.springer.com/article/10.1186/s12911-026-03520-2)

**Prostate cancer, PSA-based evolutionary and stem-cell models (Moffitt IMO)**
- Brady-Nicholls et al., *Nature Communications* (2020). A prostate cancer stem-cell / non-stem-cell model was calibrated on longitudinal PSA during intermittent androgen deprivation. It predicted response to the next treatment cycle with 73% sensitivity, 91% specificity and 89% accuracy. — [Nat Commun 2020](https://www.nature.com/articles/s41467-020-15424-4)
- A 2025 follow-up in *npj Systems Biology and Applications* evaluates PSA dynamics for predicting androgen-deprivation failure with a patient-specific model. — [npj SBA 2025](https://www.nature.com/articles/s41540-025-00540-y)
- JAMA Oncology (published online Aug 6, 2026), "Mathematical biomarkers of adaptive therapy outcomes in prostate cancer". In extended follow-up, a model-derived adaptive-therapy score and expected time to progression (TTP) were "significantly associated with prolonged overall survival", while standard empirical PSA metrics showed "no association with OS". Authors' limitation: "small cohort sizes ... should be validated in larger, multicycle cohorts, such as the ongoing ANZADAPT trial." — [PMC13448836 (2026)](https://pmc.ncbi.nlm.nih.gov/articles/PMC13448836/)

**Inputs and cadence (summary from the sources above)**
- Breast: serial quantitative MRI (DCE plus DWI) at 2–3 timepoints during neoadjuvant therapy. [Cancer Res 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9481712/)
- Glioma: serial MRI combined with population priors. [arXiv 2308.12429](https://arxiv.org/abs/2308.12429)
- Prostate: serial PSA, typically monthly or each visit, with imaging for progression. [eLife 2022](https://elifesciences.org/articles/76284); [Nat Commun 2020](https://www.nature.com/articles/s41467-020-15424-4)
- Imaging frequency itself is now treated as a design variable in the twin. [Pash et al. 2025](https://arxiv.org/abs/2505.08927)

### Inferences
- In these mechanistic twins, sparse but quantitative longitudinal data (2–3 MRIs, or serial PSA) suffice for calibration. Genomics is generally *not* an input to the published clinical-grade mechanistic models.
- The reported "pCR improvement of 21–25%" and "6 days / 16.7% dose reduction" are model-internal counterfactuals. They should not be cited as clinical benefit.

### Gaps
- I found no published prospective trial in which a Yankeelov-type MRI twin selected a patient's actual chemotherapy or radiotherapy regimen with outcome follow-up, as of Oct 2026. The status of any planned trial could not be confirmed.
- No pooled external accuracy figures for glioma twins on real patient cohorts were extracted.

## 3. Prospective evidence that twin-guided treatment changed outcomes (adaptive abiraterone and others)

### Takeaway
The only prospective clinical evidence I found that model-guided treatment was associated with better outcomes is Moffitt's adaptive abiraterone study in metastatic castration-resistant prostate cancer (mCRPC). Against a standard-of-care cohort it showed median TTP 33.5 vs 14.3 months and median OS 58.5 vs 31.3 months (HR 0.41). It is small and non-randomized, so it shows association, not proven causal benefit. Randomized confirmation (ANZADAPT, NCT05393791) was still ongoing as of the 2026 literature.

### Cited Findings
- Pilot study, Zhang, Cunningham, Gatenby, Brown, *Nature Communications* (2017). Abiraterone was stopped when PSA fell below 50% of the pretreatment value and resumed when PSA returned to baseline, using on/off cycles derived from an evolutionary game-theory model. In 10 of 11 patients tumor burden oscillated stably. Median TTP was at least 27 months, and cumulative drug use was 47% of standard dosing. — [Nat Commun 2017](https://www.nature.com/articles/s41467-017-01968-5); [PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5703947/)
- Updated results, Zhang, Cunningham, Brown, Gatenby, *eLife* (June 2022). There were 17 patients in the adaptive-therapy group and 16 in the standard-of-care (SOC) group.
  - Median OS was 58.5 months vs 31.3 months for SOC (HR 0.41, 95% CI 0.20–0.83, p<0.001).
  - 4 study patients remained stably cycling at 53–70 months.
  - The paper also used the model to identify strategies to improve outcomes further.
  — [eLife 2022;11:e76284](https://elifesciences.org/articles/76284)
- Median TTP was 33.5 months (adaptive) vs 14.3 months (SOC). The 2026 JAMA Oncology paper describes the design as "a nonrandomized study by Zhang et al (April 2015 to January 2022)". — [JAMA Oncol 2026 (PMC13448836)](https://pmc.ncbi.nlm.nih.gov/articles/PMC13448836/)
- One summary gives "approximately 30 months vs about 14 months" for TTP. This likely reflects an earlier data cut. — [search summary of Brady-Nicholls/Moffitt work; primary: eLife 2022](https://elifesciences.org/articles/76284)
- Cost: budget-impact modeling found savings from adaptive abiraterone because of lower cumulative drug use. — [Am Health Drug Benefits / PubMed 33841621](https://pubmed.ncbi.nlm.nih.gov/33841621/)
- Randomized follow-up: ANZADAPT (NCT05393791), a phase 2 adaptive-therapy trial in prostate cancer, is described in 2026 as ongoing and needed to validate the biomarkers. — [JAMA Oncol 2026 (PMC13448836)](https://pmc.ncbi.nlm.nih.gov/articles/PMC13448836/)
- Critique: the eLife paper's comparison and model claims have been debated in published correspondence (e.g., "Response to Mistry"). — [Response to Mistry, PMC7804311](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7804311/)
- Field-level status: an Oct 2025 review classes oncology digital twins as "Pilot/Experimental". It says "few current efforts rise to the level of randomized trials" and that, for cancer avatars, "clinical use is still in its early stages, [though] such models are now informing prospective trial design." — [J Pers Med 2025 (PMC12653454)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12653454/)
- A 2025 *npj Systems Biology and Applications* paper discusses bringing evolutionary cancer therapy to the clinic. A 2023 JCO paper discusses evolutionary dynamics and intermittent therapy for metastatic cancers. — [npj SBA 2025](https://www.nature.com/articles/s41540-025-00528-8); [JCO 2023](https://ascopubs.org/doi/10.1200/JCO.23.00647)

### Inferences
- The adaptive abiraterone result is the strongest "twin changed treatment" case: the model's logic set dosing timing in real patients. Three things limit causal inference:
  - The comparison is non-randomized, so confounding and selection are possible.
  - n is about 17.
  - The on/off rule in practice is a simple PSA threshold, so it is debatable how much of the "twin" was patient-specific in real time.
- Strictly, the field still lacks a randomized trial showing that twin-guided therapy improves remission or survival in any cancer.

### Gaps
- The eLife full text did not load. I could not verify from the primary text whether the SOC cohort was contemporaneous or historical, or how it was matched. The 2026 JAMA Oncology paper only calls it "a standard-of-care cohort" in a nonrandomized study.
- No ANZADAPT readout was found as of Oct 2026.
- Other prospective adaptive-therapy trials (e.g., in melanoma, thyroid and ovarian cancer) were not investigated in depth here.

## 4. AI/ML predictive twins (category b) and virtual/synthetic control arms (category c)

### Takeaway
AI "twins" in trials (Unlearn's PROCOVA) are regulator-accepted as a *statistical efficiency* tool. They are prognostic scores used for covariate adjustment within randomized trials, not treatment-guiding twins. Separately, oncology approvals have used real-world external or "synthetic" control arms. Neither kind has been shown to improve individual patient outcomes. Their value is faster or smaller trials.

### Cited Findings
- In Sept 2022 the EMA issued a qualification opinion for Unlearn's PROCOVA (Prognostic Covariate Adjustment). It is "an acceptable statistical approach for primary analysis" of phase 2/3 trials with continuous endpoints. Patient-level prognostic scores come from ML "digital twins". As a special case of ANCOVA, it gives unbiased treatment-effect estimates and controls type I error. — [EMA qualification opinion PDF](https://www.ema.europa.eu/en/documents/regulatory-procedural-guideline/qualification-opinion-prognostic-covariate-adjustment-procovatm_en.pdf); [Clinical Trials Arena](https://www.clinicaltrialsarena.com/news/ema-qualifies-unlearn-approach/)
- The FDA reportedly concurred with the EMA that PROCOVA does not deviate from its existing covariate-adjustment guidance. This is a company-reported statement. — [Unlearn LinkedIn post](https://www.linkedin.com/pulse/us-fda-comments-unlearns-procova-methodology-unlearn-ai-l31ic)
- Demonstrated sample-size reduction exists mainly outside oncology, e.g., a simulated TRAILBLAZER-ALZ 2 (Alzheimer's) trial. — [PMC12740155](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12740155/)
- The MRCT Center (Sept/Nov 2025) compiled use cases for digital twins and synthetic data in trials. — [MRCT Center 2025 PDF](https://mrctcenter.org/wp-content/uploads/2025/11/2025-11-18-Use-Cases-DigiTwins-and-SynData_Combined.pdf)
- Oncology external control arms:
  - The 2018 FDA approval of avelumab for Merkel cell carcinoma used EHR-derived historical data as context, because short survival precluded a prospective control.
  - The EU label expansion of alectinib (ALK+ NSCLC) used a 67-patient Flatiron Health real-world external control.
  — [Precision Medicine Online](https://www.precisionmedicineonline.com/cancer/synthetic-control-arms-finding-stronger-footing-precision-oncology-trials-regulatory)
- Methods are maturing. Example: the ECLIPSE case study used synthetic real-world data as the external control for the Lung-MAP S1400I single arm (medRxiv 2024). — [medRxiv 2024](https://www.medrxiv.org/content/10.1101/2024.09.10.24313417.full.pdf)
- A related approach is the "virtual patient" in immuno-oncology: quantitative systems pharmacology (QSP) virtual populations used for trial design, as reviewed in 2024. — [arXiv 2403.03335](https://arxiv.org/pdf/2403.03335)
- LLM-enabled twins for rare gynecological tumors appeared in *npj Digital Medicine* (2025). Details were not extracted. — [search result referencing npj DM 2025; see scoping review](https://www.nature.com/articles/s41746-025-01910-w)

### Inferences
- "Digital twin" in Unlearn's sense is a per-patient predicted control outcome. It is closer to a prognostic biomarker than to a mechanistic simulation, and it is not used to choose any patient's therapy.
- External or synthetic control arms are not patient twins at all. They are historical cohorts. Their evidentiary weight depends on bias control, and regulators accept them mainly when randomization is infeasible.

### Gaps
- I found no oncology trial with published, quantified sample-size savings from PROCOVA.
- No head-to-head accuracy figures for multimodal AI twins (imaging, genomics and EHR combined) predicting survival were extracted.

## 5. Programs, regulation and credibility frameworks

### Takeaway
NCI–DOE (ECICC), NSF/NIH and the EU (EDITH/VHT) are funding infrastructure and seed projects. The FDA evaluates in silico evidence through context-of-use credibility frameworks: ASME V&V 40 and the Nov 2023 final CM&S guidance for mechanistic device models, and the Jan 2025 draft AI guidance for drugs and biologics. No oncology twin is FDA-cleared to guide therapy, as far as these sources show.

### Cited Findings
- NCI–DOE ECICC:
  - It began with a July 2020 five-day virtual ideas lab, "Toward Building a Cancer Patient 'Digital Twin'". In late 2020, 5 teams received seed funding through Frederick National Laboratory, and 3 were invited to apply for further DOE funding.
  - Current focus is "cancer patient digital twin" and "predictive radiation oncology".
  - Seed projects covered deep phenotyping with large cohorts of twins, self-learning twin platforms, adaptive twins to monitor response and resistance, and multiscale data fusion.
  — [NCI Hub ECICC](https://ncihub.cancer.gov/groups/cicc/overview); [Frederick National Lab](https://frederick.cancer.gov/news/digital-twins-cancer-care-exploring-cross-disciplinary-innovative-approach); [ECICC perspective "Exploring approaches for predictive cancer patient digital twins", PMC9586248 (2022)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9586248/)
- NCI–DOE recently funded digital twins in radiation oncology (stated Jan 2025). NSF/NIH also fund digital-twin work (2024 announcement). — [NCI blog 2025](https://www.cancer.gov/about-nci/organization/cbiit/news-events/blog/2025/digital-twins-cancer-not-if-when-how-and-why); [NCI 2024 NSF news](https://www.cancer.gov/about-nci/organization/cbiit/news-events/news/2024/national-science-foundation-funding-digital-twin-technology)
- EU:
  - EDITH is a Coordination and Support Action (Digital Europe grant 101083771) with 19 institutions and input from more than 800 people. It published its final Roadmap for the European Virtual Human Twin and a Policy Brief in October 2025.
  - The EU allocates €80M (Horizon Europe) for multiscale patient models and €24M (Digital Europe) for a VHT platform.
  - These are infrastructure and roadmap efforts, not outcome trials.
  — [EDITH roadmap](https://www.edith-csa.eu/roadmap/); [EC VHT initiative](https://digital-strategy.ec.europa.eu/en/policies/virtual-human-twins); [Zenodo record, Oct 22, 2025](https://zenodo.org/records/16910818)
- FDA CM&S credibility guidance (final Nov 2023), for medical devices:
  - It provides a risk-informed framework "heavily based on" ASME V&V 40.
  - It covers first-principles/mechanistic models and *not* ML/AI models.
  — [FDA guidance PDF](https://www.fda.gov/media/154985/download); [StarFish Medical summary](https://starfishmedical.com/resource/fda-guidance-on-cms-in-medical-device-submissions/)
- FDA draft guidance (Jan 6, 2025), "Considerations for the Use of AI to Support Regulatory Decision-Making for Drug and Biological Products", sets a 7-step risk-based credibility framework:
  1. Question of interest.
  2. Context of use.
  3. Model risk.
  4. Credibility plan.
  5. Execute the plan.
  6. Document results and deviations.
  7. Decide adequacy for the context of use.
  — [DLA Piper summary](https://www.dlapiper.com/en-us/insights/publications/2025/01/fda-releases-draft-guidance-on-use-of-ai); [critical review 2026, J Chem](https://onlinelibrary.wiley.com/doi/10.1155/joch/5202999)
- VVUQ survey, *npj Digital Medicine* (2025): verification, validation and uncertainty quantification are critical to twin safety and efficacy, with examples in cardiology and oncology. A scoping review found that only two oncology-twin studies mentioned VVUQ. — [npj DM 2025 VVUQ survey](https://www.nature.com/articles/s41746-025-01447-y); [scoping review npj DM 2025](https://www.nature.com/articles/s41746-025-01910-w)

### Inferences
- A treatment-guiding oncology twin would likely be regulated as software as a medical device or clinical decision support. Its required evidence would scale with "model influence × decision consequence" (V&V 40). Dose or schedule selection for cancer therapy is high-consequence, which implies prospective validation.

### Gaps
- I could not confirm whether the Jan 2025 FDA AI draft guidance was finalized by Oct 2026.
- I found no FDA-cleared or approved oncology digital twin that guides therapy.

## 6. Main limitations: data scarcity, validation, bias, overclaiming

### Takeaway
Cancer twins are limited by four problems:
- Small, single-center calibration cohorts.
- Retrospective or synthetic validation.
- Rare VVUQ reporting.
- Unrepresentative training data.

Much of the literature overstates in silico "optimization" gains as if they were clinical benefit.

### Cited Findings
- Models are typically fitted to populations, and "lose accuracy when applied to individual cases changing over time" (NCI, 2025). — [NCI blog 2025](https://www.cancer.gov/about-nci/organization/cbiit/news-events/blog/2025/digital-twins-cancer-not-if-when-how-and-why)
- Development datasets "frequently do not include ... comorbidities, polypharmacy, non-adherence, or socio-environmental determinants". A twin's performance "may suffer if it was trained primarily on data from White, male, urban populations". Most oncology twins remain "limited to pilot tests or experimental settings" (2025). — [J Pers Med 2025 (PMC12653454)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12653454/)
- Only two oncology-twin studies in a 2025 review mentioned VVUQ. — [npj DM 2025 scoping review](https://www.nature.com/articles/s41746-025-01910-w); [VVUQ survey](https://www.nature.com/articles/s41746-025-01447-y)
- Specific study limitations:
  - TNBC model: no lymph-node prediction, pCR-enriched cohort, literature-fixed paclitaxel parameters. [Cancer Res 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9481712/)
  - Glioma RT twin: tested only on 100 synthetic patients. [arXiv 2308.12429](https://arxiv.org/abs/2308.12429)
  - Prostate biomarkers: "small cohort sizes". [JAMA Oncol 2026](https://pmc.ncbi.nlm.nih.gov/articles/PMC13448836/)
- Breast twins have shown retrospective convergence between simulated and actual trajectories, mainly in breast cancer and melanoma. That is not prospective benefit. — [J Pers Med 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12653454/); [Frontiers review on tumor-therapy DTs (2025)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11921680/)

### Inferences
- Overclaiming pattern: headlines such as "digital twins improve pCR by 21–25%" (npj DM 2025) describe counterfactual simulations on retrospective cohorts. A fair summary separates three levels:
  - Prediction: validated retrospectively, sometimes externally (I-SPY2).
  - Decision optimization: simulated only.
  - Outcome benefit: prospective, non-randomized evidence only in prostate adaptive therapy.
- Data needs are a bottleneck. Quantitative serial MRI (DCE plus DWI at standardized timepoints) is not routine care, so twins built on it may not transfer to community settings.

### Gaps
- I found no systematic meta-analysis of oncology-twin prediction accuracy across studies.
- I found no published evidence on the cost or feasibility of the imaging cadence that twins need in routine practice.
- A Medscape 2026 piece ("AI Digital Twins Get Better and Better: Cancer in Crosshairs") was found but not read, so any 2026 developments it reports are unverified. — [Medscape 2026](https://www.medscape.com/viewarticle/ai-digital-twins-get-better-and-better-cancer-crosshairs-2026a1000yav)
