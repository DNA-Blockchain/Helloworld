"""One switch for every confirmation prompt and approval gate.

RABBIT_AUTO_APPROVE=1 turns it on (the toolkit launcher sets it). Unset or 0 keeps each script's own
default, so tests and one-off runs behave as before. Authentication, pinned peers and tokens are not
approvals and are never skipped by this switch.
"""
import os


def enabled() -> bool:
    return os.environ.get("RABBIT_AUTO_APPROVE", "").strip().lower() in ("1", "true", "yes", "on")
