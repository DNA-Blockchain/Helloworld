#!/usr/bin/env python3
# ============================================================================
#  SPDX-License-Identifier: UPL-1.0
#
#  Copyright (c) 2026 Chase Allen Ringquist
#
#  This file is part of an operating system, software, and network Work
#  conceived and authored by Chase Allen Ringquist. The Author retains
#  copyright and authorship. Use of this file is licensed as follows.
#
#  ----------------------------------------------------------------------------
#  The Universal Permissive License (UPL), Version 1.0
#
#  Subject to the condition set forth below, permission is hereby granted to
#  any person obtaining a copy of this software, associated documentation
#  and/or data (collectively the "Software"), free of charge and under any
#  and all copyright rights in the Software, and any and all patent rights
#  owned or freely licensable by each licensor hereunder covering either
#  (i) the unmodified Software as contributed to or provided by such
#  licensor, or (ii) the Larger Works (as defined below), to deal in both
#
#  (a) the Software, and
#
#  (b) any piece of software and/or hardware listed in the lrgrwrks.txt file
#  if one is included with the Software (each a "Larger Work" to which the
#  Software is contributed by such licensors),
#
#  without restriction, including without limitation the rights to copy,
#  create derivative works of, display, perform, and distribute the Software
#  and make, use, sell, offer for sale, import, export, have made, and have
#  sold the Software and the Larger Work(s), and to sublicense the foregoing
#  rights on either these or other terms.
#
#  This license is subject to the following condition:
#
#  The above copyright notice and either this complete permission notice or
#  at a minimum a reference to the UPL must be included in all copies or
#  substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#  ----------------------------------------------------------------------------
#
#  Do not remove or alter this notice or any record of origin.
#  See NOTICE.md in the project root for authorship and ownership terms.
#
#  Contact:  ringquistchase@gmail.com  |  (918) 845-0940
#            Bixby, OK, United States
# ============================================================================

