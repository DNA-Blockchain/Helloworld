"""
Adds the project root to sys.path so tests can `import digital_dna`,
`import network_os`, etc. directly -- this project is a flat
collection of scripts, not an installable package.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


TEST_TIME_ANCHOR = {"chain": "bitcoin", "height": 900000, "block_hash": "0" * 64, "source": "blockstream.info"}


@pytest.fixture(autouse=True)
def _offline_time_anchor(monkeypatch):
    """Tests never contact public Bitcoin explorers for time anchors."""
    import research_publish
    monkeypatch.setattr(research_publish, "current_time_anchor", lambda: dict(TEST_TIME_ANCHOR))


@pytest.fixture(autouse=True)
def _no_real_embedding_model(monkeypatch):
    """RabbitSoftware.inc sessions in tests match by words (TF-IDF), never through a real local model."""
    import rabbitsoft.assistant
    monkeypatch.setattr(rabbitsoft.assistant, "default_embedder", lambda: None)
    for name in ("RABBIT_MODEL_URL", "RABBIT_MODEL_KEY", "RABBIT_MODEL_NAME"):   # never this PC's model server
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolate_real_backups(tmp_path_factory, monkeypatch):
    """Tests never see the user's real ~/network-os-backups or backup passphrase."""
    import backup
    monkeypatch.setattr(backup, "DEFAULT_DEST", tmp_path_factory.mktemp("no-real-backups") / "none")
    monkeypatch.setattr(backup, "DPAPI_FILE", tmp_path_factory.mktemp("no-real-key") / "none.dpapi")
    monkeypatch.delenv(backup.PASSPHRASE_ENV, raising=False)
