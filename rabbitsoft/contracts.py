"""The APIs between the parts of RabbitSoftware, as versioned JSON Schemas in schemas/rabbitsoftware-*.

Each API's schema file has an $id; a message is checked against one definition inside it, e.g.
validate(reply, "app-api-v1", "messageReply"). Changes that only add fields or routes keep the v1 file;
anything that would break an existing reader gets a new -v2 file and a MAJOR version (RELEASING.md).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
BASE = "https://schemas.rabbitsoftware.local/"
APIS = ("app-api-v1", "shell-api-v1", "node-api-v1", "model-api-v1", "sync-api-v1", "integrity-v1",
        "pipeline-report-v1")


def _uri(api: str) -> str:
    return f"{BASE}rabbitsoftware-{api}.schema.json"


@lru_cache(maxsize=1)
def registry():
    from referencing import Registry, Resource

    resources = [(_uri(api), Resource.from_contents(json.loads((SCHEMAS / f"rabbitsoftware-{api}.schema.json")
                                                                .read_text(encoding="utf-8")))) for api in APIS]
    return Registry().with_resources(resources)


def validator(api: str, definition: str | None = None):
    from jsonschema import Draft202012Validator, FormatChecker

    ref = _uri(api) + (f"#/$defs/{definition}" if definition else "")
    return Draft202012Validator({"$ref": ref}, registry=registry(), format_checker=FormatChecker())


def errors(instance, api: str, definition: str | None = None) -> list[str]:
    """Every way the instance breaks the contract, as readable lines (empty when it fits)."""
    return [f"{'/'.join(map(str, e.absolute_path)) or '(top)'}: {e.message}"
            for e in validator(api, definition).iter_errors(instance)]


def validate(instance, api: str, definition: str | None = None) -> None:
    problems = errors(instance, api, definition)
    if problems:
        raise ValueError(f"doesn't fit {api}{'#' + definition if definition else ''}: " + "; ".join(problems))
