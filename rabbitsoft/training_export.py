"""Shared answers: review them in the sync service's SQL database (D1), export them to the private Hugging
Face dataset as Parquet.

    python rabbit.py training stats                 accounts, answers by review status, corpus, exports
    python rabbit.py training pending               answers waiting for review
    python rabbit.py training approve ID [ID...]    (or reject; IDs from "pending")
    python rabbit.py training export                asks first, then uploads data/<date>.parquet
    python rabbit.py training export --daily on     the supervisor exports once a day without asking (off: stop)

An export takes every answer not yet exported and not rejected, screens each again for personal information
(any that fails is left out and marked rejected), writes one Parquet file (zstd), checks the dataset repo is
private, uploads it, and then records the file, its SHA-256 and the Hugging Face commit on the service. The
service marks those answers exported in the same transaction, so no answer is exported twice.

Only the owner's account can do this (ADMIN_ACCOUNT on the sync service). Uploading uses this PC's own
Hugging Face login (hf auth login); no Hugging Face token is stored in Cloudflare.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
from pathlib import Path

DATASET_REPO = "rabbitsoftware-training"
COLUMNS = ("id", "shared_at", "question", "answer", "sources", "rating", "model", "status")


def _schema():
    import pyarrow as pa

    return pa.schema([("id", pa.string()), ("shared_at", pa.string()), ("question", pa.string()),
                      ("answer", pa.string()), ("sources", pa.list_(pa.string())), ("rating", pa.int8()),
                      ("model", pa.string()), ("status", pa.string())])


def to_parquet(items: list[dict]) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist([{k: item.get(k) for k in COLUMNS} for item in items], schema=_schema())
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="zstd")
    return buffer.getvalue()


def export_file_name(existing: set[str], day: str) -> str:
    name, n = f"data/{day}.parquet", 2
    while name in existing:
        name, n = f"data/{day}-{n}.parquet", n + 1
    return name


def export(client, hub=None, repo: str | None = None, ask=input, today: str | None = None, log=None) -> dict:
    """One export run. Returns what happened; raises on a service or Hugging Face error."""
    from research_provenance import personal_information

    items = client.training_to_export()
    if not items:
        return {"exported": 0, "message": "No new shared answers to export."}
    clean = [i for i in items if not personal_information(f"{i['question']}\n{i['answer']}")]
    flagged = [i["id"] for i in items if i not in clean]
    if flagged:
        client.review_training(flagged, "rejected")
    if not clean:
        return {"exported": 0, "rejected_personal": len(flagged),
                "message": f"{len(flagged)} answer(s) held personal information and were rejected; nothing to export."}
    if hub is None:
        from huggingface_hub import HfApi
        hub = HfApi()
    repo = repo or f"{hub.whoami()['name']}/{DATASET_REPO}"
    if not hub.repo_info(repo, repo_type="dataset").private:
        raise RuntimeError(f"{repo} is public; shared answers only go to a private dataset")
    data = to_parquet(clean)
    file = export_file_name(set(hub.list_repo_files(repo, repo_type="dataset")),
                            today or dt.datetime.now(dt.timezone.utc).date().isoformat())
    sha256 = hashlib.sha256(data).hexdigest()
    question = (f"Upload {len(clean)} shared answer(s) ({len(data) / 1000:.1f} kB Parquet) to the private dataset "
                f"{repo} as {file}? (yes/no) ")
    if ask(question).strip().lower() not in ("y", "yes"):
        return {"exported": 0, "message": "Nothing was uploaded."}
    commit = hub.upload_file(path_or_fileobj=data, path_in_repo=file, repo_id=repo, repo_type="dataset",
                             commit_message=f"Export {len(clean)} shared answers ({file})")
    oid = str(getattr(commit, "oid", "") or "")
    marked = client.mark_exported(file, sha256, oid, [i["id"] for i in clean])
    result = {"exported": len(clean), "marked": marked, "file": file, "sha256": sha256, "commit": oid,
              "repo": repo, "rejected_personal": len(flagged),
              "message": f"Exported {len(clean)} answer(s) to {repo}/{file} (commit {oid[:10]})."}
    if log:
        log("training_exported", {k: result[k] for k in ("exported", "file", "sha256", "commit", "rejected_personal")})
    return result


# -- the daily setting (read by the supervisor) ----------------------------------------------------------
def _settings_file(paths) -> Path:
    return paths.rabbit / "settings.json"


def exporting_daily(paths) -> bool:
    try:
        return bool(json.loads(_settings_file(paths).read_text(encoding="utf-8")).get("training_export_daily"))
    except (OSError, ValueError, AttributeError):
        return False


def set_exporting_daily(paths, on: bool) -> None:
    path = _settings_file(paths)
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    settings["training_export_daily"] = on
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=1), encoding="utf-8")
