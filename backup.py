#!/usr/bin/env python3
"""Create verified, local-only ZIP snapshots of this project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

APP_NAME = "NetworkOSBackup"
CONFIG_NAME = "config.json"
ARCHIVE_PREFIX = "network-os-backup-"
MANIFEST_NAME = "backup-manifest.json"
DEFAULT_RETENTION = 30
EXCLUDED_DIRS = {
    ".pytest_cache",
    ".cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "target",
    ".venv",
    "venv",
    "dist",
    "build",
}
EXCLUDED_FILES = {"autonomous/supervisor.lock"}
CHUNK_SIZE = 1024 * 1024


def config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / APP_NAME / CONFIG_NAME


def load_config() -> dict[str, Any]:
    path = config_path()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError("Backup is not initialized; run `python backup.py init` first.") from error
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read backup configuration at {path}: {error}") from error
    if not isinstance(config, dict) or not isinstance(config.get("project_root"), str):
        raise RuntimeError(f"Backup configuration at {path} has an invalid format.")
    return config


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    try:
        temporary_path.write_text(
            json.dumps(config, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    except OSError as error:
        raise RuntimeError(f"Could not save backup configuration at {path}: {error}") from error


def initialize(project_root: Path, backup_root: Path | None) -> None:
    project_root = project_root.expanduser().resolve(strict=True)
    if not project_root.is_dir():
        raise RuntimeError(f"Project root is not a directory: {project_root}")
    if backup_root is None:
        if os.name == "nt":
            backup_root = Path(
                os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
            ) / APP_NAME / "archives"
        else:
            backup_root = Path.home() / ".local" / "state" / APP_NAME / "archives"
    backup_root = backup_root.expanduser().resolve()
    if backup_root == project_root or project_root in backup_root.parents:
        raise RuntimeError(
            "Backup destination must be outside the project tree to prevent recursive backups."
        )
    backup_root.mkdir(parents=True, exist_ok=True)
    config = {
        "version": 1,
        "project_root": str(project_root),
        "backup_root": str(backup_root),
        "retention": DEFAULT_RETENTION,
        "scheduled_task_name": "NetworkOSNightlyBackup",
        "contains_sensitive_files": True,
        "cloud_copy_enabled": False,
    }
    save_config(config)
    print(f"Initialized local backups for: {project_root}")
    print(f"Archive destination: {backup_root}")
    print(f"Retention: {DEFAULT_RETENTION} successful archives")
    print("Archives include private keys and credentials and are not encrypted.")
    print("Cloud copy is disabled.")


def iter_project_files(project_root: Path, backup_root: Path):
    backup_root = backup_root.resolve()
    for current_dir, dir_names, file_names in os.walk(project_root, followlinks=False):
        current_path = Path(current_dir)
        kept_dirs = []
        for name in sorted(dir_names):
            candidate = current_path / name
            if name in EXCLUDED_DIRS or candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            if resolved == backup_root or backup_root in resolved.parents:
                continue
            kept_dirs.append(name)
        dir_names[:] = kept_dirs

        for name in sorted(file_names):
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                continue
            relative_name = path.relative_to(project_root).as_posix()
            if relative_name in EXCLUDED_FILES:
                continue
            resolved = path.resolve()
            if resolved == backup_root or backup_root in resolved.parents:
                continue
            yield path, relative_name


def create_backup(config: dict[str, Any]) -> Path:
    project_root = Path(config["project_root"]).resolve(strict=True)
    backup_root = Path(config["backup_root"]).resolve()
    if not project_root.is_dir():
        raise RuntimeError(f"Configured project root no longer exists: {project_root}")
    backup_root.mkdir(parents=True, exist_ok=True)
    if backup_root == project_root or project_root in backup_root.parents:
        raise RuntimeError("Configured backup destination is inside the project tree.")

    lock_path = backup_root / ".backup.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError(
            f"Another backup may be running (lock exists at {lock_path}); "
            "check for a running backup before removing a stale lock."
        ) from error
    except OSError as error:
        raise RuntimeError(f"Could not create backup lock {lock_path}: {error}") from error

    temporary_path: Path | None = None
    try:
        os.write(lock_fd, f"pid={os.getpid()}\nstarted={time.time()}\n".encode("ascii"))
        os.close(lock_fd)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_path = backup_root / f"{ARCHIVE_PREFIX}{timestamp}.zip"
        with tempfile.NamedTemporaryFile(
            prefix=f".{ARCHIVE_PREFIX}",
            suffix=".tmp",
            dir=backup_root,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)

        manifest_files = []
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for source_path, relative_name in iter_project_files(project_root, backup_root):
                digest = hashlib.sha256()
                byte_count = 0
                with source_path.open("rb") as source, archive.open(relative_name, "w") as target:
                    while True:
                        chunk = source.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        target.write(chunk)
                        digest.update(chunk)
                        byte_count += len(chunk)
                manifest_files.append(
                    {"path": relative_name, "size": byte_count, "sha256": digest.hexdigest()}
                )

            manifest = {
                "format_version": 1,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "project_root": str(project_root),
                "file_count": len(manifest_files),
                "files": manifest_files,
            }
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            )

        with zipfile.ZipFile(temporary_path, mode="r") as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise RuntimeError(f"New archive failed its CRC check at {bad_member!r}.")
            verify_archive(archive)
        os.replace(temporary_path, archive_path)
        temporary_path = None
        prune_archives(backup_root, int(config.get("retention", DEFAULT_RETENTION)))
        return archive_path
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        try:
            os.close(lock_fd)
        except OSError:
            pass
        lock_path.unlink(missing_ok=True)


def verify_archive(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Archive is missing a valid backup manifest.") from error
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
        raise RuntimeError("Backup manifest has an unsupported format.")
    files = manifest.get("files")
    if not isinstance(files, list) or manifest.get("file_count") != len(files):
        raise RuntimeError("Backup manifest file list is invalid.")

    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise RuntimeError("Backup manifest contains an invalid file entry.")
        relative_name = entry.get("path")
        if not isinstance(relative_name, str) or not safe_archive_path(relative_name):
            raise RuntimeError(f"Unsafe archive path in manifest: {relative_name!r}.")
        if relative_name in seen or relative_name == MANIFEST_NAME:
            raise RuntimeError(f"Duplicate or reserved path in manifest: {relative_name!r}.")
        seen.add(relative_name)
        try:
            content = archive.read(relative_name)
        except (KeyError, OSError, zipfile.BadZipFile) as error:
            raise RuntimeError(f"Archive is missing {relative_name!r}.") from error
        if len(content) != entry.get("size"):
            raise RuntimeError(f"Size verification failed for {relative_name!r}.")
        if hashlib.sha256(content).hexdigest() != entry.get("sha256"):
            raise RuntimeError(f"SHA-256 verification failed for {relative_name!r}.")
    return manifest


def safe_archive_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and "\\" not in name
        and ":" not in name
        and not path.is_absolute()
        and all(part not in ("", ".", "..") for part in path.parts)
    )


def latest_archive(backup_root: Path) -> Path:
    archives = sorted(
        backup_root.glob(f"{ARCHIVE_PREFIX}*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not archives:
        raise RuntimeError(f"No local backup archives found in {backup_root}.")
    return archives[0]


def prune_archives(backup_root: Path, retention: int) -> None:
    if retention < 1:
        raise RuntimeError("Backup retention must be at least one archive.")
    archives = sorted(
        backup_root.glob(f"{ARCHIVE_PREFIX}*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for archive in archives[retention:]:
        archive.unlink()


def restore_test(config: dict[str, Any]) -> tuple[Path, int]:
    backup_root = Path(config["backup_root"])
    archive_path = latest_archive(backup_root)
    restored_files = 0
    with zipfile.ZipFile(archive_path, mode="r") as archive:
        manifest = verify_archive(archive)
        with tempfile.TemporaryDirectory(prefix="network-os-restore-test-") as temp_dir:
            restore_root = Path(temp_dir)
            for entry in manifest["files"]:
                relative_name = entry["path"]
                destination = restore_root.joinpath(*PurePosixPath(relative_name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(relative_name))
                restored_files += 1
                if destination.stat().st_size != entry["size"]:
                    raise RuntimeError(f"Restore size verification failed for {relative_name!r}.")
                digest = hashlib.sha256(destination.read_bytes()).hexdigest()
                if digest != entry["sha256"]:
                    raise RuntimeError(f"Restore SHA-256 verification failed for {relative_name!r}.")
    return archive_path, restored_files


def command_run() -> int:
    archive = create_backup(load_config())
    print(f"Backup verified: {archive}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="initialize local backup configuration")
    init_parser.add_argument("--project-root", type=Path, default=Path.cwd())
    init_parser.add_argument("--backup-root", type=Path, default=None)
    subparsers.add_parser("run", help="create and verify a local backup archive")
    subparsers.add_parser("list", help="verify and list local backup archives")
    args = parser.parse_args()

    try:
        if args.command == "init":
            initialize(args.project_root, args.backup_root)
            return 0
        config = load_config()
        if args.command == "run":
            return command_run()
        if args.command == "list":
            backup_root = Path(config["backup_root"])
            archives = sorted(
                backup_root.glob(f"{ARCHIVE_PREFIX}*.zip"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not archives:
                print(f"No local backup archives found in {backup_root}.")
                return 1
            for path in archives:
                with zipfile.ZipFile(path, mode="r") as archive:
                    manifest = verify_archive(archive)
                print(f"{path.name}: {manifest['file_count']} files; manifest verified")
            return 0
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Backup error: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
