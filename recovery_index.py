#!/usr/bin/env python3
"""Read-only local inventory for finding files across explicitly selected roots."""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

DEFAULT_INDEX = Path.home() / ".network-os" / "recovery-index.sqlite3"
CHUNK_BYTES = 1024 * 1024
EXCLUDED_DIRS = {
    ".ssh", ".aws", ".azure", "keys", "secrets",
    "__pycache__", "node_modules", ".venv", "venv",
}
EXCLUDED_FILES = {
    ".env", "credentials", "credentials.json", "secrets.json",
    "id_rsa", "id_ed25519",
}
EXCLUDED_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".ed25519", ".dpapi",
}


def _connect(database: Path) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            scan_root TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            indexed_at REAL NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS files_sha256_idx ON files(sha256)"
    )
    return connection


def _excluded_file(path: Path) -> bool:
    name = path.name.casefold()
    if name in EXCLUDED_FILES or name.startswith(".env."):
        return True
    if path.suffix.casefold() in EXCLUDED_SUFFIXES:
        return True
    return any(part.casefold() in EXCLUDED_DIRS for part in path.parts)


def _hash_file(path: Path) -> tuple[str, os.stat_result]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError("file changed while it was being indexed")
    return digest.hexdigest(), after


def scan_roots(roots: list[Path], database: Path = DEFAULT_INDEX) -> dict:
    """Hash regular files below roots without modifying or following symlinks."""
    if not roots:
        raise ValueError("select at least one directory to scan")

    normalized_roots: list[Path] = []
    for root in roots:
        resolved = root.expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise NotADirectoryError(f"scan root is not a directory: {resolved}")
        if resolved not in normalized_roots:
            normalized_roots.append(resolved)

    indexed = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    index_artifacts = {
        Path(str(database.expanduser().resolve(strict=False)) + suffix)
        for suffix in ("", "-wal", "-shm")
    }
    with closing(_connect(database)) as connection, connection:
        for root in normalized_roots:
            def on_walk_error(error: OSError) -> None:
                errors.append({"path": str(error.filename or root), "error": str(error)})

            for current, directories, filenames in os.walk(
                root, followlinks=False, onerror=on_walk_error
            ):
                current_path = Path(current)
                allowed_directories = []
                for name in directories:
                    directory = current_path / name
                    if name.casefold() in EXCLUDED_DIRS or directory.is_symlink():
                        skipped += 1
                    else:
                        allowed_directories.append(name)
                directories[:] = allowed_directories
                for filename in filenames:
                    path = current_path / filename
                    if path.resolve(strict=False) in index_artifacts:
                        skipped += 1
                        continue
                    if path.is_symlink() or _excluded_file(path):
                        skipped += 1
                        continue
                    try:
                        digest, stat = _hash_file(path)
                        connection.execute(
                            """
                            INSERT INTO files(path, scan_root, size, mtime_ns, sha256, indexed_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(path) DO UPDATE SET
                                scan_root = excluded.scan_root,
                                size = excluded.size,
                                mtime_ns = excluded.mtime_ns,
                                sha256 = excluded.sha256,
                                indexed_at = excluded.indexed_at
                            """,
                            (
                                str(path),
                                str(root),
                                stat.st_size,
                                stat.st_mtime_ns,
                                digest,
                                time.time(),
                            ),
                        )
                        indexed += 1
                    except OSError as error:
                        errors.append({"path": str(path), "error": str(error)})
    return {
        "database": str(database),
        "roots": [str(root) for root in normalized_roots],
        "indexed": indexed,
        "skipped_sensitive_or_linked": skipped,
        "errors": errors,
        "complete": not errors,
    }


def search(query: str, database: Path = DEFAULT_INDEX, limit: int = 100) -> list[dict]:
    if not query.strip():
        raise ValueError("search query must not be empty")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if not database.is_file():
        raise FileNotFoundError(f"recovery index does not exist: {database}")

    needle = query.casefold()
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT path, scan_root, size, mtime_ns, sha256
            FROM files
            ORDER BY path
            """
        )
        results = []
        for row in rows:
            if needle in row["path"].casefold() or row["sha256"].startswith(needle):
                result = dict(row)
                result["path_exists"] = Path(row["path"]).is_file()
                results.append(result)
                if len(results) == limit:
                    break
    return results


def duplicates(database: Path = DEFAULT_INDEX, limit: int = 100) -> list[dict]:
    if not database.is_file():
        raise FileNotFoundError(f"recovery index does not exist: {database}")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        groups = connection.execute(
            """
            SELECT sha256, size, COUNT(*) AS copies
            FROM files
            GROUP BY sha256, size
            HAVING COUNT(*) > 1
            ORDER BY copies DESC, sha256
            LIMIT ?
            """,
            (limit,),
        )
        result = []
        for group in groups:
            paths = connection.execute(
                "SELECT path FROM files WHERE sha256 = ? ORDER BY path",
                (group["sha256"],),
            )
            result.append(
                {
                    "sha256": group["sha256"],
                    "size": group["size"],
                    "copies": group["copies"],
                    "paths": [row["path"] for row in paths],
                }
            )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_INDEX)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan", help="index explicitly selected local directories")
    scan.add_argument("roots", nargs="+", type=Path)
    find = commands.add_parser("search", help="search indexed paths or SHA-256 prefixes")
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=100)
    dupes = commands.add_parser("duplicates", help="find identical files by SHA-256")
    dupes.add_argument("--limit", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "scan":
            result = scan_roots(args.roots, args.db)
            print(json.dumps(result, indent=2))
            return 0 if result["complete"] else 1
        if args.command == "search":
            result = search(args.query, args.db, args.limit)
        else:
            result = duplicates(args.db, args.limit)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"recovery-index: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
