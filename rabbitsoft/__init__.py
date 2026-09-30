"""
RabbitSoftware: one assistant for this OS, in a terminal or a web page.

It reads what the OS already records (nodes, chain audits, the swarm, the token
ledger, the research agents and catalog, daily reports) and answers in short,
plain sentences. It is built to be easy to use: misspellings are fixed, choices
are numbered, and nothing that sends data out or changes anything happens
without a yes.

    python rabbit.py chat          # terminal
    python rabbit.py web           # web page at http://127.0.0.1:8792
    python rabbit.py ask "how are the nodes doing"
"""

NAME = "RabbitSoftware"
