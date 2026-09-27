"""
Adds the project root to sys.path so tests can `import digital_dna`,
`import network_os`, etc. directly -- this project is a flat
collection of scripts, not an installable package.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _isolate_real_backups(tmp_path_factory, monkeypatch):
    """Tests never see the user's real ~/network-os-backups or backup passphrase."""
    import backup
    monkeypatch.setattr(backup, "DEFAULT_DEST", tmp_path_factory.mktemp("no-real-backups") / "none")
    monkeypatch.setattr(backup, "DPAPI_FILE", tmp_path_factory.mktemp("no-real-key") / "none.dpapi")
    monkeypatch.delenv(backup.PASSPHRASE_ENV, raising=False)
