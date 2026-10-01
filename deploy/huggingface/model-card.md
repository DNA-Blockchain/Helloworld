---
license: llama3.2
base_model: meta-llama/Llama-3.2-3B-Instruct
language: [en]
pipeline_tag: text-generation
tags: [gguf, llama.cpp, lora, rabbitsoftware, biomedical-research, retrieval-augmented-generation]
---

# Llama-3.2-3B-RabbitSoftware (GGUF, Q4_K_M)

The model behind **RabbitSoftware.inc**, the assistant of the RabbitSoftware OS
([DNA-Blockchain/Helloworld](https://github.com/DNA-Blockchain/Helloworld)). The OS runs a network of
research nodes that collect public biomedical records into a local corpus and record them on a signed,
replicated chain. This model is the reasoning layer on top of that corpus. It produces cited technical
answers from the retrieved records, and it reports on the OS's own chain, swarm and integrity results.

## Model

| | |
|---|---|
| Base model | Meta Llama 3.2 3B Instruct |
| Fine-tuning | LoRA, round 2, trained by distillation: Qwen2.5-7B-Instruct generated candidate explanations, which were filtered by automatic fact checks before training the 3B model. |
| Export | LoRA merged into the base weights and quantized with llama.cpp to GGUF Q4_K_M (2.0 GB). |
| File | `nos-lora.Q4_K_M.gguf`, SHA-256 `8aa05e2879f4e1e37395a238497726c2454fc0dc66661f989996e1b0dca473ef` |

## Pipeline it runs in

1. **Ingestion:** research nodes query PubMed, Europe PMC, NIH RePORTER and ClinicalTrials.gov. Records are saved to the local catalog, and each batch is published to the shared research chain as a signed `public_research_records` event.
2. **Retrieval:** a question is matched against the catalog by keyword (catalog score ≥ 3) and by meaning, using `nomic-embed-text` embeddings with cosine ≥ 0.62, or TF-IDF with cosine ≥ 0.12 when no embedding model is installed. Duplicates across sources are merged, and the top 5 records go to the model.
3. **Generation:** the model receives each record's title, source, year and up to 900 characters of abstract. It answers in three sections:
   - **Findings:** the reported figures, quoted exactly;
   - **Methods and evidence:** each cited record's study type and the strength of evidence;
   - **Limitations:** what the records don't establish, and where they disagree.

   Every claim is cited `[n]`. Citations to records that weren't supplied are removed after generation.
4. **Reporting:** the answer is returned with its sources and a retrieval line covering match methods, similarity range and cutoff, sources, years and abstract coverage.

## Serving

- **Server:** a Hugging Face Inference Endpoint (`rabbitsoftware-model`) running the llama.cpp server on one NVIDIA T4. It scales to zero after 15 minutes idle.
- **API:** OpenAI-compatible `POST /v1/chat/completions`, model name `rabbitsoftware`. Answers are capped at 400 tokens.
- **Access:** the endpoint is private. The owner's installation authenticates with its own Hugging Face login. Other installations go through a gateway on Cloudflare Workers, which holds the token and enforces per-user and daily limits.
- **Consent:** RabbitSoftware.inc asks before **every** question it sends to the server. Declining answers with the model on the local machine.
- **Throughput:** about 84 tokens/s when warm; 30–60 s cold start after scale-to-zero.

## Evaluation and limits

- On the project's explanation checks it scores 6 of 8, matching the prompt-engineered `nos-explain` model. Round 2 improved exact preservation of numbers. Summaries remain the weakest task.
- It's a 3B model and **can be wrong even when it cites a record**. Known errors from testing:
  - it reversed the direction of the sickle-cell substitution (the correct direction is glutamic acid → valine at β-globin position 6);
  - it over-read a survey paper as a treatment approval.
- It answers only from the records supplied. When nothing relevant is retrieved, the assistant offers a search instead of answering.
- **Not medical advice.** Every answer in RabbitSoftware.inc says so.

## Data

Training used public research text and synthetic examples, with no personal data. Later rounds may add answers that users explicitly chose to share. These are screened for personal information and carry no name, account or device identifier (see the private dataset `rabbitsoftware-training`).

## License

Built with Llama. Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved. Use must follow the [Llama 3.2 Acceptable Use Policy](https://llama.meta.com/llama3_2/use-policy).
