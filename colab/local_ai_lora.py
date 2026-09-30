"""
Teacher answers -> the project's checks -> a LoRA for the local model.
Used by colab/local_ai_lora_colab.ipynb on a Colab GPU.

1. A larger model (the teacher, default Qwen2.5-7B-Instruct) answers each
   training prompt from `local_ai_tuning.py export`, with the system text
   the Ollama models use plus TEACHER_NOTES aimed at known mistakes.
2. Every answer goes through the checks local_ai_tuning.py scores with.
   Only answers that pass are kept; a failed prompt gets retried with
   sampling. What was kept and what was rejected are both saved.
3. A LoRA is trained on Llama-3.2-3B-Instruct, the model Ollama runs as
   llama3.2:3b, on the kept answers only (loss on the answer, not the
   prompt).
4. Ollama 0.34+ no longer loads separate adapters, so the LoRA is merged
   into the base weights and converted to one Q4_K_M GGUF file: in Colab
   (notebook cell 10), or on a PC without much memory:

     python3 colab/local_ai_lora.py nos-lora.zip      # in WSL; needs hf auth login
"""
from __future__ import annotations

import gc
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import local_ai_tuning as lt  # noqa: E402

TEACHER = "Qwen/Qwen2.5-7B-Instruct"
STUDENT = "meta-llama/Llama-3.2-3B-Instruct"     # = Ollama's llama3.2:3b
TOKEN_LIMITS = {"explain": 220, "summary": 120}  # what swarm_explain / research_summaries ask Ollama for
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def load_rows(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def save_rows(path: str | Path, rows: list[dict]) -> None:
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# Extra instructions for the teacher only, aimed at what the first round's teacher got wrong (it copied
# titles, and described changes as "in the middle" or as altering protein shape). The student trains on
# the plain system text, so it learns the behaviour without needing these words.
TEACHER_NOTES = {
    "explain": "State the position number of every change. Keep each number with the fact it belongs to: "
               "the highest design score is not the score of the windows that cover the difference. Do not "
               "say where in the sequence a change is beyond its position number, and do not describe "
               "molecules binding or the protein's shape, structure or folding.",
    "summary": "Rewrite the title in your own everyday words; do not reuse its phrasing or word order. Keep "
               "gene, drug and trial names exactly as written.",
}


def messages(row: dict, answer: str | None = None, *, teacher: bool = False) -> list[dict]:
    system = row["system"] + ("\n" + TEACHER_NOTES[row["task"]] if teacher else "")
    chat = [{"role": "system", "content": system}, {"role": "user", "content": row["prompt"]}]
    if answer is not None:
        chat.append({"role": "assistant", "content": answer})
    return chat


def load_model(model_id: str, *, four_bit: bool = False):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    gpu = torch.cuda.is_available()
    kwargs = {"dtype": torch.float16 if gpu else torch.float32}
    if gpu:
        kwargs["device_map"] = "auto"
    if four_bit:
        from transformers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                           bnb_4bit_compute_dtype=torch.float16)
    return AutoModelForCausalLM.from_pretrained(model_id, **kwargs), tokenizer


def release_gpu_memory() -> None:
    """Call after dropping the last reference to a model (del model)."""
    import torch

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def test_rows() -> list[dict]:
    """The 8 synthetic explain test cases as prompts. Training never sees these."""
    system = lt.modelfile_system(lt.CUSTOM_MODELS["nos-explain"])
    return [{"id": case_id, "task": "explain", "input": facts, "system": system,
             "prompt": lt.se.PROMPT.format(facts="\n".join(f"- {f}" for f in facts))}
            for case_id, facts in lt.explain_cases()]


