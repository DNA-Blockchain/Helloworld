---
license: other
language: [en]
pretty_name: RabbitSoftware project knowledge base
task_categories: [question-answering, text-retrieval]
tags: [rabbitsoftware, research, rag, knowledge-base]
configs:
  - config_name: default
    data_files: "data/knowledge.parquet"
---

# RabbitSoftware project knowledge base (private)

The research reports behind RabbitSoftware's design, from `docs/research/` in
[DNA-Blockchain/Helloworld](https://github.com/DNA-Blockchain/Helloworld), split into sections. RabbitSoftware.inc
answers questions from these sections, passing the matching ones to
the model Llama-3.2-3B-RabbitSoftware (`Llama-3.2-3B-RabbitSoftware-GGUF`, in the same account)
with each question. This copy keeps the knowledge base versioned on Hugging Face, ready for future fine-tuning.

## Contents

The reports summarize public research: peer-reviewed papers, preprints, dataset documentation, statutes and
regulator guidance, each cited by link. **Nothing personal** is included.

| Field | Type | Meaning |
|---|---|---|
| `id` | string | stable section ID: `path#heading-slug`, numbered when a long section is split |
| `path` | string | the report or notes file in the repository |
| `title` | string | the document's title |
| `heading` | string | the section heading |
| `text` | string | the section's text (Markdown) |
| `sha256` | string | SHA-256 of `text` |
| `urls` | list of strings | the sources the section cites |
| `version` | string | the knowledge-base fingerprint this row belongs to |

`manifest.json` holds the version **fingerprint** (a SHA-256 over every section's ID and hash), the files, and
each section's ID and SHA-256, so any copy can be checked against the version it claims to be.

## How it's updated

`python rabbit.py knowledge publish` rebuilds the sections from the reports committed to the repository, which
have been through review, and compares fingerprints. It uploads only when something changed, after asking. The
data, manifest and card go up in one commit. Earlier versions stay in this dataset's commit history.

## Use

```python
from datasets import load_dataset
kb = load_dataset("<your-hf-username>/rabbitsoftware-knowledge", split="train")   # needs your HF login
```

The reports are research summaries, not legal or medical advice. Results from preprints are marked as
unreplicated in the text where that applies.
