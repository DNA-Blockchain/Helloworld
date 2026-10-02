---
license: other
language: [en]
pretty_name: RabbitSoftware.inc shared answers
task_categories: [text-generation, question-answering]
tags: [rabbitsoftware, rlhf, feedback]
configs:
  - config_name: default
    data_files: "data/*.parquet"
---

# RabbitSoftware.inc shared answers (private)

Questions and answers that RabbitSoftware.inc users **chose to share** to help train the next version of
the model Llama-3.2-3B-RabbitSoftware (`Llama-3.2-3B-RabbitSoftware-GGUF`, in the same account).

## How an answer gets here

1. **An answer is given.** Someone asks RabbitSoftware.inc a question, and the model answers from public research records.
2. **They choose to share it.** They pick "Share this answer for training" and say yes. Sharing is never automatic.
3. **It's screened on the device.** Before anything is sent, the question and answer are checked for personal information: emails, phone and ID numbers, dates of birth, addresses and long DNA sequences. If any is found, the answer isn't shared.
4. **It's stored with no identity.** The RabbitSoftware sync service stores the answer in its SQL database (Cloudflare D1, table `training_answers`) **without any name, account or device**, with review status `pending`.
5. **The owner reviews it.** The owner can approve or reject answers. Rejected answers are never exported.
6. **It's exported here.** Each export (`python rabbit.py training export`, or daily if turned on) screens every answer again and writes one Parquet file (zstd) to `data/`. The service then records the file, its SHA-256 and the commit, so no answer is exported twice.

## Fields

| Field | Type | Meaning |
|---|---|---|
| `id` | string | the answer's random ID on the sync service |
| `shared_at` | string | when it was shared (ISO 8601, UTC) |
| `question` | string | what was asked, up to 2,000 characters |
| `answer` | string | the model's answer, up to 4,000 characters |
| `sources` | list of strings | the public record links the answer was based on, at most 10 |
| `rating` | int8 | 1 helpful, −1 wrong, 0 not rated |
| `model` | string | which model answered (`rabbitsoftware` = the hosted model, `local` = the user's own PC) |
| `status` | string | review status at export: `pending` or `approved` |

## Use

```python
from datasets import load_dataset
ds = load_dataset("<your-hf-username>/rabbitsoftware-training", split="train")   # needs your HF login
```

Or query it with SQL from DuckDB:

```sql
SELECT status, rating, COUNT(*) FROM 'hf://datasets/<your-hf-username>/rabbitsoftware-training/data/*.parquet' GROUP BY ALL;
```

The dataset is private: it holds only the owner's training material for future LoRA rounds. Before training, check answers against their sources. A shared answer isn't necessarily correct, which is what the `rating`, the review status and the review itself are for.
