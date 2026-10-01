"""
RabbitSoftware.inc, from RabbitSoftware, Inc.: one assistant for this OS, in a terminal or a web page.

It reads what the OS already records (nodes, chain audits, the swarm, the token
ledger, the research agents and catalog, integrity reports, daily reports) and
answers from that data. Research questions get a cited technical answer
(findings, methods and evidence, limitations) with the retrieval behind it.
Requests are routed deterministically, with spelling correction and numbered
choices, and nothing that sends data out or changes anything happens without
a yes.

    python rabbit.py chat          # terminal
    python rabbit.py web           # web page at http://127.0.0.1:8792
    python rabbit.py ask "how are the nodes doing"
"""

from pathlib import Path

try:                                 # one version for the whole project: the VERSION file (see RELEASING.md)
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    __version__ = "0.0.0"

NAME = "RabbitSoftware.inc"          # the assistant: page heading, chat label, terminal prompt
COMPANY = "RabbitSoftware, Inc."     # the company it comes from
GREETING = f"Hello! I'm {NAME}, the assistant from {COMPANY}"     # COMPANY already ends the sentence
