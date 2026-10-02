"""Prints one version's section of CHANGELOG.md (the release notes), or exits 1 if it's missing.

    python scripts/release_notes.py 0.9.0
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(changelog: str, version: str) -> str | None:
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(?P<body>.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    return match.group("body").strip() if match else None


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: release_notes.py VERSION", file=sys.stderr)
        return 2
    notes = section(CHANGELOG.read_text(encoding="utf-8"), argv[0].removeprefix("v"))
    if not notes:
        print(f"CHANGELOG.md has no section for {argv[0]}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")          # the Windows console isn't UTF-8 by default
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
