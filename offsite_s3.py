#!/usr/bin/env python3
"""
offsite_s3.py — copies backup.py's encrypted backups to Amazon S3, so a
dead disk or a lost PC doesn't take every copy with it.

WHAT GOES UP
-----------------
Only what backup.py already encrypted: each <vault-id>.dvault (AES-256-GCM;
file names and contents are inside the ciphertext) and index.jsonl (vault
ids, times, sizes -- no file names). The passphrase never leaves this PC,
so AWS stores data it cannot read.

HOW
--------
Through the AWS CLI (`aws s3api`), already installed -- no extra Python
dependency. Each upload:
- sends a SHA-256 checksum that S3 verifies on arrival,
- uses If-None-Match: * so an existing backup is never overwritten,
- is then checked with head-object: S3's stored SHA-256 must equal ours.
A backup only counts as off-site after that check, and is recorded in
<dest>/offsite_s3.jsonl. Anything not yet confirmed -- no internet, AWS
down, PC asleep -- is simply retried on the next sync.

The AWS side (see aws_backup_setup.ps1) is designed so this PC can add
backups but not delete or replace them: its IAM user has no delete
permission and the bucket is versioned, so ransomware or a mistake on
this PC can't wipe the off-site copies. S3 itself expires them by
lifecycle rule. Nothing here needs, stores or prints the AWS account ID.

Usage
-----
    python offsite_s3.py configure --bucket NAME --region us-east-2 --profile network-os-backup
    python offsite_s3.py sync                  # upload + verify everything not yet off-site
    python offsite_s3.py status
    python offsite_s3.py pull all-missing      # disaster recovery: download into the local vault

backup.py runs `sync` after each nightly backup once configured.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

DEFAULT_DEST = Path.home() / "network-os-backups"
CONFIG_NAME = "offsite_s3.json"
LEDGER_NAME = "offsite_s3.jsonl"
AWS_FALLBACK = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Amazon" / "AWSCLIV2" / "aws.exe"


class AwsError(RuntimeError):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def _aws_exe() -> str:
    found = shutil.which("aws")
    if found:
        return found
    if AWS_FALLBACK.exists():
        return str(AWS_FALLBACK)
    raise AwsError("AWS CLI not found (install AWS CLI v2)")


def cli_runner(args: list[str]) -> dict:
    """Runs `aws <args> --output json`; returns parsed JSON or raises AwsError."""
    proc = subprocess.run([_aws_exe(), *args, "--output", "json"], capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        err = proc.stderr.strip()
        code = None
        if "(" in err and ")" in err:
            code = err[err.index("(") + 1:err.index(")")]
        raise AwsError(err or f"aws exited {proc.returncode}", code)
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def sha256_b64(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode()


class S3Offsite:
    def __init__(self, dest: Path = DEFAULT_DEST, config: dict | None = None,
                 runner: Callable[[list[str]], dict] = cli_runner):
        self.dest = Path(dest)
        self.vault_dir = self.dest / "vault"
        self.config = config if config is not None else self.load_config(self.dest)
        if not self.config:
            raise LookupError(f"off-site copy not configured: run `offsite_s3.py configure` ({self.dest / CONFIG_NAME})")
        self.run = runner

    # ---- config and ledger ----
    @staticmethod
    def load_config(dest: Path) -> dict | None:
        path = Path(dest) / CONFIG_NAME
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    @staticmethod
    def save_config(dest: Path, bucket: str, region: str, profile: str | None, prefix: str) -> Path:
        prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        path = Path(dest) / CONFIG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"bucket": bucket, "region": region, "profile": profile,
                                    "prefix": prefix}, indent=2), encoding="utf-8")
        return path

    def confirmed(self) -> dict[str, dict]:
        path = self.dest / LEDGER_NAME
        if not path.exists():
            return {}
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return {r["vault_id"]: r for r in rows if r["bucket"] == self.config["bucket"]}

    def _record(self, row: dict) -> None:
        with (self.dest / LEDGER_NAME).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")

    # ---- aws calls ----
    def _common(self) -> list[str]:
        args = ["--bucket", self.config["bucket"], "--region", self.config["region"]]
        if self.config.get("profile"):
            args += ["--profile", self.config["profile"]]
        return args

    def key_for(self, name: str) -> str:
        return f"{self.config['prefix']}{name}"

    def _head_checksum(self, key: str) -> str | None:
        try:
            head = self.run(["s3api", "head-object", *self._common(), "--key", key, "--checksum-mode", "ENABLED"])
        except AwsError as e:
            if e.code in ("404", "NoSuchKey", "NotFound") or "Not Found" in str(e):
                return None
            raise
        return head.get("ChecksumSHA256")

    def upload_verified(self, path: Path, key: str, never_overwrite: bool = True) -> str:
        """Uploads with an S3-checked SHA-256 and confirms the stored checksum.
        An existing object is kept (not replaced) and just verified."""
        local = sha256_b64(path)
        args = ["s3api", "put-object", *self._common(), "--key", key, "--body", str(path),
                "--checksum-algorithm", "SHA256", "--checksum-sha256", local]
        if never_overwrite:
            args += ["--if-none-match", "*"]
        try:
            self.run(args)
        except AwsError as e:
            if not (never_overwrite and (e.code == "PreconditionFailed" or "PreconditionFailed" in str(e))):
                raise
        remote = self._head_checksum(key)
        if remote != local:
            raise AwsError(f"checksum mismatch for s3://{self.config['bucket']}/{key}: "
                           f"local {local}, S3 {remote}")
        return local

    # ---- operations ----
    def pending(self) -> list[str]:
        done = self.confirmed()
        local = sorted(p.stem for p in self.vault_dir.glob("*.dvault")) if self.vault_dir.exists() else []
        return [vid for vid in local if vid not in done]

    def sync(self) -> dict:
        uploaded, failed = [], {}
        for vid in self.pending():
            key = self.key_for(f"vault/{vid}.dvault")
            try:
                checksum = self.upload_verified(self.vault_dir / f"{vid}.dvault", key)
            except AwsError as e:
                failed[vid] = str(e)[:300]
                continue
            self._record({"vault_id": vid, "bucket": self.config["bucket"], "key": key,
                          "sha256_b64": checksum, "confirmed_at": time.time()})
            uploaded.append(vid)
        index = self.dest / "index.jsonl"
        index_ok = None
        if index.exists() and not failed:
            try:
                self.upload_verified(index, self.key_for("index.jsonl"), never_overwrite=False)
                index_ok = True
            except AwsError as e:
                index_ok, failed["index.jsonl"] = False, str(e)[:300]
        return {"bucket": self.config["bucket"], "uploaded": uploaded, "failed": failed,
                "index_uploaded": index_ok, "still_pending": len(self.pending())}

    def pull(self, vault_ids: list[str] | str = "all-missing") -> list[str]:
        """Downloads backups from S3 into the local vault (disaster recovery)."""
        if vault_ids == "all-missing":
            listing = self.run(["s3api", "list-objects-v2", *self._common(),
                                "--prefix", self.key_for("vault/")]).get("Contents", [])
            remote = [Path(o["Key"]).stem for o in listing if o["Key"].endswith(".dvault")]
            vault_ids = [v for v in remote if not (self.vault_dir / f"{v}.dvault").exists()]
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        got = []
        for vid in vault_ids:
            final = self.vault_dir / f"{vid}.dvault"
            if final.exists():
                continue
            tmp = final.with_suffix(".download")
            key = self.key_for(f"vault/{vid}.dvault")
            head = self.run(["s3api", "get-object", *self._common(), "--key", key,
                             "--checksum-mode", "ENABLED", str(tmp)])
            expected = head.get("ChecksumSHA256")
            if expected and sha256_b64(tmp) != expected:
                tmp.unlink(missing_ok=True)
                raise AwsError(f"downloaded {key} failed its checksum")
            os.replace(tmp, final)
            got.append(vid)
        return got


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Off-site copy of backup.py's encrypted backups in Amazon S3.")
    p.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"backup folder (default: {DEFAULT_DEST})")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("configure")
    c.add_argument("--bucket", required=True)
    c.add_argument("--region", required=True)
    c.add_argument("--profile", help="AWS CLI profile holding the backup user's keys")
    c.add_argument("--prefix", default="network-os/")
    sub.add_parser("sync")
    sub.add_parser("status")
    pl = sub.add_parser("pull")
    pl.add_argument("vault_ids", nargs="+", help="vault ids, or 'all-missing'")
    args = p.parse_args(argv)

    if args.command == "configure":
        path = S3Offsite.save_config(args.dest, args.bucket, args.region, args.profile, args.prefix)
        print(f"saved {path}")
        return 0
    try:
        off = S3Offsite(args.dest)
    except LookupError as e:
        p.error(str(e))
    if args.command == "status":
        print(json.dumps({"config": off.config, "confirmed_offsite": len(off.confirmed()),
                          "pending": off.pending()}, indent=2))
        return 0
    if args.command == "sync":
        report = off.sync()
        print(json.dumps(report, indent=2))
        return 1 if report["failed"] else 0
    ids = "all-missing" if args.vault_ids == ["all-missing"] else args.vault_ids
    print(json.dumps({"downloaded": off.pull(ids)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