def generate(rows: list[dict], model, tokenizer, *, sample: bool = False, batch_size: int = 8,
             teacher: bool = False, log=print) -> list[tuple[str, bool]]:
    """(answer, finished) per row, in row order. finished is False when the answer used up the task's
    token limit, since Ollama would cut it off there too. Each batch holds one task."""
    import torch

    tokenizer.padding_side = "left"
    eos = model.generation_config.eos_token_id
    stops = {tokenizer.eos_token_id, tokenizer.pad_token_id, *(eos if isinstance(eos, list) else [eos])}
    options = {"do_sample": True, "temperature": 0.7, "top_p": 0.9} if sample else {"do_sample": False}
    results: dict[int, tuple[str, bool]] = {}
    done = 0
    for task, limit in TOKEN_LIMITS.items():
        indexes = [i for i, r in enumerate(rows) if r["task"] == task]
        for start in range(0, len(indexes), batch_size):
            batch = indexes[start:start + batch_size]
            texts = [tokenizer.apply_chat_template(messages(rows[i], teacher=teacher), tokenize=False,
                                                   add_generation_prompt=True)
                     for i in batch]
            encoded = tokenizer(texts, return_tensors="pt", padding=True, add_special_tokens=False).to(model.device)
            with torch.no_grad():
                output = model.generate(**encoded, max_new_tokens=limit, pad_token_id=tokenizer.pad_token_id,
                                        **options)
            for i, ids in zip(batch, output[:, encoded["input_ids"].shape[1]:].tolist()):
                used = next((n for n, t in enumerate(ids) if t in stops), len(ids))
                results[i] = (tokenizer.decode(ids[:used], skip_special_tokens=True).strip(), used < len(ids))
            done += len(batch)
            log(f"  answered {done}/{len(rows)}")
    return [results[i] for i in range(len(rows))]


def check(row: dict, answer: str) -> dict:
    """The same scoring local_ai_tuning.py applies to the local model's answers."""
    if row["task"] == "explain":
        return lt.score_explain(row["input"], lt.Replay(answer), "{facts}")
    return lt.score_summary(row["input"], lt.Replay(answer), "{title}")


def build_dataset(rows: list[dict], model, tokenizer, *, retries: int = 2, batch_size: int = 8,
                  log=print) -> tuple[list[dict], list[dict]]:
    """Kept rows carry the checked, cleaned answer; rejected rows carry every failed attempt."""
    kept, attempts = [], {id(r): [] for r in rows}
    pending = rows
    for attempt in range(retries + 1):
        if not pending:
            break
        log(f"attempt {attempt + 1}: {len(pending)} prompts{' (sampled)' if attempt else ''}")
        failed = []
        for row, (answer, finished) in zip(pending, generate(pending, model, tokenizer, sample=attempt > 0, teacher=True,
                                                             batch_size=batch_size, log=log)):
            result = check(row, answer) if finished else {"ok": False, "flags": ["hit the token limit"]}
            if result["ok"]:
                kept.append({**row, "answer": result["text"]})
            else:
                attempts[id(row)].append({"answer": answer, "flags": result["flags"]})
                failed.append(row)
        pending = failed
    rejected = [{**r, "attempts": attempts[id(r)]} for r in pending]
    log(f"kept {len(kept)}, rejected {len(rejected)}")
    return kept, rejected


def encode(row: dict, tokenizer, max_length: int) -> dict:
    """Token ids for prompt + answer, with the prompt masked out of the loss."""
    prompt = tokenizer.apply_chat_template(messages(row), tokenize=False, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages(row, row["answer"]), tokenize=False)
    if not full.startswith(prompt):
        raise ValueError("the chat template renders the prompt differently with an answer attached")
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    ids = tokenizer(full, add_special_tokens=False)["input_ids"][:max_length]
    labels = [-100] * min(len(prompt_ids), len(ids)) + ids[len(prompt_ids):]
    return {"input_ids": ids, "labels": labels}


