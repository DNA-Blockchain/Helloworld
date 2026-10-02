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

`python deploy/hf_publish.py cards` updates only the model and dataset cards (deploy/huggingface/).

Versions (model_versions.py has the whole flow):
  candidate --version 1.1.0 --release v0.10.0   upload a new GGUF to the "candidates" branch (Colab or PC)
  record 1.1.0                                  add a candidate's entry to deploy/huggingface/model-versions.json
  promote --release v0.10.0                     release the versions that ship with that tag (the GitHub
                                                release workflow runs this with its HF_TOKEN secret)
  versions                                      every version, and whether it's released

Log in first with `hf auth login` (your token is typed there, on this PC, never into a chat).

The model is a fine-tune of Meta's Llama 3.2 3B Instruct, so it's published under the Llama 3.2
Community License: its name starts with "Llama", and it says "Built with Llama".
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import model_versions as mv  # noqa: E402
GGUF = ROOT / "ollama" / "nos-lora" / "nos-lora.Q4_K_M.gguf"
MODEL_REPO = "Llama-3.2-3B-RabbitSoftware-GGUF"
SPACE_REPO = "rabbitsoftware-gateway"
DATASET_REPO = "rabbitsoftware-training"
CARDS = ROOT / "deploy" / "huggingface"          # the cards are versioned here, with the code they describe
MODEL_CARD = CARDS / "model-card.md"
DATASET_CARD = CARDS / "dataset-card.md"


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
    client.upload_file(path_or_fileobj=str(MODEL_CARD), path_in_repo="README.md", repo_id=repo)
    client.upload_file(path_or_fileobj=str(GGUF), path_in_repo=GGUF.name, repo_id=repo)
    print(f"Uploaded: https://huggingface.co/{repo}\nNext: python deploy/hf_publish.py endpoint")
    return 0


def publish_cards(ask=None) -> int:
    """Update only the model and dataset cards (README.md of each repo) from deploy/huggingface/."""
    client, user = api()
    targets = [(f"{user}/{MODEL_REPO}", "model", MODEL_CARD), (f"{user}/{DATASET_REPO}", "dataset", DATASET_CARD)]
    if not (ask or confirm)("Replace the README of " + " and ".join(repo for repo, _, _ in targets)
                            + " with the cards in deploy/huggingface/?"):
        return 1
    for repo, kind, card in targets:
        client.upload_file(path_or_fileobj=str(card), path_in_repo="README.md", repo_id=repo, repo_type=kind,
                           commit_message="Update the card from deploy/huggingface/")
        print(f"Updated: https://huggingface.co/{'datasets/' if kind == 'dataset' else ''}{repo}")
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


def _git_commit() -> str:
    import subprocess

    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit("Run this from a git clone of the repository (the version records the commit it was built from).")
    return done.stdout.strip()


def _evaluation(path: str | None) -> dict:
    """passed/cases per task from a local_ai_tuning run report, or {} when none is given."""
    if not path:
        return {}
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    scores = {f"{r['task']} ({r['model']})": f"{r['passed']}/{r['cases']}" for r in report.get("results", [])}
    return {"suite": "python local_ai_tuning.py run", "run": report.get("created_at", ""), **scores}


def publish_candidate(args, ask=None) -> int:
    gguf = Path(args.gguf)
    if not gguf.is_file():
        sys.exit(f"The model file isn't here: {gguf}")
    client, user = api()
    repo = f"{user}/{mv.load()['repo']}"
    manifest = mv.load()
    training = {"method": args.method, "examples": args.examples, "where": args.where}
    if not (ask or confirm)(f"Upload {gguf.name} ({gguf.stat().st_size / 1e9:.1f} GB) as candidate model "
                            f"{args.version} for {args.release} to the '{mv.CANDIDATES}' branch of the PRIVATE repo "
                            f"{repo}? (free)"):
        return 1
    updated, new = mv.add_candidate(client, repo, manifest, gguf, args.version, args.release, _git_commit(),
                                    training, _evaluation(args.evaluation), args.base_model)
    mv.save(updated)
    print(f"Candidate {args.version} uploaded (HF commit {new['hf_revision'][:12]}, SHA-256 {new['sha256'][:12]}...).\n"
          f"On your PC: python deploy/hf_publish.py record {args.version}, then commit "
          f"deploy/huggingface/model-versions.json in a PR. The {args.release} release then publishes it.")
    return 0


