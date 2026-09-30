"""Understanding what someone typed, without needing correct spelling or the right words.

Nothing here calls an AI: spelling is fixed against a word list, requests are matched by
keywords, and choices are numbers or yes/no. That keeps it fast and predictable; the AI
is only asked when these rules can't tell what someone means.
"""
from __future__ import annotations

import difflib
import re

# What each tool is about. A request goes to the tool whose words it uses most.
INTENTS: dict[str, tuple[str, ...]] = {
    "help": ("help", "menu", "options", "commands", "what can you do", "how do i", "start"),
    "nodes": ("node", "nodes", "status", "running", "network", "peers", "peer", "uptime", "health",
              "online", "working"),
    "chain": ("chain", "blockchain", "block", "blocks", "verify", "verified", "audit", "audits", "intact",
              "tamper", "mined", "mining"),
    "swarm": ("swarm", "verdict", "verdicts", "accepted", "round", "rounds", "explain", "synthetic",
              "subject", "twin"),
    "ledger": ("token", "tokens", "credit", "credits", "balance", "balances", "ledger", "leaderboard",
               "earned"),
    "activity": ("activity", "log", "logs", "trail", "history", "happened", "events"),
    "agents": ("agent", "agents", "research agent", "research agents", "topic", "topics", "queue", "queued"),
    "report": ("report", "reports", "daily", "today", "yesterday", "overnight"),
    "selftest": ("self-test", "self-tests", "self test", "self tests", "selftest", "selftests", "run tests",
                 "run the tests", "test everything", "check everything", "health check", "run checks"),
    "jobs": ("jobs", "job", "what's running", "whats running", "background", "still running"),
    "research": ("research", "study", "studies", "paper", "papers", "trial", "trials", "gene", "genes",
                 "disease", "treatment", "therapy", "cancer", "mutation", "editing", "crispr", "search",
                 "find", "look up", "question", "evidence"),
}
LABELS = {
    "help": "What I can do",
    "nodes": "How the nodes are doing",
    "chain": "Blockchain checks and audits",
    "swarm": "Swarm results, explained",
    "ledger": "Token ledger balances",
    "activity": "Recent activity log",
    "agents": "Research agents and their topics",
    "report": "Latest daily report",
    "research": "Ask a research question",
    "selftest": "Run the self-tests",
    "jobs": "What's running in the background",
}
START = re.compile(r"\b(start|begin|launch|resume|turn on|switch on)\b", re.I)
STOP = re.compile(r"\b(stop|halt|end|pause|kill|turn off|switch off|shut down)\b", re.I)
# Names and terms people often misspell when asking about this project's research.
DOMAIN_TERMS = (
    "crispr", "cas9", "sirna", "rna", "dna", "gene", "genes", "genetic", "genome", "mutation", "mutations",
    "variant", "variants", "editing", "therapy", "therapies", "treatment", "trial", "trials", "cancer",
    "tumor", "tumour", "breast", "ovarian", "colorectal", "prostate", "pancreatic", "leukemia", "lymphoma",
    "sickle", "cell", "cells", "anemia", "thalassemia", "hemoglobin", "fetal", "brca1", "brca2", "tp53",
    "parp", "inhibitor", "inhibitors", "olaparib", "rucaparib", "chemotherapy", "radiotherapy", "immune",
    "immunotherapy", "protein", "proteins", "enzyme", "hereditary", "inherited", "risk", "carrier",
    "carriers", "diagnosis", "screening", "remission", "hydropathy", "codon", "anticodon", "synthetic",
)
YES = {"y", "yes", "yeah", "yep", "ok", "okay", "sure", "go", "go ahead", "do it", "please", "send", "1"}
NO = {"n", "no", "nope", "stop", "cancel", "don't", "dont", "not now", "2"}


def vocabulary(extra: tuple[str, ...] = ()) -> set[str]:
    words = {w for phrases in INTENTS.values() for p in phrases for w in p.split()}
    return words | set(DOMAIN_TERMS) | {w.lower() for w in extra}


