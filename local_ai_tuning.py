"""
local_ai_tuning.py
==================
Measures how well the local Ollama model does the project's two writing jobs,
so a prompt or model change is kept only when it scores better:

  explain   swarm_explain.py: 3 to 5 sentences about verified swarm facts,
            one case per synthetic subject (8 cases)
  summary   research_summaries.py: one plain sentence per paper title, from
            the published records on this machine (or built-in titles)

Every output goes through the same code checks the project applies before
showing it, plus stricter ones: sentence count, an introduction line,
invented framing ("researchers designed..."), names dropped from a title, a
title copied back almost word for word. Scores are counted, not judged by
another model.

Variants pair a model with a prompt. "baseline" is what the project runs
today; "system" uses the custom models in ollama/*.Modelfile; "examples" adds
one worked example to the prompt. Build the custom models first:

    python local_ai_tuning.py create
    python local_ai_tuning.py run                        # every variant, both jobs
    python local_ai_tuning.py run --variants baseline,examples --tasks summary --titles 20

Each run writes every output and score to autonomous/ai-tuning/.
Everything stays on this machine: Ollama is reached on loopback only.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import research_summaries as rs
import swarm_analysis
import swarm_explain as se

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "autonomous" / "ai-tuning"
CUSTOM_MODELS = {"nos-explain": ROOT / "ollama" / "nos-explain.Modelfile",
                 "nos-summary": ROOT / "ollama" / "nos-summary.Modelfile"}

# One worked example per job, written by hand from facts that are not test cases.
EXPLAIN_EXAMPLE_FACTS = [
    "Subject: Example sequence (example:0), 90 DNA bases.",
    "The sample differs from its reference at 2 position(s).",
    "At position 14 the codon changes from GCT to GAT (a missense change); the tRNA anticodons are AGC and "
    "AUC; hydropathy changes by -5.3.",
    "At position 40 the codon changes from CTG to CTA (the protein is unchanged); the tRNA anticodons are "
    "CAG and UAG.",
    "The highest siRNA design score is 8 out of 10, for the 19-base window starting at position 22.",
    "3 scored window(s) cover the difference; the best scores 6.",
    "siRNA scores are Reynolds et al. 2004 design heuristics and have not been tested.",
]
EXPLAIN_EXAMPLE_ANSWER = (
    "This computer analysis compares a 90-base DNA sequence with its reference and finds 2 positions where "
    "they differ. At position 14 the codon changes from GCT to GAT, a missense change that swaps one amino "
    "acid for another, and hydropathy decreases by 5.3. At position 40 the codon changes from CTG to CTA, "
    "but the protein is unchanged. The best siRNA design, a short RNA meant to switch off a gene's message, "
    "scores 8 out of 10 at position 22, and 3 scored windows cover the difference, the best scoring 6. "
    "These scores are Reynolds et al. 2004 design estimates and have not been tested."
)
EXPLAIN_WITH_EXAMPLE = se.PROMPT.replace(
    "Facts:\n{facts}",
    "Example facts:\n" + "\n".join(f"- {f}" for f in EXPLAIN_EXAMPLE_FACTS).replace("{", "{{").replace("}", "}}")
    + "\nExample explanation:\n" + EXPLAIN_EXAMPLE_ANSWER
    + "\n\nNow explain these facts the same way. Use only these facts, not the example's.\n\nFacts:\n{facts}")

SUMMARY_EXAMPLES = [
    ("Germline TP53 variants and early-onset breast cancer: a population-based case-control study",
     "A population-based case-control study looks at whether inherited TP53 variants are linked to breast "
     "cancer that starts at a young age."),
    ("Olaparib versus placebo in BRCA1/2-mutated pancreatic cancer (POLO): a phase 3 trial",
     "The POLO phase 3 trial compares Olaparib with a placebo in pancreatic cancer with BRCA1/2 mutations."),
]
SUMMARY_WITH_EXAMPLES = rs.PROMPT.replace(
    "Title: {title}",
    "".join(f"Example title: {t}\nExample sentence: {s}\n\n" for t, s in SUMMARY_EXAMPLES)
    + "Now the real title.\nTitle: {title}")

PROMPTS = {"explain": {"current": se.PROMPT, "example": EXPLAIN_WITH_EXAMPLE},
           "summary": {"current": rs.PROMPT, "example": SUMMARY_WITH_EXAMPLES}}


@dataclass(frozen=True)
class Variant:
    name: str
    models: dict[str, str]      # task -> Ollama model
    prompt: str                 # key in PROMPTS[task]


VARIANTS = {v.name: v for v in (
    Variant("baseline", {"explain": rs.DEFAULT_MODEL, "summary": rs.DEFAULT_MODEL}, "current"),
    Variant("system", {"explain": "nos-explain", "summary": "nos-summary"}, "current"),
    Variant("examples", {"explain": rs.DEFAULT_MODEL, "summary": rs.DEFAULT_MODEL}, "example"),
    Variant("system+examples", {"explain": "nos-explain", "summary": "nos-summary"}, "example"),
)}

FALLBACK_TITLES = [
    "BRCA1 and BRCA2 mutation carriers and breast cancer risk: a prospective cohort study",
    "Somatic TP53 mutations in colorectal adenocarcinoma: prevalence and prognostic value",
    "CRISPR-Cas9 screening identifies PARP1 dependencies in ovarian cancer cell lines",
    "Hereditary cancer genetic testing outcomes in 2,000 patients over ten years",
]
# Storytelling the explain facts never support: who made the sequence, or why. The prompt's own
# background ("lab researchers design" siRNAs) is allowed.
INVENTED_FRAMING = re.compile(
    r"\b(scientists?|a study|this study|experiment|new approach|to test|"
    r"(researchers?|they|someone) (designed|created|made|built|developed) (a|an|the|this) "
    r"(synthetic |short |new )?(dna|sequence))\b", re.I)
PREAMBLE = re.compile(r"^(here('s| is)|sure|certainly|explanation|summary)\b", re.I)


def sentences(text: str) -> list[str]:
    """Split after . ! or ?, but not after "et al." (the facts cite "Reynolds et al. 2004")."""
    return [s for s in re.split(r"(?<=[.!?])(?<!\bal\.)\s+(?=[A-Z0-9])", text.strip()) if s]


def names_in(title: str) -> list[str]:
    """Gene, drug and trial names: words with a digit or two capitals (BRCA1, TP53, POLO, BRCA1/2)."""
    words = [w.strip(".'\"") for w in re.split(r"[\s\-()\[\];,:/]+", title)]
    return [w for w in words if len(w) > 1 and (re.search(r"\d", w) and re.search(r"[A-Za-z]", w)
                                                or len(re.findall(r"[A-Z]", w)) >= 2)]


def score_explain(facts: list[str], model, prompt: str) -> dict:
    try:
        text = se.explain(facts, model, prompt)
    except ValueError as error:
        return {"ok": False, "withheld": str(error), "flags": ["withheld"]}
    flags = []
    if not 3 <= len(sentences(text)) <= 5:
        flags.append(f"{len(sentences(text))} sentences")
    if PREAMBLE.match(text):
        flags.append("introduction line")
    if INVENTED_FRAMING.search(text):
        flags.append(f"invented framing: '{INVENTED_FRAMING.search(text).group(0)}'")
    return {"ok": not flags, "text": text, "flags": flags}


def score_summary(title: str, model, prompt: str) -> dict:
    try:
        text = rs.clean_summary(model.generate(prompt.format(title=title)))
    except ValueError as error:
        return {"ok": False, "withheld": str(error), "flags": ["no text"]}
    flags = []
    if len(sentences(text)) != 1:
        flags.append(f"{len(sentences(text))} sentences")
    if PREAMBLE.match(text):
        flags.append("introduction line")
    added = se._numbers(text) - se._numbers(title)
    if added:
        flags.append(f"added numbers: {', '.join(f'{n:g}' for n in sorted(added))}")
    dropped = [n for n in names_in(title) if n not in text]
    if dropped:
        flags.append(f"dropped names: {', '.join(dropped)}")
    claims = lambda s: set(re.findall(r"\b(cure[sd]?|prove[sn]?|breakthrough|effective|causes?)\b", s.lower()))
    added_claims = sorted(claims(text) - claims(title))
    if added_claims:
        flags.append(f"added claims: {', '.join(added_claims)}")
    if difflib.SequenceMatcher(None, text.lower().rstrip("."), title.lower().rstrip(".")).ratio() > 0.9:
        flags.append("copied the title")
    return {"ok": not flags, "text": text, "flags": flags}


def explain_cases() -> list[tuple[str, list[str]]]:
    cases = []
    for n in range(swarm_analysis.SYNTHETIC_COUNT):
        subject = swarm_analysis.resolve(f"synthetic:{n}", None)
        cases.append((subject["id"], se.facts_for(swarm_analysis.analyze(subject), subject)))
    return cases


def summary_cases(limit: int) -> list[tuple[str, str]]:
    """Published titles on this machine, a fixed selection so runs compare; else built-in titles."""
    try:
        records = sorted(rs.published_records(rs.DEFAULT_BASE_DIR), key=rs.record_key)
    except Exception:           # no local research data: the built-in titles still give a comparison
        records = []
    titles = [(rs.record_key(r), r["title"]) for r in records if r.get("title")]
    return titles[:limit] if titles else list(enumerate(FALLBACK_TITLES))[:limit]


def run(variants: list[Variant], tasks: list[str], titles: int, endpoint: str, log=print) -> dict:
    cases = {"explain": explain_cases() if "explain" in tasks else [],
             "summary": summary_cases(titles) if "summary" in tasks else []}
    report = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "results": []}
    for variant in variants:
        for task in tasks:
            model = rs.OllamaSummarizer(variant.models[task], endpoint, timeout=600)
            prompt = PROMPTS[task][variant.prompt]
            scorer = score_explain if task == "explain" else score_summary
            rows, started = [], time.time()
            for case_id, case in cases[task]:
                t = time.time()
                row = {"case": str(case_id), "input": case, **scorer(case, model, prompt)}
                row["seconds"] = round(time.time() - t, 1)
                rows.append(row)
                log(f"  {variant.name:16} {task:8} {row['case']:28} {'ok ' if row['ok'] else 'BAD'} "
                    f"{'; '.join(row['flags'])}")
            report["results"].append({"variant": variant.name, "task": task, "model": variant.models[task],
                                      "prompt": variant.prompt, "passed": sum(r["ok"] for r in rows),
                                      "cases": len(rows), "seconds": round(time.time() - started, 1),
                                      "rows": rows})
    return report


def table(report: dict) -> str:
    lines = [f"{'variant':16} {'task':8} {'model':12} {'passed':>8} {'avg s':>6}  most common problems"]
    for r in report["results"]:
        flags: dict[str, int] = {}
        for row in r["rows"]:
            for flag in row["flags"]:
                kind = flag.split(":")[0]
                flags[kind] = flags.get(kind, 0) + 1
        common = ", ".join(f"{k} x{v}" for k, v in sorted(flags.items(), key=lambda kv: -kv[1])[:3]) or "-"
        avg = r["seconds"] / max(1, r["cases"])
        lines.append(f"{r['variant']:16} {r['task']:8} {r['model']:12} {r['passed']:>3}/{r['cases']:<4} "
                     f"{avg:6.1f}  {common}")
    return "\n".join(lines)


class Replay:
    """Stands in for the model when rescoring: returns the saved output."""

    def __init__(self, text: str):
        self.text = text

    def generate(self, prompt: str, num_predict: int = 120) -> str:
        return self.text


def rescore(report: dict) -> dict:
    """Score a saved run again with the current checks, without calling the model. Rows the project's own
    checks withheld have no saved text and stay withheld."""
    for result in report["results"]:
        for row in result["rows"]:
            if "text" not in row:
                continue
            if result["task"] == "explain":
                scored = score_explain(row["input"], Replay(row["text"]), "{facts}")
            else:
                scored = score_summary(row["input"], Replay(row["text"]), "{title}")
            row.update(ok=scored["ok"], flags=scored["flags"])
        result["passed"] = sum(r["ok"] for r in result["rows"])
    return report


def create_models() -> int:
    for name, modelfile in CUSTOM_MODELS.items():
        print(f"ollama create {name}")
        result = subprocess.run(["ollama", "create", name, "-f", str(modelfile)], capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("create", help="build the custom models in ollama/*.Modelfile")
    r = sub.add_parser("run", help="score variants and save every output")
    r.add_argument("--variants", default=",".join(VARIANTS), help=f"comma-separated: {', '.join(VARIANTS)}")
    r.add_argument("--tasks", default="explain,summary")
    r.add_argument("--titles", type=int, default=12, help="title cases for the summary job (default 12)")
    r.add_argument("--endpoint", default=rs.DEFAULT_ENDPOINT, help="local Ollama (numeric loopback IP only)")
    rescore_cmd = sub.add_parser("rescore", help="score a saved run again with the current checks")
    rescore_cmd.add_argument("report", type=Path, help="a run-*.json from autonomous/ai-tuning/")
    args = p.parse_args(argv)

    if args.command == "create":
        return create_models()
    if args.command == "rescore":
        print(table(rescore(json.loads(args.report.read_text(encoding="utf-8")))))
        return 0
    unknown = [v for v in args.variants.split(",") if v not in VARIANTS]
    tasks = args.tasks.split(",")
    if unknown or not set(tasks) <= {"explain", "summary"}:
        p.error(f"unknown variant or task: {unknown or tasks}")
    report = run([VARIANTS[v] for v in args.variants.split(",")], tasks, args.titles, args.endpoint)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"run-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n" + table(report))
    print(f"\nevery output: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
