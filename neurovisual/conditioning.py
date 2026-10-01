"""From a visual latent state to a request any existing image or video generator understands.

Off-the-shelf generators (Stable Diffusion via ComfyUI, AUTOMATIC1111 or diffusers, and video models)
are conditioned on text and a few numbers, not on this system's latent. This maps one onto the other:

  prompt      the stored memory's description (memory mode) or a variation of it (imagination), or an
              abstract scene without one, plus descriptors read from the latent's named slices:
              lighting (mean of the lighting slice), shot (depth), motion (norm of the motion slice)
  seed        derived from the latent, so the same state always gives the same image
  guidance    how closely the generator follows the prompt: higher when the state rests on evidence
  strength    how much the generator may invent (image-to-image / video): the generative weight
  video       frame count and motion strength from the motion slice

A custom generator can ignore the prompt and use `latent` directly.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

import numpy as np

NEGATIVE = "text, watermark, logo, distorted faces, extra limbs, low quality"


@dataclass
class GenerationRequest:
    prompt: str
    negative_prompt: str
    seed: int
    guidance: float
    strength: float
    width: int = 512
    height: int = 512
    steps: int = 20
    frames: int = 16
    fps: int = 8
    motion_strength: float = 0.5
    mode: str = "memory"
    confidence: float = 0.0
    model_version: str = ""
    latent: list[float] = field(default_factory=list, repr=False)
    contains_memory_text: bool = False      # the prompt includes a stored memory's description

    def to_dict(self) -> dict:
        return asdict(self)


def _pick(value: float, words: tuple[str, str, str]) -> str:
    return words[0] if value < -0.25 else words[2] if value > 0.25 else words[1]


def condition(state, description: str | None = None, width: int = 512, height: int = 512) -> GenerationRequest:
    lighting = _pick(float(np.mean(state.lighting)), ("dim low-key lighting", "soft natural light", "bright high-key lighting"))
    shot = _pick(float(np.mean(state.depth)), ("close-up", "medium shot", "wide establishing shot"))
    motion_level = float(np.linalg.norm(state.motion) / np.sqrt(len(state.motion)))
    motion = "still" if motion_level < 0.3 else "gentle movement" if motion_level < 0.6 else "fast motion"
    if description and state.mode == "memory":
        subject = description
    elif description:
        subject = f"an imagined variation of: {description}"
    else:
        subject = "an abstract scene"
    seed = int.from_bytes(hashlib.sha256(np.round(state.scene, 3).tobytes()).digest()[:4], "big") & 0x7FFFFFFF
    return GenerationRequest(
        prompt=f"{subject}, {shot}, {lighting}, {motion}, photographic, coherent detail",
        negative_prompt=NEGATIVE, seed=seed,
        guidance=round(4.0 + 6.0 * state.evidence_weight + 2.0 * state.inference_weight, 2),
        strength=round(0.2 + 0.7 * state.generative_weight, 3), width=width, height=height,
        motion_strength=round(min(1.0, motion_level), 3), mode=state.mode, confidence=round(state.confidence, 3),
        model_version=state.model_version, latent=[round(float(x), 4) for x in state.scene],
        contains_memory_text=bool(description))
