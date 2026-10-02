# Model versions: GitHub, Hugging Face and your PC

RabbitSoftware.inc's model is built from code in GitHub, stored on Hugging Face, and run on any PC with
Ollama. Each part has one job:

| | Holds | Where |
|---|---|---|
| **GitHub** | The training code, the checks that filter training answers, the model card, and the **record of every version**: [`deploy/huggingface/model-versions.json`](../../deploy/huggingface/model-versions.json) | this repository |
| **Hugging Face** | The model files: new versions on the `candidates` branch, released versions on `main`, each tagged `model-v<version>` | the private repo `Llama-3.2-3B-RabbitSoftware-GGUF` |
| **Google Colab** | The GPU that trains it (free T4) | [`colab/local_ai_lora_colab.ipynb`](../../colab/local_ai_lora_colab.ipynb) |
| **Your PC** | Ollama, running any version | `rabbitsoftware:<version>` and `rabbitsoftware:latest` |

```
Colab: train → check → merge → GGUF ──candidate──▶ HF "candidates" branch (+ its manifest entry)
PC:    python deploy/hf_publish.py record 1.1.0 ──▶ model-versions.json ──▶ pull request ──▶ master
GitHub release v0.10.0 ──promote──▶ HF main (server-side copy) + tag model-v1.1.0 + SHA-256 check
Any PC: python rabbit.py model install ──▶ download with your HF login ──▶ SHA-256 check ──▶ Ollama
```

## Making a new version

1. **Train in Colab.** Open the notebook, run steps 1–10 (about 2–3 hours on a T4) and read the answers
   in step 6 before training.
2. **Publish it as a candidate** (notebook step 11). Set `VERSION` (for example `1.1.0`, newer than the
   last one) and `RELEASE` (the RabbitSoftware release that will ship it, for example `v0.10.0`). It
   uploads the GGUF to the `candidates` branch with its manifest entry. Nothing on `main` changes, so
   anyone installing the released version is unaffected.
3. **Record it in GitHub**, on your PC: `python deploy/hf_publish.py record 1.1.0`, then commit
   `deploy/huggingface/model-versions.json` in a pull request. Each entry holds:
   - the GGUF's SHA-256 and size;
   - the Hugging Face commit it was uploaded in;
   - the GitHub commit it was built from;
   - the base model, how it was trained, and its scores.
4. **Try it before the release:** `python rabbit.py model install --version 1.1.0 --candidate`.
5. **Release.** Tagging RabbitSoftware `v0.10.0` runs `.github/workflows/release.yml`. After the tests pass, it:
   - copies each version that ships with that tag to `main` on Hugging Face (a copy on their servers, with no 2 GB re-upload);
   - updates the card and tags the commit `model-v1.1.0`;
   - checks the SHA-256 on `main` against the manifest;
   - adds the version to the release notes.

   If any check fails, the GitHub release isn't created.

## Installing on a PC

```powershell
hf auth login                                   # once; your token is typed here, never in chat
python rabbit.py model versions                 # every version, released or candidate, with its scores
python rabbit.py model install                  # the newest released version
python rabbit.py model install --version 1.0.0  # a specific one
ollama run rabbitsoftware
```

`install` first looks for a file on this PC with the right SHA-256 (`ollama/nos-lora/`). Otherwise it
downloads the file from Hugging Face with your login. No SSH key is needed, unlike
`ollama pull huggingface.co/...` for a private repo. A file whose SHA-256 doesn't match the manifest is
never installed. Ollama also needs `llama3.2:3b` (`ollama pull llama3.2:3b`), whose chat template and stop
tokens go with the weights.

**In WSL**, `install` uses Windows' Ollama (`ollama.exe`), the one that holds your models, and gives it Windows
paths. A Linux Ollama inside WSL (for example a snap install) keeps its own, separate model store and its
own server on `127.0.0.1:11434` inside WSL. Run the model with `ollama.exe run rabbitsoftware` there, or
from PowerShell. WSL also has its own Hugging Face login: run `hf auth login` once in WSL.

## One-time setup: the release token

The release workflow needs a Hugging Face token that can write to the model repo. It's stored as a GitHub
secret, which only the workflow can read:

1. Go to https://huggingface.co/settings/tokens and create a **fine-grained** token, with **write** access
   to `Llama-3.2-3B-RabbitSoftware-GGUF` only.
2. In a terminal on your PC, run `gh secret set HF_TOKEN -R DNA-Blockchain/Helloworld` and paste the token
   at its prompt. It isn't shown, and doesn't go into the repository or any chat.

A release that ships no model version doesn't use the token, so releases work before it's set.

## Limits

- **Version 1.0.0 was recorded after the fact.** Its GitHub commit is the last change to the training
  script before the upload, and its scores come from a local run a few hours before the final
  conversion fix (the manifest says so).
- **Training needs a GPU.** GitHub's runners have none, so training stays in Colab (or on any NVIDIA PC
  with the same script); GitHub only records and publishes.
- **The Inference Endpoint doesn't switch automatically.** It keeps serving the revision it was created
  with. To serve a new version, update the endpoint's revision on Hugging Face, where you'll see any cost.
