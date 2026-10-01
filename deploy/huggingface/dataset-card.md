---
license: other
language: [en]
pretty_name: RabbitSoftware.inc shared answers
task_categories: [text-generation, question-answering]
tags: [rabbitsoftware, rlhf, feedback]
configs:
  - config_name: default
    data_files: "data/*.jsonl"
---

# RabbitSoftware.inc shared answers (private)

Questions and answers that RabbitSoftware.inc users **chose to share** to help train the next version of
[Llama-3.2-3B-RabbitSoftware](https://huggingface.co/Therealsickonechase-bit/Llama-3.2-3B-RabbitSoftware-GGUF).

## How an answer gets here

1. Someone asks RabbitSoftware.inc a question, and the model answers from public research records.
2. They choose "Share this answer for training" and say yes. Sharing is never automatic.
3. Before anything is sent, the question and answer are checked for personal information: emails, phone and ID numbers, dates of birth, addresses and long DNA sequences. If any is found, the answer is not shared.
4. The answer is stored by the RabbitSoftware sync service (Cloudflare R2) **without any name, account or device**.
5. A daily export copies new answers here, one JSON Lines file per day, under `data/`.

## Fields

| Field | Meaning |
|---|---|
| `question` | what was asked, up to 2,000 characters |
| `answer` | the model's answer, up to 4,000 characters |
| `sources` | the public record links the answer was based on, at most 10 |
| `rating` | 1 helpful, -1 wrong, 0 not rated |
| `model` | which model answered (`rabbitsoftware` = the hosted model, `local` = the user's own PC) |
| `shared_at` | when it was shared (UTC) |

## Use

The dataset is private: it holds only the owner's training material for future LoRA rounds. Before training, check answers against their sources. A shared answer isn't necessarily correct, which is what the `rating` field and review are for.
