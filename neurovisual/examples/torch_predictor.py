"""An example external model: a GRU over the feature sequence, in PyTorch (pip install torch).

    python -m neurovisual --predictor neurovisual.examples.torch_predictor:GRUPredictor

It implements the Predictor interface (interfaces.py): predict() runs the GRU over the last
SEQUENCE_LENGTH feature vectors (zero-padded at the start of a session) and hands the output to
model.compose(), so memory/imagination mixing and confidence work as for the built-in model.
trained() does the same reward-weighted objective with Adam, on a copy. Replace the network with
your own; keep the four members.
"""
from __future__ import annotations

import copy
import hashlib

import numpy as np
import torch
from torch import nn

from neurovisual.model import LATENT_SIZE, compose
from neurovisual.system import SEQUENCE_LENGTH


class _Net(nn.Module):
    def __init__(self, feature_dim: int, hidden: int):
        super().__init__()
        self.gru = nn.GRU(feature_dim, hidden, batch_first=True)
        self.head = nn.Linear(hidden, LATENT_SIZE)

    def forward(self, sequences: torch.Tensor) -> torch.Tensor:          # (batch, time, features)
        _, last = self.gru(sequences)
        return torch.tanh(self.head(last[-1]))


class GRUPredictor:
    def __init__(self, feature_dim: int, hidden: int = 32, seed: int = 0):
        torch.manual_seed(seed)
        self.net = _Net(feature_dim, hidden).double()
        self.feature_dim, self.version = feature_dim, (1, 0, 0)
        self.rng = np.random.default_rng(seed)

    @property
    def version_text(self) -> str:
        return ".".join(map(str, self.version))

    def _window(self, sequence: list[np.ndarray]) -> np.ndarray:
        window = np.zeros((SEQUENCE_LENGTH, self.feature_dim))
        recent = np.asarray(sequence[-SEQUENCE_LENGTH:], dtype=float)
        window[SEQUENCE_LENGTH - len(recent):] = recent
        return window

    def predict(self, sequence, mode, anchor, quality, timestamp, event_id=None):
        window = self._window(sequence)
        with torch.no_grad():
            neural = self.net(torch.from_numpy(window)[None]).numpy()[0]
        return compose(neural, window, mode, anchor, quality, timestamp, event_id, self.version_text, self.rng)

    def trained(self, records: list[dict], epochs: int = 25, learning_rate: float = 0.01):
        model = copy.deepcopy(self)
        windows = torch.from_numpy(np.stack([r["context"] for r in records]))
        shown = torch.from_numpy(np.stack([r["neural"] for r in records]))
        ratings = torch.tensor([r["rating"] for r in records], dtype=torch.float64)
        objective = lambda net: (ratings * (net(windows) * shown).sum(1) / LATENT_SIZE).mean()
        with torch.no_grad():
            before = float(objective(model.net))
        optimizer = torch.optim.Adam(model.net.parameters(), lr=learning_rate)
        for _ in range(epochs):
            optimizer.zero_grad()
            (-objective(model.net)).backward()
            optimizer.step()
        with torch.no_grad():
            after = float(objective(model.net))
        major, minor, patch = model.version
        model.version = (major, minor + 1, patch)
        return model, {"records": len(records), "epochs": epochs, "learning_rate": learning_rate,
                       "objective_before": round(before, 6), "objective_after": round(after, 6),
                       "old_version": self.version_text, "new_version": model.version_text}

    def fingerprint(self) -> str:
        digest = hashlib.sha256(self.version_text.encode())
        for name, tensor in sorted(self.net.state_dict().items()):
            digest.update(name.encode())
            digest.update(tensor.detach().cpu().numpy().astype("<f8").tobytes())
        return digest.hexdigest()
