# Public datasets and benchmarks for EEG-based visual decoding and image reconstruction (as of October 2026)

Scope: non-invasive EEG only. Every figure below has a source link. Items marked **[unverified]** came from search snippets or from summaries of PDFs that the fetch tool could not parse. Check them against the primary paper before quoting them. Numbers marked **[derived]** are arithmetic on sourced numbers.

## The main datasets: what each contains, and its license

### Takeaway
For EEG-to-image work the de facto benchmark is THINGS-EEG2: 10 subjects, 63 channels at 1000 Hz, 16,540 training images × 4 repetitions and 200 test images × 80 repetitions, CC-BY 4.0. The largest dataset is Alljoined-1.6M: 20 subjects, an Emotiv Flex 2 consumer headset, 32 channels at 256 Hz, the same THINGS split, licensed CC BY-NC-ND 4.0. EEG-CVPR40 ("ImageNet-EEG", Spampinato 2017) and EEG-ImageNet (2024) both present each category's images consecutively, so they inherit the block-design confound. New datasets from 2025–2026 add multi-session data (Xue 2025, 122 channels), visual imagery (Gao 2026) and video.

### Cited Findings

**THINGS-EEG2 (Gifford, Dwivedi, Roig & Cichy, NeuroImage 264:119754, 2022)**
- 10 subjects; 16,540 distinct training images and 200 test images (each test image repeated about 80 times); RSVP at 5 Hz; BrainVision actiCHamp at 1000 Hz; the source files hold 63 EEG channels because the online reference is not stored — [NEMAR GitHub nm000232](https://github.com/nemarDatasets/nm000232)
- 4 sessions per subject; tasks: rest, rest1, rest2, test, train; 63 channels (10-10 system), 1000 Hz; BIDS, with a Zarr conversion available; **241.5 GB in total**; **CC-BY 4.0**; DOI 10.82901/nemar.nm000232; data at https://data.nemar.org/nm000232/v1.1.0/ (v1.1.0, 5 July 2026); includes the authors' preprocessed epochs, the stimulus images and resting-state recordings — [NEMAR nm000232](https://nemar.org/dataset/nm000232)
- The source, raw and preprocessed data are on OSF at https://osf.io/3jk45/. The training and test images, and the ILSVRC-2012 files the repo uses, are downloaded separately. The repo ships a Colab tutorial that loads the preprocessed data — [gifale95/eeg_encoding](https://github.com/gifale95/eeg_encoding)
- The NICE paper describes the standard split as "1654 concepts × 10 images × 4 repetitions" for training and "200 concepts × 1 image × 80 repetitions" for testing — [Song et al., arXiv 2308.13234 / ICLR 2024](https://arxiv.org/html/2308.13234)
- The NeurIPS-style "Neural Interfaces 2026" challenge lists THINGS-EEG2 as "10 participants, 87 hours, 63 channels at 1000 Hz" — [neural-interfaces26 Tracks & Data](https://neural-interfaces26.github.io/tracks.html)
- Trials per subject: 16,540 × 4 + 200 × 80 = **82,160** **[derived]**
- **[unverified]** From memory and not confirmed in a fetched source: stimuli are shown for 100 ms with a 100 ms blank (consistent with the 5 Hz rate); the authors' preprocessed release keeps 17 occipital and parietal channels, downsampled to 100 Hz, in a −200 to 800 ms window, as .npy files.

**THINGS-EEG / "THINGS-EEG1" (Grootswagers, Zhou, Robinson, Hebart & Carlson, Scientific Data 2022)**
- 50 subjects; 22,248 images from 1,854 object concepts; RSVP streams at 10 Hz; an orthogonal task (detecting a change in fixation colour); about 1 hour per subject — [OpenNeuro ds003825 (search listing)](https://openneuro.org/datasets/ds003825); [Sci Data paper](https://www.nature.com/articles/s41597-021-01102-7); [OSF hd6zk](https://osf.io/hd6zk/overview); [bioRxiv preprint](https://www.biorxiv.org/content/10.1101/2021.06.03.447008v2.full.pdf)
- **[unverified]** The EEG system, channel count (I believe 64-channel BrainVision at 1000 Hz), the validation-set structure (200 validation images with repeats), any subject exclusions and the license. The OpenNeuro page renders client-side and the bioRxiv full text returned HTTP 429 or the user declined the fetch. OpenNeuro datasets are normally CC0, but I did not confirm it for this one.

**EEG-CVPR40 / "ImageNet-EEG" / PeRCeiVe "EEG visual classification" (Spampinato et al., CVPR 2017; Palazzo et al., TPAMI 2020)**
- 6 subjects; 40 ImageNet classes × 50 images = 2,000 images; 128 channels; 1 kHz; 0.5 s per image; images of each class "shown consecutively in a single sequence" with "a 10-second black screen" between class blocks; 11,964 valid segments (36 excluded); signals cut to 440 samples per channel (the first 20 ms dropped); released in three band-passed versions: 5–95 Hz, 14–70 Hz and 55–95 Hz; download at tinyurl.com/eeg-visual-classification — [perceivelab/eeg_visual_classification](https://github.com/perceivelab/eeg_visual_classification)
- Recorded with a 128-channel actiCAP 128Ch2 and BrainVision DAQ — [search summary citing PMC6921386 and related](https://pmc.ncbi.nlm.nih.gov/articles/PMC6921386/) **[snippet-level]**
- License: **not stated** on the repository page. File format and the official split file were not confirmed in a fetched source; the community uses PyTorch `.pth` dicts with a "block_splits" file **[unverified]**.

**EEG-ImageNet (Zhu et al., arXiv 2406.07151, 2024; later renamed "CrossPT-EEG")**
- v1: 16 subjects (10 male, 6 female, aged 21–27); 4,000 ImageNet-21k images in 80 categories × 50 images (40 coarse-grained categories plus 40 fine-grained ones in 5 groups of 8 sharing a WordNet parent); 63,850 EEG-image pairs; **15.88 GB**; Compumedics Neuroscan NuAmps Express with a 64-channel Quik-Cap, 62 channels used, 1000 Hz; RSVP with 500 ms per image; **"Images of the same category are sequentially presented"** (block design), with category order randomized; one session of about 2 hours per subject; benchmark split: the first 30 images of each category for training, the last 20 for testing; distributed as two `.pth` files (8 subjects each) from https://github.com/Promise-Z5Q2SQ/EEG-ImageNet-Dataset — [arXiv 2406.07151v1 HTML](https://arxiv.org/html/2406.07151v1)
- v1 baselines: 80-class 40.50% (RGNN), 40 coarse classes 53.39% (MLP), 8 fine classes 81.63% (MLP); reconstruction two-way identification 64.67% with CLIP ViT-L/14 (chance 50%) — [arXiv 2406.07151v1](https://arxiv.org/html/2406.07151v1)
- The current arXiv version is titled "CrossPT-EEG: A Benchmark for Cross-Participant and Cross-Time Generalization of EEG-based Visual Decoding". It describes 16 participants, 4,000 images, "two collection stages separated in time" and a design that avoids "block-design artifacts" — [arXiv 2406.07151 abs](https://arxiv.org/abs/2406.07151). **Conflict:** v1 says images of a category were presented consecutively, while the later version says it avoids block-design artifacts. It is unclear whether new data was recorded. Check which release you downloaded.
- Dataset license: the fetch only found the arXiv paper license ("perpetual non-exclusive"), which is not a data license. **The data license is unknown.**

**Alljoined1 (Alljoined, arXiv 2404.05553, 2024)**
- 8 subjects (6 male, 2 female), 2 sessions each; 10,000 images per subject (9,000 unique plus 1,000 shared) from MS-COCO via the Natural Scenes Dataset (NSD); each image shown 4 times; 46,080 epochs in total; BioSemi ActiveTwo, 64 channels, 512 Hz, 24-bit; 300 ms on, 300 ms ISI plus 0–50 ms jitter; one-back task (24 oddball trials per block); preprocessing: 0.5–125 Hz band-pass, ICA, autoreject; on average 130.75 ± 260.44 epochs dropped per subject; SNR peaks at 150 ms; data on OSF https://osf.io/kqgs8/; **CC BY 4.0** — [arXiv 2404.05553v1 HTML](https://arxiv.org/html/2404.05553v1); [abs](https://arxiv.org/abs/2404.05553)
- Inconsistency: 8 × 10,000 × 4 would be 320,000 presentations, which does not match 46,080 epochs. Not every image appears to have been shown 4 times to every subject. **[unresolved]**

**Alljoined-1.6M (arXiv 2508.18571, 2025)**
- 20 subjects (aged 23–63; 15 male, 5 female) × 4 sessions, about 8 h on task per subject; 83,520 trials per subject; more than 1.6 M trials in total; 16,740 THINGS images (16,540 training images shown 4–5 times, 200 test images shown 80 times); **Emotiv Flex 2** (about $2.2k, wet electrodes), **32 channels**, **256 Hz**; 100 ms image plus 100 ms blank; epochs −200 to 1000 ms, resampled to 250 Hz, multivariate noise normalization; 0–0.6% of trials excluded for trigger mismatches; HF: https://huggingface.co/datasets/Alljoined/Alljoined-1.6M; code: https://github.com/Alljoined/Alljoined-1.6M; **.edf**; **CC BY-NC-ND 4.0** — [arXiv 2508.18571 HTML](https://arxiv.org/html/2508.18571)
- Also on NEMAR as nm000134 — [GitHub nemarDatasets/nm000134](https://github.com/nemarDatasets/nm000134)
- Challenge listing: "20 participants, 130 hours, 32 channels at 256 Hz, 7.7 GB", plus a sealed 2026 evaluation cohort of 11 new participants — [neural-interfaces26](https://neural-interfaces26.github.io/tracks.html)

**Xue et al. 2025, "A multi-subject and multi-session EEG dataset for modelling human visual object recognition" (Scientific Data 12:663, 19 April 2025)**
- 32 subjects; 122 channels; 1–5 sessions per subject on different days, about 1.5 h of EEG per session; 10,000 images, 500 per class, from PASCAL and ImageNet (so 20 classes **[derived]**); built for cross-subject and cross-session BCI work; OpenNeuro **ds005589** — [Sci Data](https://www.nature.com/articles/s41597-025-04843-x); [PubMed 40253381](https://pubmed.ncbi.nlm.nih.gov/40253381/); [OpenNeuro ds005589](https://openneuro.org/datasets/ds005589/versions/1.0.1)
- Sampling rate, presentation timing, license and size were not retrieved: the OpenNeuro page did not render and nature.com redirected to a login.

**Gao et al. 2026, "An EEG Dataset for Visual Imagery-Based Brain–Computer Interface" (Scientific Data)**
- 22 subjects (20 with 2 sessions, 2 with 1); 16,800 trials; 10 imagined items in three groups — animals (dog, bird, fish), figures (pentagram, square, circle) and objects (scissors, watch, cup, chair); 4 s trials, 3 runs per session, cued synchronous imagery; Neuracle NeuSenW32, 32 channels, 1000 Hz, CPz reference; **BDF**; **CC-BY-NC-ND-4.0**; Figshare DOI 10.6084/m9.figshare.30227503; paper DOI 10.1038/s41597-025-06512-5 — [NEMAR nm000242](https://github.com/nemarDatasets/nm000242); [Sci Data](https://www.nature.com/articles/s41597-025-06512-5)
- The listing gives 10 class names, but the fetched NEMAR summary lists 4 objects (scissor, watch, cup, chair), which makes 11. **[inconsistent — check the paper]**

**Other datasets found (less detail retrieved)**
- **MindBigData "ImageNet of the Brain"** (v1.04): 70,060 three-second signals from **one subject** (David Vivancos) on an **Emotiv Insight, 5 channels** (AF3, AF4, T7, T8, Pz), viewing 14,012 ILSVRC2013 training images; spectrograms included for 10,032 images — [mindbigdata.com/opendb/imagenet](https://mindbigdata.com/opendb/imagenet.html); [MindBigData 2022, arXiv 2212.14746](https://arxiv.org/pdf/2212.14746)
- **EIT-1M** (arXiv 2407.01884): "over 1 million EEG-image-text pairs", images alternating with category text, 60K natural images; the abstract gives no hardware, channel count, sampling rate or license — [arXiv 2407.01884](https://arxiv.org/abs/2407.01884)
- **EEG dataset for natural image recognition through visual stimuli** (Data in Brief 2025): 32 subjects, VEPs to natural images, for classification and reconstruction — [Mendeley g9shp2gxhy v2](https://data.mendeley.com/datasets/g9shp2gxhy/2); [PubMed 40496741](https://pubmed.ncbi.nlm.nih.gov/40496741/) (hardware not retrieved)
- **YOTO ("You Only Think Once")**: a human EEG dataset for multisensory perception and mental imagery (bioRxiv 2025) — [bioRxiv 2025.04.17.645384](https://www.biorxiv.org/content/10.1101/2025.04.17.645384.full.pdf) (title only)
- **Naturalistic video EEG**: "A large dataset of human EEG responses to short naturalistic videos for studying dynamic visual event processing" (arXiv, 28 August 2026) — [arXiv 2608.28768](https://arxiv.org/abs/2608.28768) (title only)

**MOABB**
- MOABB's visual datasets are P300/ERP (e.g. Lee2019_ERP: 54 subjects, 62 channels, 1000 Hz; BNCI2014_008: 8 subjects, 8 channels, 256 Hz; Huebner2017; Zhang2025), SSVEP (Lee2019_SSVEP, Liu2020BETA: 70 subjects, 64 channels, 250 Hz; Wang2016; Nakanishi2015) and c-VEP (Thielen2021, CastillosCVEP100). **None are natural-image or object-decoding datasets.** MOABB can load external BIDS data through `LocalBIDSDataset` — [MOABB dataset summary](https://moabb.neurotechx.com/docs/dataset_summary.html)

### Inferences
- If you need a permissive license that allows derivatives, use THINGS-EEG2 (CC-BY 4.0) or Alljoined1 (CC BY 4.0). Alljoined-1.6M and Gao 2026 are NoDerivatives and NonCommercial, so a model trained on them and shipped commercially, or a redistributed processed copy, needs legal review.
- The stimulus images carry their own terms, separate from the EEG license (THINGS image licenses, ImageNet terms of access, COCO). The THINGS-EEG2 repo already makes users download ImageNet files separately.
- Do not use MOABB for EEG-to-image work. Its value here is as a loader and pipeline framework.

### Gaps
- No verified per-dataset license for THINGS-EEG1, EEG-CVPR40, EEG-ImageNet or Xue 2025.
- On-disk size was found only for THINGS-EEG2 (241.5 GB BIDS raw), EEG-ImageNet (15.88 GB) and Alljoined-1.6M (7.7 GB per the challenge page).
- Whether EEG-ImageNet/CrossPT-EEG v2 is a new recording is unresolved.
- EIT-1M hardware and availability are not verified, and I found no independent audit of it.

## The block-design controversy around EEG-CVPR40

### Takeaway
Li et al. (Purdue, Siskind group) showed that EEG-CVPR40's high accuracy comes mostly from its block design. Every image of a class is shown in one consecutive block, so a classifier can learn slow, block-specific signals, and test trials come from the same blocks as training trials ("training on the test set"). When the presentation order is randomized, accuracy falls to around chance. Palazzo, Spampinato et al. replied that the effect is "drastically overstated", but conceded that slow low-frequency activity can inflate accuracy, and they report about 50% (not the original high figures) on new block-design data. The field's working consensus treats raw EEG-CVPR40 accuracies as unreliable evidence of stimulus decoding.

### Cited Findings
- Li et al., first posted as "Training on the test set? An analysis of Spampinato et al." (arXiv 1812.07697, 18 December 2018): results "depend critically" on a block design in which same-class stimuli are presented in sequence; the result fails when stimulus order is randomized; test trials come from blocks that also contain training data; "random codebooks" match or beat the EEG-derived representations — [arXiv 1812.07697](https://arxiv.org/abs/1812.07697)
- Published as "The Perils and Pitfalls of Block Design for EEG Classification Experiments", IEEE TPAMI (DOI 10.1109/TPAMI.2020.2973153) — [PDF (Purdue)](https://engineering.purdue.edu/~qobi/papers/tpami2021.pdf); [DOI](https://doi.org/10.1109/tpami.2020.2973153)
- **[unverified, from a summary of a PDF the tool could not parse]** Spampinato's original figure is about 82.9%. Li et al. reproduce high accuracy with block design but get near-chance results (40-way chance = 2.5%) with rapid-event or randomized design. The released data is reported not to match the band-pass filtering described, and accuracy changes once filtering is applied properly. Classifiers can also separate labels unrelated to the stimulus. — [Purdue PDF](https://engineering.purdue.edu/~qobi/papers/tpami2021.pdf)
- Reply: Palazzo, Spampinato et al., "Correct block-design experiments mitigate temporal correlation bias in EEG classification" (arXiv 2012.03849). They say the main claim "is drastically overstated" and that other analyses are "seriously flawed", but accept that low-frequency slow EEG activity can inflate classifier performance. On newly recorded data they report about 50% accuracy over 40 classes ("lower than in [2], but still significant"). Their rapid-design experiments give accuracy "at or near chance". They could reproduce Li et al.'s results only "when intentionally contaminating our data by inducing a temporal correlation". They argue that keeping each experiment short is what mitigates the bias. — [arXiv 2012.03849](https://arxiv.org/abs/2012.03849); [Semantic Scholar](https://www.semanticscholar.org/paper/Correct-block-design-experiments-mitigate-temporal-Palazzo-Spampinato/ffed2ef1ff1b82c10f3cd08a0d11c021244eaec4)
- Later work cites the critique as settled. NICE (ICLR 2024) calls the Spampinato experiments "flawed block-design" ones that allow classification "relying on block-level temporal correlation rather than stimulus-related activity" — [arXiv 2308.13234](https://arxiv.org/html/2308.13234)
- Alljoined1 justifies its randomized within-block design by pointing to "block-specific stimulus patterns" in earlier datasets — [arXiv 2404.05553v1](https://arxiv.org/html/2404.05553v1)
- EEG-ImageNet v1 also presents same-category images in sequence and notes a residual "temporal effect" as a limitation — [arXiv 2406.07151v1](https://arxiv.org/html/2406.07151v1)

### Inferences
- Classification or reconstruction numbers on EEG-CVPR40 (and on EEG-ImageNet v1, which uses the same per-category sequencing) should not be compared with THINGS-EEG2 or Alljoined numbers. They likely measure temporal and block context as well as visual content. "Reconstructions" on EEG-CVPR40 can work as class-conditional generation from a block-identity code.
- Minimum safeguards for any new dataset: interleave classes in a randomized order, take the test set from separate runs or sessions, report a randomized-order control, and check performance with slow drift removed (high-pass filtering, per-block detrending).

### Gaps
- I could not extract exact sentences and numbers from the TPAMI PDF: no PDF text extractor is installed and the fetch tool returned a generic summary. Ahmed, Wilbur, Bharadwaj & Siskind, "Object classification from randomized EEG trials" (CVPR 2021), a follow-up, was not fetched.
- I found no further rejoinder after Palazzo et al. 2020/21.

## Evaluation protocols and comparability across papers

### Takeaway
The THINGS-EEG2 protocol: train on 1,654 concepts × 10 images × 4 repetitions; test zero-shot on 200 unseen concepts × 1 image × 80 repetitions, averaged; report 200-way top-1 and top-5 retrieval (chance 0.5%), intra-subject and leave-one-subject-out. Reconstruction adds PixCorr, SSIM, AlexNet(2/5), Inception, CLIP and SwAV-style metrics plus human 2AFC. Results across papers are only roughly comparable. Papers differ in how many test repetitions they average (1, 4 or 80), the channel set (17 vs 63), the time window, the sampling rate, the image-embedding target (CLIP vs DINOv2) and whether test-set averaging or noise normalization is used. Single-trial and challenge protocols are starting to replace the averaged one.

### Cited Findings
- NICE preprocessing on THINGS-EEG2: 63 channels, downsampled to 250 Hz, 0–1000 ms window, baseline from the 200 ms before stimulus, multivariate noise normalization fitted on training data, all repetitions of an image averaged. Zero-shot 200-way top-1/top-5 (chance 0.5%). Intra-subject: NICE 13.8% / 39.5%, NICE-GA 15.6% / 42.8%, BraVL 5.8% / 17.5%. Inter-subject (leave-one-subject-out): NICE 6.2% / 21.4% — [arXiv 2308.13234](https://arxiv.org/html/2308.13234)
- The Alljoined-1.6M protocol mirrors THINGS-EEG2: no category overlap between training and test, 7 meta-categories for generalization analysis, top-1/5/10 200-way retrieval, CLIP similarity, SSIM, PixCorr, AlexNet layers, and human identification (545 raters, 2AFC). ENIGMA results — THINGS-EEG2: CLIP 78.90%, top-1 27.60%, human ID 83.06%; Alljoined-1.6M: CLIP 62.91%, top-1 6.00%, human ID 65.43% — [arXiv 2508.18571](https://arxiv.org/html/2508.18571); ENIGMA paper: [arXiv 2602.10361](https://arxiv.org/html/2602.10361v1)
- The intra-subject top-1 on THINGS-EEG2 roughly doubled from NICE (13.8%, ICLR 2024) to ENIGMA (27.6%, 2026) under the averaged-test protocol — compare the two sources above.
- Repetition count matters. NEAR (arXiv 2608.19128) targets few-repetition retrieval on THINGS-EEG2 and reports +5.7 and +9.3 points 200-way top-1 when averaging 1 and 4 repetitions respectively. It identifies a "non-transitive alignment pattern": low-repetition queries and image representations each align with the high-repetition centre but not with each other — [arXiv 2608.19128](https://arxiv.org/abs/2608.19128)
- Neural Interfaces 2026 challenge, Track 01 (EEG-to-image): **single EEG epoch** → rank held-out candidates in a **frozen DINOv2** embedding space; metric: **top-5 retrieval**; training and test images do not overlap. Warm-up on the THINGS-EEG2 test split; hidden evaluation on new participants and image galleries (Alljoined 2026 cohort, 11 participants). BIDS data, starter kit, NeuralBench integration — [neural-interfaces26](https://neural-interfaces26.github.io/tracks.html)
- EEG-ImageNet's own protocol is a within-category image split (first 30 / last 20 per category), which is closed-set classification, not zero-shot — [arXiv 2406.07151v1](https://arxiv.org/html/2406.07151v1)
- A 2025 paper proposes "Multigranular Evaluation for Brain Visual Decoding", a sign that reconstruction metrics are disputed — [arXiv 2507.07993](https://arxiv.org/pdf/2507.07993) (title only)

### Inferences
- When comparing papers, normalize on: (a) test-repetition averaging (80 vs 1); (b) channel set (17 posterior vs 63); (c) window and sampling rate; (d) intra- vs inter-subject; (e) target embedding (CLIP ViT-H/14, ViT-L/14, DINOv2); (f) whether hyperparameters or checkpoints were chosen on the test set (THINGS-EEG2 has no official validation split, so many papers hold out training images).
- An 80-repetition average is not a realistic BCI condition. Single-trial numbers (as in the 2026 challenge) are the deployable figure and are much lower.

### Gaps
- I found no systematic meta-analysis that re-runs published methods under one THINGS-EEG2 protocol.
- Many papers use the 17-channel, 100 Hz preprocessed release, but that variant is **[unverified]** here.

## Consumer and low-channel headsets

### Takeaway
Yes. Alljoined-1.6M (Emotiv Flex 2, 32 channels, 256 Hz, 20 subjects) is the main consumer-grade EEG-image dataset. MindBigData (Emotiv Insight, 5 channels, one subject) is older and much weaker. Consumer data decodes high-level semantics but at much lower accuracy: 6.0% vs 27.6% 200-way top-1 for the same model. Accuracy scales log-linearly with data, and gains flatten above about 24 channels. I found no Muse- or OpenBCI-based EEG-to-image dataset of comparable scale.

### Cited Findings
- Emotiv Flex 2, about $2.2k, said to be "~27x cheaper" than a research-grade system (about $60k, 64 channels); "log-linear decoding performance with increasing data volume" with "no sign of saturation"; consumer hardware "scaled less efficiently" than research-grade; "performance gains start to drop off after 24 channels"; limitations: one headset model, laboratory setting with healthy adults, RSVP lowers SNR at later latencies — [arXiv 2508.18571](https://arxiv.org/html/2508.18571); [Alljoined blog](https://www.alljoined.com/blog/introducing-alljoined-1-6m)
- ENIGMA: top-1 6.00% (Alljoined-1.6M) vs 27.60% (THINGS-EEG2); human identification 65.43% vs 83.06% — [arXiv 2508.18571](https://arxiv.org/html/2508.18571)
- MindBigData ImageNet: Emotiv Insight, 5 channels, a single subject, 14,012 images, 70,060 three-second signals — [mindbigdata.com](https://mindbigdata.com/opendb/imagenet.html)
- The 2026 challenge deliberately tests across "institutional hardware (Emotiv) and consumer-grade recording equipment" — [neural-interfaces26](https://neural-interfaces26.github.io/tracks.html)

### Inferences
- For a low-cost prototype (for example the project's `neurovisual/` with BrainFlow/LSL), Alljoined-1.6M is the closest public reference. Expect semantic, category-level reconstructions rather than pixel fidelity, and plan to average repetitions or accept low single-trial accuracy.
- Muse (4 frontal/temporal channels) and 8–16-channel OpenBCI montages lack occipital coverage or channel count. Given the channel ablation above, expect worse results than with the Flex 2. This is not measured on a public image dataset.

### Gaps
- No public EEG-to-image dataset recorded with Muse or OpenBCI was found within the search budget.

## Formats and loading

### Takeaway
Distribution is converging on BIDS (THINGS-EEG2 on NEMAR, Alljoined-1.6M on NEMAR, the 2026 challenge, OpenNeuro datasets), alongside author-preprocessed arrays: THINGS-EEG2 on OSF, EEG-ImageNet and EEG-CVPR40 as PyTorch `.pth`. Raw files are BrainVision (THINGS), EDF (Alljoined-1.6M) and BDF (BioSemi, Neuracle).

### Cited Findings
- THINGS-EEG2: BIDS plus a Zarr conversion, 241.5 GB, downloadable with the NEMAR CLI, DataLad, git-annex or plain HTTPS — [NEMAR](https://nemar.org/dataset/nm000232). Source, raw and preprocessed data on OSF, with a Colab loader — [eeg_encoding](https://github.com/gifale95/eeg_encoding)
- Alljoined-1.6M: `.edf`, processed with MNE-Python, on Hugging Face — [arXiv 2508.18571](https://arxiv.org/html/2508.18571)
- EEG-ImageNet: two `.pth` files — [arXiv 2406.07151v1](https://arxiv.org/html/2406.07151v1)
- Gao 2026 imagery: BDF, standard_1005 montage — [nm000242](https://github.com/nemarDatasets/nm000242)
- MOABB: `LocalBIDSDataset` for external BIDS data, which yields MNE Raw objects — [MOABB](https://moabb.neurotechx.com/docs/dataset_summary.html)

### Inferences
- The MNE readers are the standard API calls, though no specific documentation page was fetched for them: BrainVision via `mne.io.read_raw_brainvision`, EDF and BDF via `mne.io.read_raw_edf` / `read_raw_bdf`, and BIDS via `mne_bids.read_raw_bids(BIDSPath(...))`. `.pth` files need `torch.load`. Preprocessed `.npy` dict files need `numpy.load(..., allow_pickle=True)` **[unverified for THINGS-EEG2]**. **Security note:** both are pickle-based and can run arbitrary code when loaded. Use `torch.load(..., weights_only=True)` where it works, load only from the official source with a checked hash, or convert the files once inside a sandbox. The BIDS, EDF and BDF routes do not have this risk.
- For this repository, a loader that maps THINGS-EEG2 or Alljoined into `neurovisual/datasets.py` training records would use the BIDS or EDF route through MNE. The raw data stays off the chain (see CLAUDE.md); only public metadata and hashes may be recorded.

### Gaps
- Exact file layout and array shapes of the THINGS-EEG2 preprocessed release were not confirmed.
- Hugging Face file listing and size for Alljoined-1.6M were not fetched; 7.7 GB comes from the challenge page.