def fix_spelling(text: str, vocab: set[str]) -> str:
    """Each word that isn't known but is close to a known one is replaced by it ("sikle cel" -> "sickle
    cell"). Short words and numbers are left alone: too many ordinary words are one letter from a term."""
    def fix(match: re.Match) -> str:
        word = match.group(0)
        low = word.lower()
        if low in vocab or len(low) < 3 or any(c.isdigit() for c in low):
            return word
        # Longer words can be further off and still be unmistakable ("tokins" -> "tokens").
        cutoff = 0.8 if len(low) >= 6 else 0.84 if len(low) == 5 else 0.85
        close = difflib.get_close_matches(low, vocab, n=1, cutoff=cutoff)
        return close[0] if close else word
    # Words include their digits, so "BRCA1" is one word (left alone), not "BRCA" + "1".
    return re.sub(r"[A-Za-z0-9][A-Za-z0-9'-]*", fix, text)


# Words that come up in almost any question about this OS ("how many tokens do the nodes have") count
# half, so the more specific word decides.
GENERAL = {"node", "nodes", "status", "network", "working", "running", "search", "find", "question"}


def intent_scores(text: str) -> dict[str, float]:
    low = f" {text.lower()} "
    scores = {}
    for intent, phrases in INTENTS.items():
        hits = sum(0.5 if p in GENERAL else 1 for p in phrases if re.search(rf"\b{re.escape(p)}\b", low))
        if hits:
            scores[intent] = hits
    return scores


def best_intent(text: str) -> tuple[str | None, list[str]]:
    """The clear winner, or None and the likely candidates (best first) to offer as choices."""
    scores = intent_scores(text)
    if not scores:
        return None, []
    ranked = sorted(scores, key=lambda i: (-scores[i], list(INTENTS).index(i)))
    if len(ranked) == 1 or scores[ranked[0]] > scores[ranked[1]]:
        return ranked[0], ranked
    return None, ranked


def choice_number(text: str, count: int) -> int | None:
    """1-based choice from "2", "2.", "number 2", "the second one"."""
    ordinals = {"first": 1, "one": 1, "second": 2, "two": 2, "third": 3, "three": 3, "fourth": 4, "four": 4,
                "fifth": 5, "five": 5}
    low = text.strip().lower()
    match = re.fullmatch(r"(?:number|option|choice|#)?\s*(\d+)\.?", low)
    number = int(match.group(1)) if match else next(
        (n for word, n in ordinals.items() if re.fullmatch(rf"(the )?{word}( one)?", low)), None)
    return number if number is not None and 1 <= number <= count else None


def yes_or_no(text: str) -> bool | None:
    low = re.sub(r"[.!]+$", "", text.strip().lower())
    if low in YES:
        return True
    if low in NO:
        return False
    return None


GREETINGS = re.compile(r"^\s*(hi|hello|hey|hiya|howdy|good (morning|afternoon|evening)|thanks?|thank you|"
                       r"cheers)\b[\s!.,]*(there|rabbit\w*|you)?[\s!.,]*$", re.I)
# Everyday words that don't make a research question on their own.
STOPWORDS = {"about", "there", "their", "these", "those", "this", "that", "what", "when", "where", "which",
             "with", "would", "could", "should", "have", "does", "doing", "your", "you're", "tell", "know",
             "want", "like", "please", "thanks", "hello", "some", "more", "much", "many", "just", "from",
             "into", "they", "them", "then", "than", "been", "being", "were", "will", "make", "need"}


def is_greeting(text: str) -> bool:
    return bool(GREETINGS.match(text))


def looks_like_a_question(text: str) -> bool:
    """Enough to search for: a known research term, or two content words of four or more letters."""
    found = re.findall(r"[A-Za-z0-9-]+", text.lower())
    content = [w for w in found if len(w) >= 4 and w not in STOPWORDS]
    return len(content) >= 2 or any(w in DOMAIN_TERMS for w in found)
