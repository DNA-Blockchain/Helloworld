#!/usr/bin/env python3
"""Launch the TwinOS agent toolkit with auto-approval on.

Works the same on Windows, macOS, Linux, WSL, Cloud Shell, Termux (Android)
and CI. Python 3.7+ and the standard library are all it needs.

    python toolkit/run.py --tools
    python toolkit/run.py --tool read_file '{"path": "README.md"}'
    python toolkit/run.py --server            (localhost; set RABBIT_TWIN_TOKEN to expose it)
    python toolkit/run.py --demo

Agents and their commands are listed in toolkit/agents.json.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("RABBIT_AUTO_APPROVE", "1")
script = ROOT / "research" / "universal_twinos_eeg_wormhole.py"
command = [sys.executable, str(script),
           "--tool-root", str(ROOT),
           "--agents-file", str(ROOT / "toolkit" / "agents.json"),
           *sys.argv[1:]]
try:
    sys.exit(subprocess.call(command))
except KeyboardInterrupt:
    sys.exit(130)
