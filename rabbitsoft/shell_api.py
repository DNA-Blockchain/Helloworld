"""The OS shell's read-only snapshot (schemas/rabbitsoftware-shell-api-v1): nodes, background jobs, AI,
account and the latest integrity report, read from files the OS already writes. It changes nothing."""
from __future__ import annotations

import json

from . import __version__, tools


def _latest_integrity(paths: tools.Paths) -> dict | None:
    reports = sorted((paths.autonomous / "integrity").glob("integrity-*.json"))
    if not reports:
        return None
    try:
        report = json.loads(reports[-1].read_text(encoding="utf-8"))
        return {"created_at": str(report["created_at"]), "ok": bool(report["ok"])}
    except (OSError, ValueError, KeyError):
        return None


def snapshot(paths: tools.Paths, jobs=None) -> dict:
    from hosted_ai import configured_url

    nodes = []
    for d in paths.node_dirs():
        status = tools._load(d / "status.json") or {}
        nodes.append({"id": d.name, "chain_blocks": int(status.get("chain_blocks") or 0),
                      "chain_ok": bool(status.get("chain_ok")),
                      "connected_peers": [int(p) for p in status.get("connected_peers") or []],
                      "updated_at": status.get("updated_at")})
    return {
        "schema": "rabbitsoft-shell.v1",
        "version": __version__,
        "nodes": nodes,
        "jobs": [{"name": j.name, "running": j.finished is None, "summary": j.summary}
                 for j in (jobs.items[-10:] if jobs else [])],
        "ai": {"model_server": configured_url(paths.rabbit / "settings.json") or None,
               "account": (paths.rabbit / "account" / "account.json").exists()},
        "integrity": _latest_integrity(paths),
    }