"""
backup.py — nightly encrypted backups of this project's source and state.

WHAT ONE BACKUP IS
-----------------------
One snapshot of the project source, OS, engineering logs, and runtime state,
encrypted as a single encrypted_data_vault.py object (AES-256-GCM,
scrypt-derived key) and verified by decrypting it end to end before it counts:

- source, schemas, tests, documentation, configuration, and Git history
- runtime state, databases, OS sources, and saved guest disk image
- engineering, supervisor, and audit logs
- every SQLite database among them (live_store.db, the research catalog
  and sessions) copied with SQLite's online-backup API, so a database
  that is being written during the backup is still copied consistently

Private key directories and common private-key/credential file patterns are
excluded. Build caches and dependencies are excluded; the OS persistent QEMU
disk image is included. A BACKUP_MANIFEST.json inside the encrypted zip lists
every included file with its size and SHA-256.

WHERE THINGS GO
--------------------
    <dest>/vault/<vault-id>.dvault     encrypted backups
    <dest>/index.jsonl                 vault id, time, size, file count -- no file names
Default <dest> is ~/network-os-backups: outside the repo, so a git clean or
a deleted checkout doesn't take the backups with it. It's still the same
disk; an off-site copy is a separate step.

THE PASSPHRASE
-------------------
`python backup.py init` asks for it twice and stores it protected with
Windows DPAPI: only your Windows account on this PC can unprotect it, so
the nightly task can run without a prompt. KEEP YOUR OWN COPY (password
manager): if this PC or its Windows profile is lost, the DPAPI copy goes
with it, and without the passphrase no backup can ever be decrypted.
Elsewhere (or to override), set NETWORK_OS_BACKUP_PASSPHRASE.

While a backup is built, the unencrypted zip exists briefly in
<dest>/.staging and is deleted as soon as it is encrypted (or on error).

Usage
-----
    python backup.py init                   # once: set the passphrase
    python backup.py run --apply-retention --audit system_audit.jsonl
    python backup.py list
    python backup.py verify [VAULT_ID|all]
    python backup.py restore latest --to C:\\restore-test
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import getpass
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from encrypted_data_vault import EncryptedDataVault

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DEST = Path.home() / "network-os-backups"
PASSPHRASE_ENV = "NETWORK_OS_BACKUP_PASSPHRASE"
DPAPI_FILE = Path(os.environ.get("APPDATA", Path.home())) / "network-os" / "backup_passphrase.dpapi"
KEEP_DAYS = 30
KEEP_MIN = 7

EXCLUDE_DIRS = {
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "__pycache__", ".staging",
    "build", "dist", "node_modules", "venv", ".venv", "keys", "secrets",
}
EXCLUDE_FILES = [
    "*.pem", "*.key", "*.p12", "*.pfx", "*.ed25519", "*.tmp", "*.lock",
    "*.stop", "*-wal", "*-shm", "*-journal", ".env", ".env.*",
]
SQLITE_MAGIC = b"SQLite format 3\x00"
PRESERVED_GUEST_DISK = Path("os/target/network-os-persistent.img")


# ---- passphrase (Windows DPAPI, or the environment) ----
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in, blob_out = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))  # UI_FORBIDDEN
    if not ok:
        raise OSError(f"DPAPI {'protect' if protect else 'unprotect'} failed (error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def save_passphrase(passphrase: str, path: Path | None = None) -> Path:
    path = Path(path or DPAPI_FILE)
    if len(passphrase) < 12:
        raise ValueError("passphrase must be at least 12 characters")
    if os.name != "nt":
        raise OSError(f"DPAPI is Windows-only; set {PASSPHRASE_ENV} instead")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(_dpapi(passphrase.encode("utf-8"), protect=True))
    os.replace(tmp, path)
    return path


def load_passphrase(path: Path | None = None) -> str:
    path = Path(path or DPAPI_FILE)
    env = os.environ.get(PASSPHRASE_ENV)
    if env:
        return env
    if os.name == "nt" and path.exists():
        return _dpapi(path.read_bytes(), protect=False).decode("utf-8")
    raise LookupError(f"no backup passphrase: run `python backup.py init` or set {PASSPHRASE_ENV}")


# ---- collecting ----
def _excluded(rel: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]):
        return True
    if "target" in rel.parts[:-1] and rel != PRESERVED_GUEST_DISK:
        return True
    if rel.name.lower() in {"id_rsa", "id_ed25519", "credentials.json"}:
        return True
    return any(fnmatch.fnmatch(rel.name, pat) for pat in EXCLUDE_FILES)


def collect(root: Path = PROJECT_DIR) -> list[Path]:
    """Return a complete source/state snapshot, excluding secrets and caches."""
    root = Path(root)
    found: list[Path] = []
    for directory, subdirectories, filenames in os.walk(root, followlinks=False):
        current = Path(directory).relative_to(root)
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in EXCLUDE_DIRS
            and not (name == "target" and current != Path("os"))
            and current != Path("os/target")
        ]
        for filename in filenames:
            path = Path(directory) / filename
            relative = path.relative_to(root)
            if path.is_symlink() or _excluded(relative):
                continue
            found.append(relative)
    return sorted(found)


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def _sqlite_copy(src: Path, dst: Path) -> None:
    source = sqlite3.connect(src, timeout=10)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def build_bundle(root: Path, zip_path: Path) -> dict:
    """Writes the plaintext zip; returns its manifest."""
    files = []
    with tempfile.TemporaryDirectory(dir=zip_path.parent) as scratch, \
            zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in collect(root):
            # snapshot first, then hash and zip that same snapshot, so a file
            # rewritten mid-backup can't make the manifest disagree with the zip
            src, staged = root / rel, Path(scratch) / "current"
            try:
                if _is_sqlite(src):
                    _sqlite_copy(src, staged)
                    method = "sqlite-backup"
                else:
                    shutil.copyfile(src, staged)
                    method = "copy"
            except FileNotFoundError:   # a node rotated it away mid-backup
                continue
            zf.write(staged, rel.as_posix())
            files.append({"path": rel.as_posix(), "bytes": staged.stat().st_size,
                          "sha256": _sha256(staged), "method": method})
            staged.unlink()
        manifest = {"schema_version": 1, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "project_root": str(root), "file_count": len(files), "files": files,
                    "excluded": {"dirs": sorted(EXCLUDE_DIRS), "files": EXCLUDE_FILES}}
        zf.writestr("BACKUP_MANIFEST.json", json.dumps(manifest, indent=2))
    return manifest


# ---- the backup set ----
class BackupSet:
    def __init__(self, dest: Path = DEFAULT_DEST):
        self.dest = Path(dest)
        self.vault = EncryptedDataVault(self.dest / "vault")
        self.index_path = self.dest / "index.jsonl"

    def entries(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        with self.index_path.open(encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        present = set(self.vault.list_ids())
        return [r for r in rows if r["vault_id"] in present]

    def _write_index(self, rows: list[dict]) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, sort_keys=True) + "\n" for r in rows)
        os.replace(tmp, self.index_path)

    def resolve(self, vault_id: str) -> str:
        if vault_id == "latest":
            rows = self.entries()
            if not rows:
                raise LookupError("no backups yet")
            return rows[-1]["vault_id"]
        return vault_id

    def run(self, passphrase: str, root: Path = PROJECT_DIR) -> dict:
        staging = self.dest / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        zip_path = staging / f"network-os-backup-{stamp}.zip"
        started = time.time()
        try:
            manifest = build_bundle(root, zip_path)
            stored = self.vault.store_file(zip_path, passphrase=passphrase, classification="private",
                                           source_label="network-os nightly backup")
        finally:
            zip_path.unlink(missing_ok=True)
        self.vault.inspect(stored["vault_id"], passphrase=passphrase)   # full decrypt + hash check
        entry = {"vault_id": stored["vault_id"], "created_at": manifest["created_at"],
                 "file_count": manifest["file_count"], "bundle_bytes": stored["content_bytes"],
                 "encrypted_bytes": (self.vault.directory / f"{stored['vault_id']}.dvault").stat().st_size,
                 "duration_s": round(time.time() - started, 2), "verified": True}
        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def prune(self, keep_days: int = KEEP_DAYS, keep_min: int = KEEP_MIN, now: dt.datetime | None = None) -> list[str]:
        """Deletes backups older than keep_days, always keeping the newest keep_min."""
        now = now or dt.datetime.now(dt.timezone.utc)
        rows = self.entries()
        cutoff = now - dt.timedelta(days=keep_days)
        doomed = [r for r in rows[:max(0, len(rows) - keep_min)]
                  if dt.datetime.fromisoformat(r["created_at"]) < cutoff]
        for r in doomed:
            (self.vault.directory / f"{r['vault_id']}.dvault").unlink(missing_ok=True)
        self._write_index([r for r in rows if r not in doomed])
        return [r["vault_id"] for r in doomed]

    def verify(self, vault_id: str, passphrase: str) -> dict:
        return self.vault.inspect(self.resolve(vault_id), passphrase=passphrase)

    def restore(self, vault_id: str, target: Path, passphrase: str) -> dict:
        """Decrypts and unpacks into `target`, which must not exist or be empty --
        never over live files. Every file is checked against the manifest."""
        vault_id = self.resolve(vault_id)
        target = Path(target)
        if target.exists() and any(target.iterdir()):
            raise FileExistsError(f"restore target must be empty: {target}")
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent) as scratch:
            zip_path = Path(scratch) / "bundle.zip"
            self.vault.restore_file(vault_id, zip_path, passphrase=passphrase)
            with zipfile.ZipFile(zip_path) as zf:
                manifest = json.loads(zf.read("BACKUP_MANIFEST.json"))
                root = target.resolve()
                for item in manifest["files"]:
                    out = (target / item["path"]).resolve()
                    if root not in out.parents:
                        raise ValueError(f"unsafe path in backup: {item['path']}")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(item["path"]) as src, out.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if _sha256(out) != item["sha256"]:
                        raise ValueError(f"restored file failed its hash check: {item['path']}")
        return {"vault_id": vault_id, "restored_to": str(target), "file_count": len(manifest["files"]),
                "backup_created_at": manifest["created_at"]}


def offsite_sync(dest: Path) -> dict | None:
    """Copies new backups to S3 if offsite_s3.py is configured for `dest`;
    None if it isn't. Never raises: a failed upload stays pending for next time."""
    import offsite_s3
    if not offsite_s3.S3Offsite.load_config(dest):
        return None
    try:
        report = offsite_s3.S3Offsite(dest, runner=offsite_s3.cli_runner).sync()
    except Exception as e:
        report = {"error": str(e)[:300]}
    # backup_health.py reads this to alert on failed syncs
    (Path(dest) / "offsite_last_sync.json").write_text(json.dumps({**report, "at": time.time()}), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Encrypted backups of network-os-project's state.")
    p.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"backup folder (default: {DEFAULT_DEST})")
    p.add_argument("--root", type=Path, default=PROJECT_DIR, help="project folder to back up (default: this file's folder)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="set the passphrase (stored with Windows DPAPI)")
    run = sub.add_parser("run", help="make, encrypt and verify one backup, then prune old ones")
    run.add_argument("--apply-retention", action="store_true",
                     help="run retention.py on live_store.db first, so expired rows aren't backed up")
    run.add_argument("--audit", help="log the backup (id, counts, sizes) to this audit_trail.py file")
    run.add_argument("--keep-days", type=int, default=KEEP_DAYS)
    run.add_argument("--keep-min", type=int, default=KEEP_MIN)
    sub.add_parser("list")
    v = sub.add_parser("verify")
    v.add_argument("vault_id", nargs="?", default="all")
    r = sub.add_parser("restore")
    r.add_argument("vault_id", help="a vault id, or 'latest'")
    r.add_argument("--to", type=Path, required=True, help="empty or new folder to restore into")
    args = p.parse_args(argv)
    bs = BackupSet(args.dest)

    if args.command == "init":
        first = getpass.getpass("Backup passphrase (12+ characters): ")
        if first != getpass.getpass("Confirm: "):
            p.error("passphrases do not match")
        path = save_passphrase(first)
        print(f"Saved (DPAPI-protected, this Windows account only): {path}")
        print("Keep your own copy of this passphrase. Without it, no backup can be decrypted.")
        return 0
    if args.command == "list":
        for e in bs.entries():
            print(f"{e['vault_id']}  {e['created_at']}  {e['file_count']:>4} files  "
                  f"{e['encrypted_bytes'] / 1024:>9.1f} KB  verified={e['verified']}")
        return 0

    try:
        passphrase = load_passphrase()
    except (LookupError, OSError) as e:
        p.error(str(e))

    if args.command == "run":
        if args.apply_retention and (args.root / "live_store.db").exists():
            import retention
            retention.apply(str(args.root / "live_store.db"), retention.load_policy(), audit_path=args.audit)
        entry = bs.run(passphrase, root=args.root)
        offsite = offsite_sync(bs.dest)   # before pruning, so nothing is pruned before it's off-site
        pruned = bs.prune(args.keep_days, args.keep_min)
        offsite_summary = None if offsite is None else {
            "uploaded": len(offsite.get("uploaded", [])), "failed": len(offsite.get("failed", {})),
            "still_pending": offsite.get("still_pending")}
        if args.audit:
            from audit_trail import AuditTrail
            AuditTrail(args.audit).log(module="backup", action="backup_created", node_id="backup",
                                       details={**{k: entry[k] for k in ("vault_id", "file_count",
                                                                          "bundle_bytes", "verified")},
                                                "pruned": pruned, "offsite": offsite_summary})
        try:   # weekly test restore when due, health checks, desktop alert if anything's wrong
            import backup_health
            health = backup_health.run_scheduled(bs.dest, passphrase, audit_path=args.audit)
        except Exception as e:
            health = {"error": str(e)[:300]}
        print(json.dumps({**entry, "pruned": pruned, "offsite": offsite, "health": health}, indent=2))
        return 0
    if args.command == "verify":
        ids = [e["vault_id"] for e in bs.entries()] if args.vault_id == "all" else [args.vault_id]
        bad = 0
        for vid in ids:
            try:
                bs.verify(vid, passphrase)
                print(f"OK      {vid}")
            except Exception as e:
                bad += 1
                print(f"FAILED  {vid}: {e}")
        return 1 if bad else 0
    print(json.dumps(bs.restore(args.vault_id, args.to, passphrase), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