def record_candidate(version: str) -> int:
    from huggingface_hub import hf_hub_download

    client, user = api()
    manifest = mv.load()
    if any(v["version"] == version for v in manifest["versions"]):
        print(f"{version} is already in the manifest.")
        return 0
    mv.save(mv.fetch_candidate(client, f"{user}/{manifest['repo']}", manifest, version, hf_hub_download))
    print(f"Added {version} to deploy/huggingface/model-versions.json. Commit it in a PR.")
    return 0


def promote_release(release: str) -> int:
    manifest = mv.load()
    problems = mv.validate(manifest)
    if problems:
        sys.exit("The manifest is invalid: " + "; ".join(problems))
    if not any(v.get("release") == release for v in manifest["versions"]):
        print(f"No model version ships with {release}; nothing to publish.")
        return 0                         # so a release without a model needs no Hugging Face token
    client, user = api()
    mv.promote(client, f"{user}/{manifest['repo']}", manifest, release)
    return 0


def release_notes(release: str) -> int:
    """Markdown lines for the model versions a release ships (nothing when it ships none). No login needed."""
    manifest = mv.load()
    for v in manifest["versions"]:
        if v.get("release") == release:
            print(f"- **Model {v['version']}** (`{manifest['file']}`, SHA-256 `{v['sha256']}`, built from "
                  f"{v['git_commit'][:7]}), tagged `{mv.tag_for(v['version'])}` on Hugging Face. "
                  f"Install it: `python rabbit.py model install --version {v['version']}`")
    return 0


def list_versions() -> int:
    client, user = api()
    manifest = mv.load()
    tags = mv.released_tags(client, f"{user}/{manifest['repo']}")
    for v in manifest["versions"]:
        state = "released" if mv.tag_for(v["version"]) in tags else f"candidate (ships with {v['release']})"
        print(f"{v['version']:<8} {state:<34} sha256 {v['sha256'][:12]}  git {v['git_commit'][:7]}  "
              f"{v['size'] / 1e9:.2f} GB")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    sub = p.add_subparsers(dest="step", required=True)
    sub.add_parser("model", help="upload the model to a private repo (free)")
    sub.add_parser("cards", help="update the model and dataset cards from deploy/huggingface/ (free)")
    sub.add_parser("endpoint", help="print the settings for creating the paid endpoint")
    g = sub.add_parser("gateway", help="create the public gateway Space (free)")
    g.add_argument("--endpoint-url", required=True)
    c = sub.add_parser("candidate", help="upload a new model version to the candidates branch (free)")
    c.add_argument("--version", required=True, help="the model's version, e.g. 1.1.0")
    c.add_argument("--release", required=True, help="the RabbitSoftware release that ships it, e.g. v0.10.0")
    c.add_argument("--gguf", default=str(GGUF), help="the model file (default ollama/nos-lora/nos-lora.Q4_K_M.gguf)")
    c.add_argument("--examples", type=int, required=True, help="how many training examples were kept")
    c.add_argument("--method", default="LoRA on Llama-3.2-3B-Instruct from filtered teacher answers, merged, GGUF Q4_K_M")
    c.add_argument("--where", default="Google Colab, colab/local_ai_lora_colab.ipynb")
    c.add_argument("--base-model", default="meta-llama/Llama-3.2-3B-Instruct")
    c.add_argument("--evaluation", help="a local_ai_tuning run report (JSON) to record its scores")
    r = sub.add_parser("record", help="add a candidate's entry (saved on Hugging Face) to the manifest")
    r.add_argument("version")
    pr = sub.add_parser("promote", help="release the versions that ship with a RabbitSoftware release")
    pr.add_argument("--release", required=True)
    sub.add_parser("versions", help="every model version and whether it's released")
    sub.add_parser("notes", help="release-note lines for the versions a release ships").add_argument("--release", required=True)
    args = p.parse_args(argv)
    if args.step == "candidate":
        return publish_candidate(args)
    if args.step == "record":
        return record_candidate(args.version)
    if args.step == "promote":
        return promote_release(args.release)
    if args.step == "versions":
        return list_versions()
    if args.step == "notes":
        return release_notes(args.release)
    if args.step == "model":
        return publish_model()
    if args.step == "cards":
        return publish_cards()
    if args.step == "endpoint":
        return endpoint_steps()
    return publish_gateway(args.endpoint_url)


if __name__ == "__main__":
    sys.exit(main())
