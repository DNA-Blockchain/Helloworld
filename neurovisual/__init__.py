"""Personal neural -> visual memory and imagination system (PNV-MIM): a research prototype.

    historical data -> personal baseline
    live EEG + slow physiology -> signal fusion -> temporal predictor -> memory | imagination mode
      -> visual latent state -> evidence/confidence weighting -> image/video generator
      -> human feedback -> learning burst (background) -> model v1.x -> provenance ledger

    python -m neurovisual --seconds 3      # a simulated session, with a learning burst

Status: simulation. The sensors are simulated and no image generator is connected. EEG cannot
reconstruct memories or images today; this prototype exercises the architecture (timing, learning
from ratings, evidence accounting, provenance) so real sensors and models can be plugged in.

Data handling: raw signals, notes and memories stay in memory, in bounded buffers. The provenance
ledger on disk holds fingerprints and metrics only (keyed digests for personal data), and nothing is
published to the shared research chain.

The blockchain is not the compute: training and inference run on the CPU/GPU, and the ledger records
which data, configuration and model produced what.
"""
from .model import VisualLatentState, VisualMode
from .provenance import ProvenanceLedger
from .system import NeurovisualSystem

__all__ = ["NeurovisualSystem", "ProvenanceLedger", "VisualLatentState", "VisualMode"]
