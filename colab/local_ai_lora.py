"""
Teacher answers -> the project's checks -> a LoRA for the local model.
Used by colab/local_ai_lora_colab.ipynb on a Colab GPU.

1. A larger model (the teacher, default Qwen2.5-7B-Instruct) answers each
   training prompt from `local_ai_tuning.py export`, with the same system
   text the Ollama models use.
2. Every answer goes through the checks local_ai_tuning.py scores with.
   Only answers that pass are kept; a failed prompt gets retried with
   sampling. What was kept and what was rejected are both saved.
3. A LoRA is trained on Llama-3.2-3B-Instruct, the model Ollama runs as
   llama3.2:3b, on the kept answers only (loss on the answer, not the
   prompt). The adapter is saved in the safetensors layout Ollama's
   ADAPTER instruction reads.
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


def messages(row: dict, answer: str | None = None) -> list[dict]:
    chat = [{"role": "system", "content": row["system"]}, {"role": "user", "content": row["prompt"]}]
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
             log=print) -> list[tuple[str, bool]]:
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
            texts = [tokenizer.apply_chat_template(messages(rows[i]), tokenize=False, add_generation_prompt=True)
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
        for row, (answer, finished) in zip(pending, generate(pending, model, tokenizer, sample=attempt > 0,
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


def try_adapter(adapter: str | Path, rows: list[dict], *, student: str = STUDENT) -> list[tuple[dict, str, dict]]:
    """The trained model's answers to rows it was not trained on (test_rows()), with their scores."""
    from peft import PeftModel

    model, tokenizer = load_model(student)
    model = PeftModel.from_pretrained(model, str(adapter))
    answers = generate(rows, model, tokenizer, batch_size=4, log=lambda _: None)
    del model
    release_gpu_memory()
    return [(row, answer, check(row, answer)) for row, (answer, _) in zip(rows, answers)]
