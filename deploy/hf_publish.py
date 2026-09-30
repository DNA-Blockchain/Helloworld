"""Publishes RabbitSoftware.inc's model to Hugging Face and puts the public gateway in front of it.

Three steps, each run on its own and each asking before it does anything:

  1. python deploy/hf_publish.py model
        Uploads the merged model (ollama/nos-lora/nos-lora.Q4_K_M.gguf, about 1.9 GB) to a PRIVATE
        model repo on your account. Free.

  2. Create the Inference Endpoint in the Hugging Face website (this is the part that costs money,
     so you choose the hardware and see the price there). `python deploy/hf_publish.py endpoint`
     prints the exact settings.

  3. python deploy/hf_publish.py gateway --endpoint-url https://....endpoints.huggingface.cloud
        Creates the gateway Space (free CPU), gives it the endpoint's address and a token as a secret,
        and prints the address to give RabbitSoftware.inc: rabbit model-server <that address>.

Log in first with `hf auth login` (your token is typed there, on this PC, never into a chat).

The model is a fine-tune of Meta's Llama 3.2 3B Instruct, so it's published under the Llama 3.2
Community License: its name starts with "Llama", and it says "Built with Llama".
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GGUF = ROOT / "ollama" / "nos-lora" / "nos-lora.Q4_K_M.gguf"
MODEL_REPO = "Llama-3.2-3B-RabbitSoftware-GGUF"
SPACE_REPO = "rabbitsoftware-gateway"
MODEL_CARD = """---
license: llama3.2
base_model: meta-llama/Llama-3.2-3B-Instruct
tags: [gguf, llama.cpp, rabbitsoftware]
---

# Llama-3.2-3B-RabbitSoftware (GGUF, Q4_K_M)

The model behind RabbitSoftware.inc: Llama 3.2 3B Instruct with a LoRA trained to explain this
project's research and chain results in plain words, merged and quantized for llama.cpp.

Built with Llama. Llama 3.2 is licensed under the Llama 3.2 Community License,
Copyright © Meta Platforms, Inc. All Rights Reserved.
"""


def confirm(question: str) -> bool:
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def api():
    from huggingface_hub import HfApi
    from huggingface_hub.errors import LocalTokenNotFoundError

    client = HfApi()
    try:
        user = client.whoami()["name"]
    except LocalTokenNotFoundError:
        sys.exit("Log in to Hugging Face first: hf auth login")
    return client, user


def publish_model() -> int:
    if not GGUF.exists():
        sys.exit(f"The model file isn't here: {GGUF}")
    client, user = api()
    repo = f"{user}/{MODEL_REPO}"
    size = GGUF.stat().st_size / 1e9
    if not confirm(f"Upload {GGUF.name} ({size:.1f} GB) to the PRIVATE model repo {repo}? (free)"):
        return 1
    client.create_repo(repo, repo_type="model", private=True, exist_ok=True)
    client.upload_file(path_or_fileobj=MODEL_CARD.encode(), path_in_repo="README.md", repo_id=repo)
    client.upload_file(path_or_fileobj=str(GGUF), path_in_repo=GGUF.name, repo_id=repo)
    print(f"Uploaded: https://huggingface.co/{repo}\nNext: python deploy/hf_publish.py endpoint")
    return 0


def endpoint_steps() -> int:
    client, user = api()
    print(f"""Create the endpoint in the Hugging Face website (you'll see the price before you confirm):

  1. Open https://huggingface.co/{user}/{MODEL_REPO}
  2. Deploy -> Inference Endpoints. Hugging Face detects the GGUF file and offers llama.cpp; keep it.
  3. Hardware: the smallest GPU offered (an NVIDIA T4 or L4, about $0.50-0.80 an hour).
  4. Security level: Protected (only callers with a token get in; the gateway will have one).
  5. Autoscaling: minimum 0 replicas, scale to zero after 15 minutes. It then costs nothing while
     nobody asks; the first question after a quiet spell waits a minute or two while it wakes.
  6. Create it, wait until it says Running, and copy its URL.

Then: python deploy/hf_publish.py gateway --endpoint-url <that URL>""")
    return 0


def publish_gateway(endpoint_url: str) -> int:
    client, user = api()
    space = f"{user}/{SPACE_REPO}"
    if not endpoint_url.startswith("https://"):
        sys.exit("The endpoint URL must start with https://")
    print("The gateway needs a token that can call your endpoint. Make a fine-grained token at\n"
          "https://huggingface.co/settings/tokens with only 'Make calls to Inference Endpoints' allowed.")
    token = os.environ.get("RABBIT_GATEWAY_TOKEN") or getpass.getpass("Paste that token here (hidden): ").strip()
    if not token:
        sys.exit("No token given.")
    if not confirm(f"Create the PUBLIC gateway Space {space} (free CPU) forwarding to {endpoint_url}?"):
        return 1
    client.create_repo(space, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    client.upload_folder(repo_id=space, repo_type="space", folder_path=str(ROOT / "deploy" / "gateway"))
    client.add_space_variable(space, "ENDPOINT_URL", endpoint_url)
    client.add_space_secret(space, "HF_TOKEN", token)
    address = f"https://{user.lower()}-{SPACE_REPO}.hf.space"
    print(f"Gateway: {address} (it takes a few minutes to build the first time).\n"
          f"Point RabbitSoftware.inc at it:  rabbit model-server {address}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    sub = p.add_subparsers(dest="step", required=True)
    sub.add_parser("model", help="upload the model to a private repo (free)")
    sub.add_parser("endpoint", help="print the settings for creating the paid endpoint")
    g = sub.add_parser("gateway", help="create the public gateway Space (free)")
    g.add_argument("--endpoint-url", required=True)
    args = p.parse_args(argv)
    if args.step == "model":
        return publish_model()
    if args.step == "endpoint":
        return endpoint_steps()
    return publish_gateway(args.endpoint_url)


if __name__ == "__main__":
    sys.exit(main())
