"""The Hugging Face cards are versioned in deploy/huggingface/ and published by `hf_publish.py cards`."""
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("hf_publish", ROOT / "deploy" / "hf_publish.py")
hf_publish = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hf_publish)


def test_the_cards_describe_the_model_and_keep_the_llama_license():
    model = hf_publish.MODEL_CARD.read_text(encoding="utf-8")
    assert model.startswith("---\nlicense: llama3.2\n") and "Built with Llama" in model
    assert "Findings" in model and "Limitations" in model and "8aa05e28" in model
    assert hf_publish.DATASET_CARD.read_text(encoding="utf-8").startswith("---\nlicense: other\n")


@pytest.mark.parametrize("path", ["deploy/huggingface/model-card.md", "deploy/huggingface/dataset-card.md",
                                  "README.md", "CHANGELOG.md", "ROADMAP.md", "rabbitsoft/__init__.py"])
def test_positioning_is_professional(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    assert not re.search(r"disabilit|word-finding|grammar or|find the right words|short, plain", text, re.I)


def test_cards_are_uploaded_to_both_repos_only_after_a_yes(monkeypatch):
    uploads = []

    class Api:
        def whoami(self):
            return {"name": "owner"}

        def upload_file(self, **kw):
            uploads.append((kw["repo_id"], kw["repo_type"], Path(kw["path_or_fileobj"]).name))

    hub = types.ModuleType("huggingface_hub")
    hub.HfApi = Api
    errors = types.ModuleType("huggingface_hub.errors")
    errors.LocalTokenNotFoundError = type("LocalTokenNotFoundError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.errors", errors)
    assert hf_publish.publish_cards(ask=lambda q: False) == 1 and uploads == []
    assert hf_publish.publish_cards(ask=lambda q: True) == 0
    assert uploads == [("owner/Llama-3.2-3B-RabbitSoftware-GGUF", "model", "model-card.md"),
                       ("owner/rabbitsoftware-training", "dataset", "dataset-card.md")]
