"""One process at a time on the twin's files: the server and the owner's commands share tasks.json and
the ledger, so each change re-reads the file under an exclusive lock file and writes it back."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

STALE_AFTER = 30.0                   # a lock older than this was left by a process that died


@contextmanager
def locked(path: Path, timeout: float = 10.0):
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > STALE_AFTER:
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"{path.name} is locked by another TwinOS process") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)
