# EEG decoding of mental imagery, visual memory recall and imagination, and real-time feasibility with available hardware (as of October 2026)

Scope note: non-invasive only. Results are labelled **[PERCEPTION]** (image on screen), **[IMAGERY]** (imagining a cued image) or **[RECALL]** (retrieving a stored episode). Findings from before 2023 are marked **(older)**. Some primary pages (Nature, PMC, Taylor & Francis, MIT Press, bioRxiv PDFs) blocked automated fetching (403 errors, CAPTCHAs, 429 rate limits). For those, the figures below come from search-engine abstracts and snippets of the primary source and are marked "(abstract/snippet)".

## Perception vs imagery: how well can imagined or recalled images be decoded from EEG, and how does that compare with fMRI?

### Takeaway
EEG imagery decoding that works today is **closed-set classification of a few well-trained classes** (about 60–76 % within a category of 3–4 items, as of 2025). No peer-reviewed EEG study I found reconstructs an arbitrary imagined natural image. Even the best fMRI systems lose 6–26 percentage points of 2-way identification accuracy going from perception to imagery, and the best perception model (MindEye2) falls to about 57 % (chance 50 %) on imagery. So EEG imagery reconstruction will be weaker still and mostly carried by the generative prior.

### Cited Findings
**EEG, imagery [IMAGERY]**
- A 2025 *Scientific Data* dataset (visual-imagery BCI): 22 participants, 2 sessions each, 32-channel EEG at 1000 Hz. Participants imagined 10 images in three categories: figures (circle, square, pentagram), animals (dog, fish, bird) and objects (cup, chair, watch, scissors) — [Scientific Data 2025, s41597-025-06512-5](https://www.nature.com/articles/s41597-025-06512-5); [PMC mirror](https://pmc.ncbi.nlm.nih.gov/articles/PMC12886826/) (abstract/snippet).
- On that dataset, EEGNet reached average accuracies of **75.8 % for animal imagery, 75.1 % for figure imagery and 62.0 % for object imagery**. These are within-category tasks with 3–4 classes, so chance is about 25–33 % — [Scientific Data 2025](https://www.nature.com/articles/s41597-025-06512-5) (snippet; the exact protocol and chance level could not be verified because the page blocked fetching).
- (older, 2022) "Improving classification and reconstruction of imagined images from EEG signals" used a Sinc-EEGNet with an attention module on EEG from perception **and** imagination, and reconstructed images with a GAN. Pooling perception and imagination EEG improved imagery classification — [bioRxiv 2022.06.01.494379](https://www.biorxiv.org/content/10.1101/2022.06.01.494379v1.full.pdf).
- A 2025 PubMed-indexed study proposed a topomap-sequence framework (dense sequences of scalp voltage maps) for "distinguishing pictorial imagination from perception" — [PubMed 41336067](https://pubmed.ncbi.nlm.nih.gov/41336067/). Its abstract could not be retrieved (cookie wall), so no figures are given here.
- 2026: "CSOANet2026", a 3,028-parameter CNN with FIR/ICA preprocessing, tested on 46 subjects. It reports **98.67 % ± 2.46 % within-subject** and **96.73 % ± 6.31 % leave-one-subject-out** accuracy, with inference in **3.99 ± 0.60 ms on CPU / 0.81 ± 0.16 ms on GPU**, "meeting real-time constraints for closed-loop neurofeedback" — [Taylor & Francis, Computer Methods in Biomechanics and Biomedical Engineering: Imaging & Visualization, 2026, doi 10.1080/21681163.2026.2684109](https://www.tandfonline.com/doi/full/10.1080/21681163.2026.2684109?af=R) (abstract/snippet). **Caution:** the task appears to be perception-versus-imagination state classification, not decoding *what* is imagined. Such near-ceiling figures are typical of state discrimination, not of content decoding. I could not verify the number of classes.
- Other 2025–2026 EEG imagery work cited in search results: decoding imagined arrows with different colours and directions ([Biosensors 2026, doi 10.3390/bios16070383](https://doi.org/10.3390/bios16070383)); "Efficient Transformer-Integrated Deep Neural Architectures for Robust EEG Decoding of Complex Visual Imagery" ([arXiv 2511.15218](https://arxiv.org/pdf/2511.15218)); "EEG decoding driven by shared semantic information for perception and imagination" ([Biomedical Signal Processing and Control 2026](https://www.sciencedirect.com/science/article/abs/pii/S1746809426001400)). I did not read their figures.

**EEG, perception (for comparison) [PERCEPTION]**
- On THINGS-EEG2 (research grade, 64 channels), the ATM model with guided diffusion (NeurIPS 2024) reaches **19.7 % top-1 and 51.5 % top-5 in 200-way zero-shot retrieval** — [Li et al., NeurIPS 2024 / arXiv 2403.07721](https://arxiv.org/html/2403.07721v6).
- ENIGMA (2026) reaches 27.60 % retrieval top-1 on THINGS-EEG2. Its reconstructions score a CLIP score of 78.90 % and 83.06 % human 2-way identification. A new subject can be fine-tuned with about 15 minutes of data — [Alljoined-1.6M, arXiv 2508.18571](https://arxiv.org/html/2508.18571); [ENIGMA, arXiv 2602.10361](https://arxiv.org/html/2602.10361v1).
- Within 500 ms of stimulus onset, accuracy on a 40-class EEG visual dataset reaches a ceiling of about 30 % and then stops improving. One integrated method reports 33.17 % against an earlier state of the art of 17.6 % — [Decoding Natural Images from EEG for Object Recognition, arXiv 2308.13234](https://arxiv.org/html/2308.13234v3) (snippet).

**fMRI, imagery vs perception**
- NSD-Imagery (2025) adds mental-imagery fMRI runs to the Natural Scenes Dataset. It has 18 imagery stimuli: 6 simple shapes, 5 complex scenes and 6 word-cued concepts. Each stimulus has 8 vision and 16 imagery repetitions, and imagery lasts 3 s per trial — [NSD-Imagery, arXiv 2506.06898](https://arxiv.org/html/2506.06898v1).
- Human-judged 2-way identification on NSD-Imagery, vision → imagery: **MindEye1 84.29 % → 73.00 %** (−11.3 pp); **Brain Diffuser 80.13 % → 73.95 %** (−6.2 pp); **iCNN (Shen et al. 2019 method) 74.52 % → 66.15 %** (−8.4 pp); **MindEye2 83.05 % → 56.96 %** (−26.1 pp, "near-chance"). All methods also drop on pixel correlation, SSIM and CLIP metrics, and early visual cortex drops more than higher areas. Vision and imagery reconstruction quality per stimulus correlate only weakly (r = 0.13–0.22) — [NSD-Imagery, arXiv 2506.06898](https://arxiv.org/html/2506.06898v1).
- (older, 2019) Shen et al.'s deep image reconstruction (iCNN) is the baseline for fMRI mental-image reconstruction — [NSD-Imagery, arXiv 2506.06898](https://arxiv.org/html/2506.06898v1).
- Koide-Majima, Nishimoto & Majima (*Neural Networks* vol. 170, 2024) reconstructed imagined images from fMRI. They used DNN features with Bayesian estimation and Langevin dynamics (SGLD) to sample from a posterior over images — [ResearchGate record](https://www.researchgate.net/publication/375533121_Mental_image_reconstruction_from_human_brain_activity_Neural_decoding_of_mental_imagery_via_deep_neural_network-based_Bayesian_estimation); [code](https://github.com/nkmjm/mental_img_recon). An independent 2025 reanalysis using the released code "identified multiple methodological concerns" that question the conclusions — [arXiv 2511.07960](https://arxiv.org/html/2511.07960).
- Shen-lab critique "Spurious reconstruction from brain activity" (2024) warns that reconstruction pipelines can produce plausible images driven by the prior or dataset structure rather than by brain information — [arXiv 2405.10078](https://arxiv.org/pdf/2405.10078) (title/listing only; not fetched).

### Inferences
- Working figures for a prototype: EEG imagery content decoding is roughly **2–4-class classification at 60–76 %** within a category, per user, with calibration data. For comparison, EEG *perception* retrieval is about 20–28 % top-1 at 200-way. Imagery responses are not time-locked to a stimulus and have lower SNR, so imagery on an open image set would score far lower. I found no peer-reviewed EEG imagery 200-way retrieval number.
- fMRI imagery loses a further 6–26 pp relative to fMRI perception, and the strongest perception model generalises worst. Decoders trained only on perception EEG (THINGS-EEG2 / Alljoined) should therefore not be expected to transfer to imagery without imagery training data.
- "Imagination mode" should be framed as **steering a generator with a small vocabulary of decoded categories and attributes**, not as reconstruction.

### Gaps
- No verified EEG paper reporting zero-shot retrieval or reconstruction of *imagined* natural images with standard metrics (2-way identification, CLIP) was found.
- I could not retrieve exact chance levels, cross-validation schemes or EOG controls for the 2025 *Scientific Data* imagery dataset, or the content of the 2025 topomap paper.
- I found no quantitative EEG perception→imagery cross-decoding figure (train on perception, test on imagery) in this pass. The 2022 bioRxiv paper pools the two conditions rather than reporting pure transfer.

## Memory signals: what does EEG show about reinstatement during recall, and can specific episodes be reconstructed?

### Takeaway
EEG/MEG reliably shows **encoding-pattern reinstatement starting about 500 ms after a retrieval cue**, with conceptual/category ("gist") information reinstated *before* perceptual detail. That order is the reverse of perception. What can be decoded is coarse (category, perceptual-vs-semantic dimension, old/new and recollection state). I found no evidence that a specific episodic memory can be reconstructed from scalp EEG.

### Cited Findings
- (older, 2019) Linde-Domingo et al., *Nature Communications* 10:179. In 3 experiments using reaction times and EEG time-series decoding, low-level perceptual features were decoded **earlier** than conceptual features during perception. During associative recall the order **reversed**: conceptual information was reconstructed first and perceptual details later — [Nat Commun 2019, Birmingham repository PDF](https://pure-oai.bham.ac.uk/ws/files/55251733/Linde_Domingo_et_al_Evidence_that_neural_information_flow_is_reversed_Nature_Communications.pdf); [bioRxiv preprint](https://www.biorxiv.org/content/10.1101/300913.full.pdf) (exact ms latencies not retrieved because of a 429 error).
- Follow-up: "Feature-specific reaction times reveal a semanticisation of memories over time and with repeated remembering" — memories lose perceptual detail relative to conceptual content over time and with repeated retrieval — [Nat Commun 2021](https://www.nature.com/articles/s41467-021-23288-5) (title/listing).
- "Reconstructing Spatiotemporal Trajectories of Visual Object Memories in the Human Brain" (2024) continues this perceptual-vs-conceptual reinstatement-timing line — [PMC11439564](https://pmc.ncbi.nlm.nih.gov/articles/PMC11439564/) (listing only).
- (older, 2020) "Tracking Your Mind's Eye during Recollection", *J Cogn Neurosci* 32(1):50. EEG from **n = 11** participants recalling short audiovisual clips seen **3 weeks, 1 day and a few hours** earlier, cued by snapshots in a Remember/Know/New paradigm. L2-regularised logistic regression with temporal generalisation (−200 to 800 ms) found **sustained patterns at >500 ms** after the cue. These faded over the retention interval. Encoding patterns were reinstated even at 3 weeks and were associated with recollection — [JoCN 2020](https://direct.mit.edu/jocn/article/32/1/50/95404/Tracking-Your-Mind-s-Eye-during-Recollection); [PubMed 31560269](https://pubmed.ncbi.nlm.nih.gov/31560269) (abstract/snippet).
- Hippocampal–neocortical dynamics **500–1500 ms** after a reminder reinstate mnemonic patterns. EEG neural reinstatement emerges around **500 ms**, together with the left-parietal ERP old/new recollection effect — [EEG reinstatement, cue overlap & goals, PMC12256160](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12256160/); [bioRxiv 2022.10.21.513221](https://www.biorxiv.org/content/10.1101/2022.10.21.513221.full.pdf) (snippet).
- 2025 preprint: theta-mediated **conceptual reinstatement in vmPFC precedes perceptual reinstatement in ventral visual cortex** during recall — [bioRxiv 2025.12.17.695049](https://www.biorxiv.org/content/10.64898/2025.12.17.695049.full.pdf) (snippet; preprint, not peer reviewed).
- (older, 2019) Review: "A Neural Chronometry of Memory Recall" (*Trends in Cognitive Sciences*) summarises time-resolved reinstatement evidence — [TICS 2019](https://www.cell.com/trends/cognitive-sciences/fulltext/S1364-6613(19)30235-9).
- Neurofeedback based on decoded context reinstatement has been used to link reinstatement to retrieval success (closed loop with fMRI, not images) — [PMC7034791](https://pmc.ncbi.nlm.nih.gov/articles/PMC7034791/) (title/listing).
- "Neural Memory Decoding with EEG Data and Representation Learning" (Bruns, 2023) attempts to decode which memory is being recalled from EEG with learned representations — [arXiv 2307.13181](https://arxiv.org/pdf/2307.13181) (listing; figures not retrieved).

### Inferences
- For "memory mode", a feasible design is cue-locked recall: show a cue and decode in a **~500–1500 ms window**, expecting **category/semantic information first**. The decoded semantic label (plus anything the user typed or the cue itself) then conditions the generator.
- Because the memory signal is conceptual-first and loses perceptual detail over time, decoded memory will rarely constrain layout or colour. Most visual detail in the output will come from the generator prior and the cue, and the UI should say so.
- Decoders need **per-user encoding sessions** (encode → recall) to learn the patterns that later get reinstated. Cross-subject memory decoding is not established.

### Gaps
- I did not retrieve exact peak latencies and accuracies for Linde-Domingo 2019, or decoding accuracy and chance level for the JoCN 2020 study.
- I found no peer-reviewed study reconstructing an image of a specific recalled episode from scalp EEG. This is recorded as absence of evidence from this search, not as proof that none exists.

## Real time: what online or closed-loop EEG visual decoding exists, and what did Meta show with MEG?

### Takeaway
Meta's 2023 MEG work (ICLR 2024) decoded **viewed** images continuously from MEG and framed it as a step toward real-time decoding. It was perception only, used 4 subjects and expensive MEG, and was evaluated offline. The cited articles do not show a comparable real-time, generative, image-level EEG demonstration. EEG classifiers themselves run in milliseconds. The bottlenecks are signal accumulation windows (~0.5–1.5 s), the need for repetitions, and generator latency.

### Cited Findings
- Benchetrit, Banville & King (FAIR Meta), "Brain decoding: toward real-time reconstruction of visual perception", arXiv 2310.19812, **ICLR 2024**. MEG sampling about **5,000 Hz** vs fMRI about **0.5 Hz**. The decoder gives a **7× improvement in image retrieval over classic linear decoders**. Late responses are best decoded with **DINOv2** features. 7T fMRI recovers better low-level features than MEG — [arXiv 2310.19812](https://arxiv.org/abs/2310.19812).
- Data: about 63,000 MEG trials from **4 participants** over 12 sessions, **22,448 unique images** plus 200 repeated images (THINGS-MEG) — [Meta AI blog](https://ai.meta.com/blog/brain-ai-image-decoding-meg-magnetoencephalography/); [AI Business](https://aibusiness.com/nlp/meta-meg-using-ai-to-generate-images-from-the-human-brain) (aggregator). Secondary press gives "up to 70 %" top retrieval accuracy in the best cases — [AI Business](https://aibusiness.com/nlp/meta-meg-using-ai-to-generate-images-from-the-human-brain); [VentureBeat](https://venturebeat.com/ai/meta-recreates-mental-imagery-from-brain-scans-using-ai). Treat the 70 % as a press figure; the exact metric (top-5 on which subset) was not verified against the paper.
- A ~**250 ms** delay is cited as the real-time BMI paradigm implied by the MEG work — [search summary of arXiv 2310.19812](https://arxiv.org/pdf/2310.19812) (snippet; not confirmed in the paper text).
- Meta's follow-up "Scaling laws for decoding images from brain activity" (2025) — [arXiv 2501.15322](https://arxiv.org/pdf/2501.15322) (listing only).
- EEG classifier compute is not the bottleneck. CSOANet2026 runs in **3.99 ± 0.60 ms (CPU) / 0.81 ± 0.16 ms (GPU)** per trial, "well below the 10-ms threshold for closed-loop neurofeedback" — [T&F 2026](https://www.tandfonline.com/doi/full/10.1080/21681163.2026.2684109?af=R) (abstract/snippet).
- (older, 2019/2021) An open-source closed-loop EEG neurofeedback framework decoded **attentional states** in real time using a portable **32-channel dry-electrode** system. Classifiers were updated continuously from recent data without a prior calibration session, with a **mean decoding error rate of 34.3 %**. This is attention state, not image content — [bioRxiv 834713](https://www.biorxiv.org/content/10.1101/834713v1); [Neural Computation 33(4):967, 2021](https://direct.mit.edu/neco/article/33/4/967/97477/Real-Time-Decoding-of-Attentional-States-Using-Closed-Loop-EEG-Neurofeedback).
- (older, 2022) EEG-LLAMAS: an open-source, low-latency EEG-fMRI neurofeedback platform — [bioRxiv 2022.11.21.515651](https://www.biorxiv.org/content/10.1101/2022.11.21.515651v1.full).
- Perception decoding from EEG plateaus within **~500 ms** of stimulus onset (about 30 % on 40 classes in that study), which sets a lower bound on the window per decode — [arXiv 2308.13234](https://arxiv.org/html/2308.13234v3) (snippet).
- Reinstatement during recall appears **>500 ms** after the cue and lasts until about 1500 ms — [JoCN 2020](https://direct.mit.edu/jocn/article/32/1/50/95404/Tracking-Your-Mind-s-Eye-during-Recollection); [PMC12256160](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12256160/).

### Inferences
- Realistic update rates for a prototype: **one decode per trial, about 0.5–1 s after a stimulus** in perception mode and **about 1–2 s after a cue** in memory mode. Imagery epochs are self-paced and typically several seconds long (NSD-Imagery uses 3 s), so **about 0.2–0.5 decodes per second** in imagery mode. Averaging repetitions to raise SNR lowers these rates further.
- The end-to-end loop is dominated by the generator. Local diffusion or video models take seconds per frame or clip. The project's own gateway figures (T4 endpoint about 5 s warm, 30–60 s cold) mean a "closed loop" will run at **several seconds per image**, not at EEG time scales.
- Nothing found matches Meta's MEG result with EEG in a live demo. The prototype's "real-time" claim should be "online decoding with generation lag", not real-time reconstruction.

### Gaps
- I found no peer-reviewed paper reporting a **live, closed-loop EEG → generative image** system with measured end-to-end latency and accuracy. Search results returned attention/state neurofeedback instead.
- I could not confirm the exact Meta retrieval metric (top-5 accuracy values per latent model) from the paper body.

## Hardware: consumer vs research EEG, BrainFlow/LSL support, and visual-decoding results per class

### Takeaway
Visual decoding benchmarks come almost entirely from **32–128-channel research systems** (THINGS-EEG2, 64 channels). A 32-channel consumer-grade Emotiv Flex 2 still decodes semantics but drops from **27.6 % to 6.0 % top-1 retrieval**. With 8 channels, 20-class perception accuracy is about 34 %. The 4-channel Muse sensors sit on the forehead and behind the ears, nowhere near the occipital cortex. BrainFlow supports Muse, OpenBCI, Unicorn, Neurosity and ANT Neuro, but **not Emotiv**.

### Cited Findings
**Results per hardware class [PERCEPTION]**
- **Research grade (64 channels, THINGS-EEG2):** ENIGMA **27.60 % top-1** retrieval, CLIP score **78.90 %**, human identification **83.06 %** — [Alljoined-1.6M, arXiv 2508.18571](https://arxiv.org/html/2508.18571). ATM: **19.7 % top-1 / 51.5 % top-5, 200-way zero-shot** — [arXiv 2403.07721](https://arxiv.org/html/2403.07721v6).
- (2024) Alljoined1: 8 participants each viewing 10,000 natural images, **46,080 epochs**, recorded with a **64-channel** headset — [arXiv 2404.05553](https://arxiv.org/html/2404.05553v1).
- **Consumer grade, 32 channels (Emotiv Flex 2, 256 Hz, about $2,200, said to be 27× cheaper than ~$60k research systems, Bluetooth 5.2):** Alljoined-1.6M has 20 participants, **1.61 million trials**, 16,740 unique images and about 8 h per person. ENIGMA scores **top-1 6.00 %** (vs 27.60 %), CLIP score **62.91 %** (vs 78.90 %) and human identification **65.43 %** (vs 83.06 %). Pairwise meta-category decoding stays robustly above chance, performance scales log-linearly with data volume, and SNR is lower — [Xu et al., arXiv 2508.18571, Aug 2025](https://arxiv.org/html/2508.18571).
- **Low density, 8 channels (portable):** **34.4 % accuracy on 20 image classes** on held-out recordings. Diffusion-based reconstruction from these data reached a 1000-trial **50-class top-1 accuracy of 35.3 %** — ["Image classification and reconstruction from low-density EEG", *Scientific Reports* 2024](https://www.nature.com/articles/s41598-024-66228-1); [PMC11252274](https://pmc.ncbi.nlm.nih.gov/articles/PMC11252274/) (snippet; device model not retrieved).
- **Imagery hardware:** the 2025 imagery dataset used **32 channels at 1000 Hz** (lab system; make not retrieved) — [Scientific Data 2025](https://www.nature.com/articles/s41597-025-06512-5).
- **Dry 32-channel** systems are usable for real-time state decoding (attention neurofeedback) — [Neural Computation 2021](https://direct.mit.edu/neco/article/33/4/967/97477/Real-Time-Decoding-of-Attentional-States-Using-Closed-Loop-EEG-Neurofeedback).

**BrainFlow support and specifications (from BrainFlow's supported-boards page)**
- **Muse 2 / Muse S / Muse 2016:** 4 EEG channels, 256 Hz — [BrainFlow supported boards](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html).
- **OpenBCI Cyton:** 8 channels, 250 Hz. **Cyton + Daisy:** 16 channels, **125 Hz** (the per-channel rate halves when Daisy is added). **Ganglion:** 4 channels, 200 Hz — [BrainFlow supported boards](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html).
- **g.tec Unicorn, Neurosity Crown/Notion, BrainBit, Enophone, ANT Neuro (EE-410, EE-411, …):** supported, but my fetch of that page did not return their channel counts or rates — [BrainFlow supported boards](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html).
- **Emotiv:** **not listed** as a BrainFlow board — [BrainFlow supported boards](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html).

### Inferences
- Going from a 64-channel research system to a 32-channel consumer one cost **~78 % of top-1 retrieval** (27.6 → 6.0 %) even with 1.6 M training trials. Muse and Ganglion (4 channels, no occipital coverage on the Muse) should be treated as unsuitable for image-content decoding. Their use would be state signals (attention/relaxation, blinks), which are confounded by artifacts.
- Minimum credible prototype hardware for visual decoding: **OpenBCI Cyton (+Daisy) with occipital/parietal montage**, g.tec Unicorn or similar 8-channel units at 250 Hz, used with per-user calibration and closed-set categories. Use 32–64-channel lab systems through LSL for anything approaching published retrieval numbers.
- Emotiv devices need Emotiv's own SDK/LSL bridge rather than BrainFlow. That claim is from general knowledge and is not verified here (see Gaps).

### Gaps
- I did not retrieve manufacturer spec pages for: Emotiv EPOC X / Insight (channels, 128/256 Hz modes, licence needed for raw data), Neurosity Crown (channel positions, rate), g.tec Unicorn (8 channels, 250 Hz, 24-bit — unverified here), Muse electrode positions, BrainProducts actiCHamp/LiveAmp or BioSemi ActiveTwo (channel counts, up to kHz rates), or noise-floor figures for any device.
- I did not fetch the LSL (Lab Streaming Layer) supported-device list, so LSL support per device is unverified here. BrainFlow can stream to LSL, but that was not confirmed from documentation in this pass.
- A snippet claimed semantic decoding drops "from 89 % to 38 % on 50-way tasks" when reducing from 128 to 24 channels. I could not tie it to a specific paper with confidence, so it is excluded from the findings.

## Scientific limits: SNR, spatial resolution, artifacts, and "semantic category plus generative prior" vs true reconstruction

### Takeaway
Scalp EEG decodes **high-level semantics** reasonably for perception and weakly for imagery and recall. Spatial detail (layout, low-level features) is poorly recovered: even MEG trails 7T fMRI on low-level features, and fMRI itself loses early-visual detail during imagery. Most visual detail in current EEG "reconstructions" comes from the diffusion prior. Reviewers and reanalyses warn about spurious, prior-driven reconstructions.

### Cited Findings
- MEG recovers high-level features (best with DINOv2), while **7T fMRI recovers better low-level features** — [arXiv 2310.19812](https://arxiv.org/abs/2310.19812). EEG has lower spatial resolution than MEG (no direct figure retrieved; see Gaps).
- During imagery even fMRI reconstructions **drop more in early visual cortex than higher areas**, "reflecting reduced spatial resolution during imagery" — [NSD-Imagery](https://arxiv.org/html/2506.06898v1).
- Consumer EEG has "significantly lower signal-to-noise ratios" but still supports semantic decoding — [Alljoined-1.6M](https://arxiv.org/html/2508.18571); [ENIGMA](https://arxiv.org/html/2602.10361v1).
- "Beyond Reconstruction: What EEG-to-Video Decoding Actually Recovers" (2025) examines what EEG-to-video systems recover beyond semantics — [arXiv 2505.21385](https://arxiv.org/pdf/2505.21385) (title/listing; findings not fetched).
- Reconstructions can be driven by priors and dataset structure: "Spurious reconstruction from brain activity" — [arXiv 2405.10078](https://arxiv.org/pdf/2405.10078); a reanalysis of the Koide-Majima 2024 fMRI imagery paper raised methodological concerns — [arXiv 2511.07960](https://arxiv.org/html/2511.07960).
- Eye-movement confounds are documented in EEG visual decoding: an "eccentricity confound" in EEG-based visual attention decoding from gaze-fixated neural tracking of motion in natural videos — [arXiv 2604.15223](https://arxiv.org/pdf/2604.15223) (title/listing).
- Memory signals are conceptual-first, with perceptual detail reinstated later and degrading over time — [Linde-Domingo 2019](https://pure-oai.bham.ac.uk/ws/files/55251733/Linde_Domingo_et_al_Evidence_that_neural_information_flow_is_reversed_Nature_Communications.pdf); [Nat Commun 2021](https://www.nature.com/articles/s41467-021-23288-5).

### Inferences
- The honest product description is **"semantic category (and a few attributes) decoded from EEG, then rendered by a generative model"**. Any output image should be presented as a *suggestion conditioned on decoded semantics*, with the decoded label and confidence shown next to it.
- Controls the prototype should implement: EOG/eye-tracking or ICA artifact rejection; fixation instructions; **shuffled-label and "no-EEG" baselines**, i.e. generate from the cue/prior alone and compare; held-out-session testing rather than within-block splits.
- Imagery and recall paradigms invite eye movements (people look toward imagined locations) and muscle tension. On low-channel frontal devices such as the Muse these artifacts can dominate any "decoded" signal.

### Gaps
- I did not retrieve quantitative figures on EEG spatial resolution (for example cm-scale localisation error) or SNR per trial versus averaged ERPs.
- I did not retrieve the known critique of block-design confounds in early EEG image datasets (the Spampinato 40-class dataset, Li et al. 2020, TPAMI). It is excluded from the findings because it was not verified in this session.
- I found no systematic review dedicated to EEG visual imagery decoding from 2023–2026. A Taylor & Francis *Brain-Computer Interfaces* review, "Feasibility of decoding visual information from EEG" (2023), exists — [doi 10.1080/2326263X.2023.2287719](https://www.tandfonline.com/doi/full/10.1080/2326263X.2023.2287719) — but returned 403, so its contents are not summarised.