def train_lora(kept: list[dict], out_dir: str | Path, *, student: str = STUDENT, epochs: int = 2, rank: int = 16,
               learning_rate: float = 2e-4, batch_size: int = 4, grad_accum: int = 2, max_length: int = 1024,
               log=print) -> Path:
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import Trainer, TrainingArguments

    model, tokenizer = load_model(student)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=rank, lora_alpha=2 * rank, lora_dropout=0.05,
                                             target_modules=LORA_TARGETS, task_type="CAUSAL_LM"))
    for p in model.parameters():            # fp16 base, fp32 LoRA weights: needed for fp16 mixed precision
        if p.requires_grad:
            p.data = p.data.float()
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log(f"training {trainable:,} LoRA parameters on {len(kept)} answers")

    examples = [encode(row, tokenizer, max_length) for row in kept]
    pad = tokenizer.pad_token_id

    def collate(batch):
        width = max(len(b["input_ids"]) for b in batch)
        return {
            "input_ids": torch.tensor([b["input_ids"] + [pad] * (width - len(b["input_ids"])) for b in batch]),
            "labels": torch.tensor([b["labels"] + [-100] * (width - len(b["labels"])) for b in batch]),
            "attention_mask": torch.tensor([[1] * len(b["input_ids"]) + [0] * (width - len(b["input_ids"]))
                                            for b in batch]),
        }

    steps = epochs * -(-len(examples) // (batch_size * grad_accum))
    args = TrainingArguments(output_dir=str(Path(out_dir) / "checkpoints"), num_train_epochs=epochs,
                             per_device_train_batch_size=batch_size, gradient_accumulation_steps=grad_accum,
                             learning_rate=learning_rate, lr_scheduler_type="cosine",
                             warmup_steps=max(1, steps // 20),      # 5% (warmup_ratio is gone in transformers 5)
                             fp16=torch.cuda.is_available(), logging_steps=10, save_strategy="no",
                             report_to=[], remove_unused_columns=False)
    Trainer(model=model, args=args, train_dataset=examples, data_collator=collate).train()
    adapter = Path(out_dir) / "adapter"
    model.save_pretrained(adapter)          # adapter_config.json + adapter_model.safetensors
    del model
    release_gpu_memory()
    log(f"adapter saved to {adapter}")
    return adapter


def merge_adapter(adapter: str | Path, out_dir: str | Path, *, student: str = STUDENT) -> Path:
    """The student with the LoRA folded into its weights, saved as a complete fp16 model. Ollama 0.34+
    no longer loads separate LoRA adapters, so this is what gets converted for it."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(student)
    model = AutoModelForCausalLM.from_pretrained(student, dtype=torch.float16)
    model = PeftModel.from_pretrained(model, str(adapter)).merge_and_unload()
    out_dir = Path(out_dir)
    model.save_pretrained(out_dir, safe_serialization=True)
    tokenizer.save_pretrained(out_dir)
    del model
    release_gpu_memory()
    return out_dir


def merge_adapter_streaming(adapter: str | Path, base_dir: str | Path, out_dir: str | Path,
                            max_shard_bytes: int = 1 << 30) -> Path:
    """merge_adapter() one weight matrix at a time, for machines without ~8 GB of free RAM: each base
    tensor gets W + (alpha/r) * B @ A added when the LoRA covers it. Output goes in files of at most
    max_shard_bytes, so memory stays near that size. base_dir is a downloaded copy of the student
    (config, tokenizer, *.safetensors)."""
    import shutil

    from safetensors import safe_open
    from safetensors.torch import load_file, save_file

    adapter, base_dir, out_dir = Path(adapter), Path(base_dir), Path(out_dir)
    config = json.loads((adapter / "adapter_config.json").read_text())
    if config.get("use_rslora") or config.get("use_dora"):
        raise ValueError("streaming merge covers plain LoRA only")
    scale = config["lora_alpha"] / config["r"]
    lora = load_file(adapter / "adapter_model.safetensors")
    pairs = {}                              # base weight name -> (A, B)
    for key in lora:
        if key.endswith(".lora_A.weight"):
            name = key.removeprefix("base_model.model.").replace(".lora_A.weight", ".weight")
            pairs[name] = (lora[key], lora[key.replace("lora_A", "lora_B")])

    out_dir.mkdir(parents=True, exist_ok=True)
    merged, weight_map = set(), {}
    pending, pending_bytes, files = {}, 0, 0

    def flush():
        nonlocal pending, pending_bytes, files
        if pending:
            files += 1
            name = f"part-{files:05d}.safetensors"      # renamed below once the count is known
            save_file(pending, out_dir / name, metadata={"format": "pt"})
            weight_map.update({key: name for key in pending})
            pending, pending_bytes = {}, 0

    for shard in sorted(base_dir.glob("*.safetensors")):
        with safe_open(shard, framework="pt") as f:
            for name in f.keys():
                weight = f.get_tensor(name)
                if name in pairs:
                    a, b = pairs[name]
                    weight = (weight.float() + scale * (b.float() @ a.float())).to(weight.dtype)
                    merged.add(name)
                size = weight.numel() * weight.element_size()
                if pending and pending_bytes + size > max_shard_bytes:
                    flush()
                pending[name] = weight
                pending_bytes += size
    flush()
    # The standard Hugging Face names: llama.cpp's converter only reads files named model*.safetensors,
    # and with any other name it silently writes a model with no weights.
    names = {f"part-{i:05d}.safetensors": f"model-{i:05d}-of-{files:05d}.safetensors" for i in range(1, files + 1)}
    for old, new in names.items():
        (out_dir / old).rename(out_dir / new)
    weight_map = {key: names[name] for key, name in weight_map.items()}
    if merged != set(pairs):
        raise ValueError(f"LoRA weights with no base tensor: {sorted(set(pairs) - merged)[:3]}")
    for extra in base_dir.iterdir():        # config, tokenizer (the base's shard index no longer applies)
        if extra.is_file() and extra.suffix != ".safetensors" and not extra.name.endswith(".index.json"):
            shutil.copy(extra, out_dir / extra.name)
    (out_dir / "model.safetensors.index.json").write_text(json.dumps({"metadata": {}, "weight_map": weight_map}))
    return out_dir


def build_llama_cpp(where: str | Path = "llama.cpp") -> Path:
    """llama.cpp's converter and quantizer: the tools that make Ollama's GGUF model files."""
    import subprocess

    where = Path(where).resolve()   # through a symlink, cmake sees a different path from its cached build
    if not where.exists():
        subprocess.run(["git", "clone", "-q", "--depth", "1", "https://github.com/ggml-org/llama.cpp.git",
                        str(where)], check=True)
    # The converter imports sentencepiece before it tries a model's other tokenizer formats.
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", str(where / "gguf-py"), "sentencepiece",
                    "protobuf"], check=True)
    subprocess.run(["cmake", "-B", str(where / "build"), "-S", str(where), "-DLLAMA_CURL=OFF",
                    "-DLLAMA_BUILD_TESTS=OFF", "-DLLAMA_BUILD_EXAMPLES=OFF", "-DCMAKE_BUILD_TYPE=Release"],
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["cmake", "--build", str(where / "build"), "--target", "llama-quantize", "-j", "4"],
                   check=True, stdout=subprocess.DEVNULL)
    return where


def to_gguf(model_dir: str | Path, out_file: str | Path, *, llama_cpp: str | Path = "llama.cpp",
            quant: str = "Q4_K_M") -> Path:
    """One GGUF file at `quant`, the compression Ollama's llama3.2:3b uses (so it runs as fast)."""
    import subprocess

    llama_cpp, out_file = Path(llama_cpp), Path(out_file)
    f16 = out_file.with_name(out_file.stem + ".f16.gguf")
    subprocess.run([sys.executable, str(llama_cpp / "convert_hf_to_gguf.py"), str(model_dir),
                    "--outtype", "f16", "--outfile", str(f16)], check=True)
    weights = sum(p.stat().st_size for p in Path(model_dir).glob("*.safetensors"))
    if f16.stat().st_size < 0.9 * weights:      # 16-bit in, 16-bit out: sizes should match
        raise RuntimeError(f"the converter wrote {f16.stat().st_size / 1e9:.2f} GB from {weights / 1e9:.2f} GB "
                           f"of weights in {model_dir}; it missed some of the weight files")
    subprocess.run([str(llama_cpp / "build" / "bin" / "llama-quantize"), str(f16), str(out_file), quant],
                   check=True, stdout=subprocess.DEVNULL)
    f16.unlink()
    return out_file


def merge_on_this_pc(adapter_zip: str | Path, out_dir: str | Path, work: str | Path) -> Path:
    """The whole merge without Colab, from the notebook's nos-lora.zip: download the student, merge with
    little memory, convert, and put the GGUF plus the adapter and its kept/rejected answers in out_dir.
    Needs `hf auth login` (the student is gated) and llama.cpp; about 20 GB free in `work`."""
    import shutil
    import zipfile

    from huggingface_hub import snapshot_download

    work, out_dir = Path(work), Path(out_dir)
    if (work / "nos-lora").exists():
        shutil.rmtree(work / "nos-lora")
    with zipfile.ZipFile(adapter_zip) as z:
        z.extractall(work)
    print("downloading the base model (6.4 GB the first time)", flush=True)
    base = snapshot_download(STUDENT, local_dir=work / "base", allow_patterns=["*.json", "*.safetensors"],
                             ignore_patterns=["original/*"])
    print("merging", flush=True)
    merged = merge_adapter_streaming(work / "nos-lora" / "adapter", base, work / "merged")
    print("converting", flush=True)
    gguf = to_gguf(merged, work / "nos-lora.Q4_K_M.gguf", llama_cpp=build_llama_cpp(work / "llama.cpp"))
    shutil.rmtree(merged)
    # copyfile, not copy: a Windows drive mounted in WSL refuses Linux permission changes.
    (out_dir / "adapter").mkdir(parents=True, exist_ok=True)
    for src in [gguf, work / "nos-lora" / "kept.jsonl", work / "nos-lora" / "rejected.jsonl"]:
        shutil.copyfile(src, out_dir / src.name)
    for src in (work / "nos-lora" / "adapter").iterdir():
        shutil.copyfile(src, out_dir / "adapter" / src.name)
    return out_dir / gguf.name


def try_adapter(adapter: str | Path, rows: list[dict], *, student: str = STUDENT) -> list[tuple[dict, str, dict]]:
    """The trained model's answers to rows it was not trained on (test_rows()), with their scores."""
    from peft import PeftModel

    model, tokenizer = load_model(student)
    model = PeftModel.from_pretrained(model, str(adapter))
    answers = generate(rows, model, tokenizer, batch_size=4, log=lambda _: None)
    del model
    release_gpu_memory()
    return [(row, answer, check(row, answer)) for row, (answer, _) in zip(rows, answers)]


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Merge the Colab-trained LoRA into one GGUF for Ollama, on this PC "
                                            "(run in WSL/Linux with torch, transformers, peft and cmake).")
    p.add_argument("adapter_zip", type=Path, help="nos-lora.zip from colab/local_ai_lora_colab.ipynb")
    p.add_argument("--out", type=Path, default=REPO / "ollama" / "nos-lora", help="default: ollama/nos-lora/")
    p.add_argument("--work", type=Path, default=Path.home() / "nos-lora-work", help="scratch space (~20 GB)")
    args = p.parse_args()
    print(f"done: {merge_on_this_pc(args.adapter_zip, args.out, args.work)}")
    print("next, on Windows: python local_ai_tuning.py create")
