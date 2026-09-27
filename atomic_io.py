#!/usr/bin/env python3
"""
atomic_io.py — os.replace that tolerates Windows' brief file locks.

The project saves state by writing a .tmp file and os.replace()-ing it
over the real one (atomic: a crash never leaves a half-written file). On
Windows that replace fails with PermissionError ("Access is denied")
while any other process has the target open for a moment -- an antivirus
scan, a backup tool, or the supervisor reading a status file. Seen in the
first unattended run: 3 failures in 3.4 hours. A short retry covers it.
"""

from __future__ import annotations

import os
import time


def replace_with_retry(src: str, dst: str, attempts: int = 12, first_delay: float = 0.05) -> None:
    """os.replace(src, dst), retrying PermissionError with a doubling delay
    (about 3 seconds in total by default) before giving up and raising."""
    delay = first_delay
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)
