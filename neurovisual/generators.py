"""Connectors to existing image and video generators, and a background renderer for live use.

  PlaceholderGenerator    describes the request; no pixels (the default)
  ComfyUIGenerator        a ComfyUI server (default http://127.0.0.1:8188): queues your exported
                          API-format workflow with {{prompt}}, {{negative_prompt}}, {{seed}}, {{guidance}},
                          {{strength}}, {{width}}, {{height}}, {{steps}}, {{frames}}, {{fps}} filled in.
                          Any ComfyUI model works: SDXL, Flux, AnimateDiff, Stable Video Diffusion...
  Automatic1111Generator  a Stable Diffusion WebUI started with --api (default http://127.0.0.1:7860)
  DiffusersGenerator      Hugging Face diffusers in this process (pip install diffusers transformers
                          accelerate); the model is whatever local path or Hub id you give it
  HTTPGenerator           any JSON-over-HTTP service, local or hosted, with the request as the body

Consent: a generator on another machine receives the prompt, which in memory mode includes the stored
memory's description. Any non-local destination needs a yes first (the `consent` callback), asked once
per destination and saying whether memory text is included. API keys are read from an environment
variable named by you and never logged.

Live use: generation takes seconds, the loop runs every 100 ms. AsyncRenderer renders on its own
thread, always the newest request (older ones are dropped, never queued up), at most every
`min_interval` seconds, and counts its errors where you can see them.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class GeneratorUnavailable(RuntimeError):
    pass


class GeneratorRefused(PermissionError):
    pass


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: float = 300) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def is_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


class _Destination:
    """Shared consent handling for generators that send requests to a URL."""

    def __init__(self, url: str, consent=None):
        if urlparse(url).scheme not in ("http", "https"):
            raise ValueError(f"a generator URL starts with http:// or https://, not {url!r}")
        if not is_local(url) and urlparse(url).scheme != "https":
            raise ValueError("a generator on another machine must use https://")
        self.url, self.consent, self._allowed = url.rstrip("/"), consent, is_local(url)

    def _allow(self, request) -> None:
        if self._allowed:
            return
        host = urlparse(self.url).hostname
        question = (f"Send generation requests to {host}? Each one carries the prompt"
                    + (", which includes the stored memory's description" if request.contains_memory_text else "")
                    + " and the visual latent. (yes/no)")
        if self.consent is None or not self.consent(question):
            raise GeneratorRefused(f"not sending to {host}: no consent")
        self._allowed = True


def _save_image(data: bytes, out_dir: Path, request) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    path = out_dir / f"{request.mode}-{request.seed}-{digest[:12]}.png"
    path.write_bytes(data)
    return {"type": "image", "status": "done", "path": str(path), "sha256": digest}


class PlaceholderGenerator:
    def render(self, request) -> dict:
        return {"type": "image", "status": "no generator connected", "prompt": request.prompt,
                "seed": request.seed, "mode": request.mode, "confidence": request.confidence}


class ComfyUIGenerator(_Destination):
    def __init__(self, workflow: dict | str | Path, url: str = "http://127.0.0.1:8188", consent=None,
                 post=post_json, client_id: str = "rabbitsoftware-neurovisual"):
        super().__init__(url, consent)
        self.template = workflow if isinstance(workflow, dict) else json.loads(Path(workflow).read_text(encoding="utf-8"))
        self.post, self.client_id = post, client_id

    def fill(self, request) -> dict:
        values = request.to_dict()

        def walk(node):
            if isinstance(node, dict):
                return {k: walk(v) for k, v in node.items()}
            if isinstance(node, list):
                return [walk(v) for v in node]
            if isinstance(node, str) and node.startswith("{{") and node.endswith("}}") and node[2:-2] in values:
                return values[node[2:-2]]                       # a whole-value placeholder keeps its type
            if isinstance(node, str):
                for key, value in values.items():
                    node = node.replace("{{" + key + "}}", str(value)) if isinstance(value, (str, int, float)) else node
            return node
        return walk(self.template)

    def render(self, request) -> dict:
        self._allow(request)
        reply = self.post(f"{self.url}/prompt", {"prompt": self.fill(request), "client_id": self.client_id})
        if "prompt_id" not in reply:
            raise GeneratorUnavailable(f"ComfyUI didn't queue the workflow: {reply.get('error') or reply}")
        return {"type": "comfyui", "status": "queued", "prompt_id": reply["prompt_id"],
                "history": f"{self.url}/history/{reply['prompt_id']}"}


class Automatic1111Generator(_Destination):
    def __init__(self, url: str = "http://127.0.0.1:7860", out_dir: str | Path = "neurovisual-output",
                 consent=None, post=post_json):
        super().__init__(url, consent)
        self.out_dir, self.post = Path(out_dir), post

    def render(self, request) -> dict:
        self._allow(request)
        reply = self.post(f"{self.url}/sdapi/v1/txt2img", {
            "prompt": request.prompt, "negative_prompt": request.negative_prompt, "seed": request.seed,
            "steps": request.steps, "cfg_scale": request.guidance, "width": request.width, "height": request.height})
        images = reply.get("images") or []
        if not images:
            raise GeneratorUnavailable(f"the WebUI returned no image: {reply.get('error') or reply.get('detail') or reply}")
        return _save_image(base64.b64decode(images[0]), self.out_dir, request)


class DiffusersGenerator:
    def __init__(self, model: str, out_dir: str | Path = "neurovisual-output", device: str | None = None):
        try:
            import torch
            from diffusers import AutoPipelineForText2Image
        except ImportError as error:
            raise GeneratorUnavailable("diffusers isn't installed: pip install diffusers transformers accelerate") from error
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.pipe = AutoPipelineForText2Image.from_pretrained(model, torch_dtype=dtype).to(self.device)
        self.out_dir = Path(out_dir)

    def render(self, request) -> dict:
        import io

        generator = self.torch.Generator(device=self.device).manual_seed(request.seed)
        image = self.pipe(prompt=request.prompt, negative_prompt=request.negative_prompt,
                          num_inference_steps=request.steps, guidance_scale=request.guidance,
                          width=request.width, height=request.height, generator=generator).images[0]
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return _save_image(buffer.getvalue(), self.out_dir, request)


class HTTPGenerator(_Destination):
    def __init__(self, url: str, api_key_env: str | None = None, consent=None, post=post_json):
        super().__init__(url, consent)
        self.api_key_env, self.post = api_key_env, post

    def render(self, request) -> dict:
        self._allow(request)
        headers = {}
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if not key:
                raise GeneratorUnavailable(f"set the API key in the environment variable {self.api_key_env}")
            headers["Authorization"] = f"Bearer {key}"
        return {"type": "http", "status": "done", "response": self.post(self.url, request.to_dict(), headers)}


class AsyncRenderer:
    def __init__(self, generator, min_interval: float = 1.0, keep: int = 50):
        self.generator, self.min_interval, self.keep = generator, min_interval, keep
        self._latest = None
        self._wake = threading.Condition()
        self._stop = False
        self.results: list[dict] = []
        self.rendered = self.dropped = self.errors = 0
        self.last_error = ""
        self._thread = threading.Thread(target=self._loop, name="neurovisual-renderer", daemon=True)
        self._thread.start()

    def submit(self, request) -> dict:
        with self._wake:
            if self._latest is not None:
                self.dropped += 1                   # superseded before it was rendered
            self._latest = request
            self._wake.notify()
        return {"type": "image", "status": "submitted", "seed": request.seed}

    def _loop(self) -> None:
        last = 0.0
        while True:
            with self._wake:
                while self._latest is None and not self._stop:
                    self._wake.wait()
                if self._stop:
                    return
                wait = self.min_interval - (time.monotonic() - last)
                if wait > 0:
                    self._wake.wait(wait)           # newer requests may replace this one meanwhile
                    if self._stop:
                        return
                request, self._latest = self._latest, None
            last = time.monotonic()
            try:
                result = self.generator.render(request)
                self.rendered += 1
            except Exception as error:              # reported in .errors / .last_error, and in results
                self.errors += 1
                self.last_error = f"{type(error).__name__}: {error}"
                result = {"status": "error", "error": self.last_error}
            self.results = (self.results + [result])[-self.keep:]

    def close(self, timeout: float = 5.0) -> None:
        with self._wake:
            self._stop = True
            self._wake.notify()
        self._thread.join(timeout)

    def stats(self) -> dict:
        return {"rendered": self.rendered, "dropped": self.dropped, "errors": self.errors, "last_error": self.last_error}
