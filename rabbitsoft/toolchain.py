"""The tools this OS needs, on this PC and in WSL: what's there, what's missing, and how to get it.

Part of the integrity team. It only looks (`command -v` / PATH); installing is a separate step that
RabbitSoftware.inc asks about first, and only for Windows tools through winget. Linux and WSL installs
need your password (sudo), so for those it tells you the exact command to run yourself.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    key: str
    name: str
    commands: tuple[str, ...]     # any one of these on PATH counts
    needed_for: str
    winget: str = ""              # winget package id on Windows ("" = none)
    linux: str = ""               # the command to install it on Ubuntu/WSL


TOOLS = (
    Tool("python", "Python 3", ("python3", "python"), "everything",
         "Python.Python.3.12", "sudo apt install -y python3 python3-venv"),
    Tool("git", "Git", ("git",), "updates and review branches", "Git.Git", "sudo apt install -y git"),
    Tool("node", "Node.js", ("node",), "the Cloudflare model gateway, through wrangler",
         "OpenJS.NodeJS.LTS", "sudo apt install -y nodejs npm"),
    Tool("rust", "Rust (cargo)", ("cargo",), "the Rust kernel in os/",
         "Rustlang.Rustup", "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"),
    Tool("qemu", "QEMU", ("qemu-system-x86_64",), "booting the RabbitSoftware OS image and the Rust kernel",
         "SoftwareFreedomConservancy.QEMU", "sudo apt install -y qemu-system-x86"),
    Tool("cmake", "CMake", ("cmake",), "building native code", "Kitware.CMake", "sudo apt install -y cmake"),
    Tool("cc", "C/C++ compiler", ("gcc", "clang", "cl"), "MicroPython for the kernel, native code",
         "LLVM.LLVM", "sudo apt install -y build-essential"),
    Tool("java", "Java", ("java",), "Java components", "EclipseAdoptium.Temurin.21.JDK",
         "sudo apt install -y openjdk-21-jdk"),
    Tool("jq", "jq (JSON tool)", ("jq",), "reading JSON in scripts", "jqlang.jq", "sudo apt install -y jq"),
    Tool("ollama", "Ollama", ("ollama",), "running the AI on this computer; optional with the hosted model",
         "Ollama.Ollama", "curl -fsSL https://ollama.com/install.sh | sh"),
)
BY_KEY = {t.key: t for t in TOOLS}
ALIASES = {"c++": "cc", "c": "cc", "gcc": "cc", "clang": "cc", "compiler": "cc", "cargo": "rust", "rustup": "rust",
           "nodejs": "node", "npm": "node", "jdk": "java", "python3": "python", "qemu-system-x86_64": "qemu"}

WSL_SCRIPT = "for c in {cmds}; do command -v \"$c\" >/dev/null 2>&1 && echo \"$c\"; done; true"


def tool_named(text: str) -> Tool | None:
    word = text.strip().lower()
    return BY_KEY.get(ALIASES.get(word, word)) or next((t for t in TOOLS if t.name.lower() == word), None)


def found_here(which=shutil.which) -> set[str]:
    return {c for t in TOOLS for c in t.commands if which(c)}


def found_in_wsl(run=subprocess.run) -> set[str] | None:
    """Commands present in the default WSL distribution; None if there's no WSL (or this isn't Windows)."""
    if sys.platform != "win32" or not shutil.which("wsl.exe"):
        return None
    commands = " ".join(sorted({c for t in TOOLS for c in t.commands}))
    try:
        # --exec: run sh directly. With "--", wsl.exe hands the line to a shell first, which mangles the script.
        result = run(["wsl.exe", "--exec", "sh", "-c", WSL_SCRIPT.format(cmds=commands)],
                     capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return set(result.stdout.split()) if result.returncode == 0 else None


def winget_available(which=shutil.which) -> bool:
    return sys.platform == "win32" and bool(which("winget"))


def survey(here: set[str] | None = None, wsl: set[str] | None | bool = False) -> list[dict]:
    """One row per tool: whether it's on this computer and (on Windows) in WSL."""
    here = found_here() if here is None else here
    wsl = found_in_wsl() if wsl is False else wsl
    return [{"tool": t, "here": any(c in here for c in t.commands),
             "wsl": None if wsl is None else any(c in wsl for c in t.commands)} for t in TOOLS]


def describe(rows: list[dict], windows: bool = sys.platform == "win32", winget: bool | None = None) -> list[str]:
    here_name = "Windows" if windows else "this computer"
    winget = winget_available() if winget is None else winget
    lines, missing = [], []
    for row in rows:
        t = row["tool"]
        places = [f"{here_name} {'yes' if row['here'] else 'no'}"]
        if row["wsl"] is not None:
            places.append(f"WSL {'yes' if row['wsl'] else 'no'}")
        lines.append(f"{t.name}: {', '.join(places)} (for {t.needed_for}).")
        if not row["here"] or row["wsl"] is False:
            missing.append(row)
    if not missing:
        return lines + ["Everything is here."]
    lines.append("")
    for row in missing:
        t = row["tool"]
        if not row["here"]:
            if windows and t.winget:
                how = (f"say \"install {t.key}\"" if winget else
                       f"winget install -e --id {t.winget}")
                lines.append(f"To add {t.name} on {here_name}: {how}.")
            elif t.linux:
                lines.append(f"To add {t.name}: {t.linux}")
        if row["wsl"] is False and t.linux:
            lines.append(f"To add {t.name} in WSL, run in Ubuntu: {t.linux}")
    if windows and not winget:
        lines.append("winget is installed but switched off: Settings > Apps > Advanced app settings > App "
                     "execution aliases > turn on \"Windows Package Manager Client\". Then I can install for you.")
    return lines


def winget_command(tool: Tool) -> list[str]:
    return ["winget", "install", "-e", "--id", tool.winget, "--accept-source-agreements",
            "--accept-package-agreements", "--disable-interactivity"]
