#!/usr/bin/env python3
"""Run a non-destructive restore test and check backup/task freshness."""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import backup

MAX_BACKUP_AGE_SECONDS = 26 * 60 * 60


def test_restore() -> int:
    config = backup.load_config()
    archive_path, restored_files = backup.restore_test(config)
    print(
        f"Restore test passed: verified {restored_files} files from "
        f"{archive_path.name} in a temporary directory."
    )
    return 0


def check_backup_freshness(config: dict) -> list[str]:
    backup_root = Path(config["backup_root"])
    try:
        archive_path = backup.latest_archive(backup_root)
        with zipfile.ZipFile(archive_path, mode="r") as archive_file:
            manifest = backup.verify_archive(archive_file)
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        return [f"Backup archive check failed: {error}"]

    age = datetime.now(timezone.utc).timestamp() - archive_path.stat().st_mtime
    if age > MAX_BACKUP_AGE_SECONDS:
        return [f"Latest verified backup is stale ({age / 3600:.1f} hours old)."]
    if manifest.get("file_count", 0) < 1:
        return ["Latest backup contains no project files."]
    return []


def check_scheduled_task(config: dict) -> list[str]:
    if sys.platform != "win32":
        return ["Scheduled-task status check is supported only on Windows."]
    task_name = str(config.get("scheduled_task_name", "NetworkOSNightlyBackup"))
    result = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", task_name, "/FO", "LIST", "/V"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "task was not found"
        return [f"Scheduled task {task_name!r} is unavailable: {detail}"]

    fields = {}
    for line in result.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip()
    last_result = fields.get("last result", "")
    if last_result and last_result not in ("0", "0x0"):
        return [f"Scheduled task last returned {last_result}."]
    next_run = fields.get("next run time", "")
    if not next_run or next_run.lower() in ("n/a", "never"):
        return ["Scheduled task has no future run time."]
    return []


def check() -> int:
    try:
        config = backup.load_config()
    except RuntimeError as error:
        print(f"Alert: {error}")
        return 1
    alerts = check_backup_freshness(config)
    if sys.platform == "win32":
        alerts.extend(check_scheduled_task(config))
    if alerts:
        for alert in alerts:
            print(f"Alert: {alert}")
        return 1
    print("No alerts")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("test-restore", "check"))
    args = parser.parse_args()
    try:
        if args.command == "test-restore":
            return test_restore()
        return check()
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Backup health error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
