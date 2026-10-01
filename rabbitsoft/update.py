"""`rabbit update`: is there a newer RabbitSoftware release, and if so, install it (after a yes).

An installed copy updates by re-running its installer for the same folder, which keeps its data. A
developer's git checkout is left alone: it updates with git.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError

REPO = "DNA-Blockchain/Helloworld"
RELEASES = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse(version: str) -> tuple[int, ...]:
    """'v1.2.3' or '1.2.3' -> (1, 2, 3); anything unreadable sorts lowest."""
    try:
        return tuple(int(part) for part in version.strip().removeprefix("v").split("."))
    except ValueError:
        return (0,)


def latest_release(fetch: Callable[[str], bytes] | None = None) -> str | None:
    """The newest published release tag, or None if there's none yet (or GitHub can't be reached)."""
    def default_fetch(url: str) -> bytes:
        from hosted_ai import SSL_CONTEXT

        request = urllib.request.Request(url, headers={"User-Agent": "RabbitSoftware-update",
                                                       "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
            return response.read(1024 * 1024)

    try:
        return json.loads((fetch or default_fetch)(RELEASES)).get("tag_name") or None
    except (HTTPError, URLError, OSError, ValueError):
        return None


def installer_command(home: Path, tag: str, platform: str = sys.platform) -> list[str]:
    """Re-runs the installer from that release, into this same folder."""
    base = f"https://raw.githubusercontent.com/{REPO}/{tag}"
    if platform == "win32":
        script = (f"$env:RABBIT_HOME = '{home}'; Remove-Item Env:RABBIT_CHANNEL -ErrorAction SilentlyContinue; "
                  f"irm {base}/install.ps1 | iex")
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    return ["bash", "-c", f"curl -fsSL {base}/install.sh | RABBIT_HOME='{home}' bash"]


def check(root: Path, current: str, fetch=None) -> dict:
    """What `rabbit update` should say and do."""
    if (root / ".git").exists():
        return {"action": "git", "message": "This is a development copy (a git checkout): update it with git pull."}
    tag = latest_release(fetch)
    if tag is None:
        return {"action": "none", "message": f"You have {current}. No release is published yet (or GitHub couldn't be reached)."}
    if parse(tag) <= parse(current):
        return {"action": "none", "message": f"You have {current}, the latest release."}
    return {"action": "install", "tag": tag,
            "message": f"Release {tag} is available (you have {current}). Updating keeps your chains, notes, "
                       "research, account and settings."}
