# Neurovisual SDK

`neurovisual/` turns live brain signals into a visual latent state, in **memory** or **imagination**
mode, and hands it to an image or video generator, a game engine, or your own code. Every part is a slot
you can fill with your own or an existing implementation:

```
 sensor ──> band power ──> personal baseline ──> sequence ──> PREDICTOR ──> mode mix + confidence
 (BrainFlow / LSL / sim)                                       (any model)        │
                                                                                  ├──> GENERATOR (ComfyUI, WebUI, diffusers, HTTP, yours)
                                                                                  ├──> UDP stream (Unity, Unreal, Godot, TouchDesigner)
                                                                                  └──> DATASET (encrypted) ──> export / train any model
 ratings ──> learning burst (background) ──> model v1.x ──> provenance ledger (fingerprints only)
```

> **Status:** an engineering prototype. EEG can't reconstruct memories or images today. The system
> produces latent states from signal features and learns only from the ratings it's given. The
> datasets it records are what future models need in order to be trained and judged.

## Quick start

```powershell
python -m neurovisual run                                   # simulated sensors, development profile
python -m neurovisual run --profile research --seconds 30   # record a session (encrypted)
python -m neurovisual run --sensor brainflow --board-id -1  # BrainFlow's synthetic board: no hardware
python -m neurovisual sessions                              # what's been recorded
python -m neurovisual export --format npz --out train.npz   # training arrays (plaintext)
python -m neurovisual train --predictor neurovisual.examples.torch_predictor:GRUPredictor
```

## Profiles: research, gaming, AI development

| Profile | Rate | Records | Raw EEG | UDP stream | Generation every | Learning every |
|---|---|---|---|---|---|---|
| `research` | 10 Hz | yes | yes | no | 5 s | 60 s |
| `gaming` | 30 Hz | no | no | yes | 1 s | 30 s |
| `development` | 10 Hz | yes | no | yes | 2 s | 30 s |

Override any field: `--record` / `--no-record`, `--include-raw`, or `profiles.profile("gaming", hz=60)` in code.

## 1. Sensors: live EEG

| Adapter | SDK | Devices |
|---|---|---|
| `sensors.BrainFlowEEG(board_id, serial_port=..., mac_address=...)` | [BrainFlow](https://brainflow.readthedocs.io) (`pip install brainflow`) | OpenBCI Cyton/Ganglion, Muse, Neurosity, BrainBit, g.tec Unicorn and others; board `-1` is the synthetic board |
| `sensors.LSLEEG(stream_type="EEG")` | [Lab Streaming Layer](https://labstreaminglayer.org) (`pip install pylsl`) | any amplifier or app that publishes an LSL EEG stream (OpenViBE, NeuroPype, BCI2000, vendor apps) |
| `signals.SimulatedEEG` | none | generated band oscillations for development |

List BrainFlow's board ids with `python -c "from brainflow.board_shim import BoardIds; print([(b.name, b.value) for b in BoardIds])"`.

A sensor is any object with `read() -> EEGWindow(timestamp, data[channels, samples], sample_rate)` and an
optional `close()`. Physiology sensors return `PhysiologySample(timestamp, {name: 0..1})`.

## 2. Predictor: plug in any model

```python
class MyPredictor:
    version_text = "1.0.0"
    def predict(self, sequence, mode, anchor, quality, timestamp, event_id=None):
        neural = ...                                   # your model: 64 values in [-1, 1]
        return compose(neural, context, mode, anchor, quality, timestamp, event_id, self.version_text, rng)
    def fingerprint(self): ...                         # SHA-256 of your weights + version
    def trained(self, records): ...                    # optional: (new model, metrics) for learning bursts
```

- **`sequence`** is the last up to 32 feature vectors, z-scored against the person's baseline: δ θ α β γ log band power, then the physiology values (weighted 0.25).
- **`model.compose()`** mixes your output with the stored memory and generated detail, and computes confidence. Every model's evidence is therefore accounted for the same way:

  | Mode | With a stored memory | Without one |
  |---|---|---|
  | memory | evidence 0.70 / inference 0.25 / generative 0.05 | 0 / 0.75 / 0.25 |
  | imagination | 0.25 / 0.35 / 0.40 | 0 / 0.50 / 0.50 |

- **`trained(records)`** gets dicts of `context`, `neural` (what was shown) and `rating` (−1…1). It must return a new model and leave `self` serving. Without `trained()`, learning bursts are skipped and reported.
- **Loading:** `--predictor package.module:Class`, which is called with `feature_dim=`.

`neurovisual/examples/torch_predictor.py` is a complete PyTorch example: a GRU over the sequence, trained with Adam on the same reward-weighted objective.

## 3. Generators: existing image and video models

`conditioning.condition(state, description)` turns a state into a `GenerationRequest` that any generator understands:

| Field | Derived from |
|---|---|
| `prompt` | the memory's description (memory mode), "an imagined variation of: …" (imagination), or "an abstract scene"; plus a shot from the depth slice, lighting from the lighting slice, motion from the motion slice |
| `negative_prompt` | a fixed quality list |
| `seed` | the latent itself, so the same state gives the same image |
| `guidance` | 4 + 6 × evidence + 2 × inference (closer to the prompt when grounded) |
| `strength` | 0.2 + 0.7 × generative (how much image-to-image or video may invent) |
| `frames`, `fps`, `motion_strength` | for video models |
| `latent` | the 64 values, for generators that take a latent directly |

| Connector | Use |
|---|---|
| `ComfyUIGenerator(workflow, url)` | Export your ComfyUI workflow in **API format** (Workflow → Export (API)). Put `{{prompt}}`, `{{negative_prompt}}`, `{{seed}}`, `{{guidance}}`, `{{strength}}`, `{{width}}`, `{{height}}`, `{{steps}}`, `{{frames}}`, `{{fps}}`, `{{motion_strength}}` where values go. A whole-value placeholder keeps its number type. Works with any ComfyUI model, including SDXL, Flux, AnimateDiff and Stable Video Diffusion. |
| `Automatic1111Generator(url)` | Stable Diffusion WebUI started with `--api`; images are saved with their SHA-256. |
| `DiffusersGenerator(model)` | Hugging Face `diffusers` in this process (`pip install diffusers transformers accelerate`), on CUDA when available. |
| `HTTPGenerator(url, api_key_env=...)` | Any JSON-over-HTTP service; the request is the body. |
| your class | Anything with `render(request) -> dict`. |

**Live use:** wrap the generator in `AsyncRenderer(generator, min_interval)`. It renders on its own thread, always the newest request (older ones are dropped, not queued), and counts `rendered`, `dropped`, `errors` and `last_error`. The real-time loop never waits for it.

**Privacy:** in memory mode the prompt contains the memory's description. A generator on another machine therefore requires `https://` and a yes, asked once per destination, saying exactly what is sent. API keys come from an environment variable you name and are never logged.

## 4. Game engines and live apps: the UDP stream

Each step sends one JSON datagram to `127.0.0.1:9555` (`--stream-port`):

```json
{"t": 12.3, "mode": "memory", "event_id": "event_001", "confidence": 0.86, "weights": [0.7, 0.25, 0.05],
 "camera": [8], "motion": [8], "depth": [8], "lighting": [8], "continuity": [8], "scene": [64], "model_version": "1.1.0"}
```

**Godot 4:**
```gdscript
var udp := PacketPeerUDP.new()
func _ready(): udp.bind(9555, "127.0.0.1")
func _process(_delta):
    while udp.get_available_packet_count() > 0:
        var state = JSON.parse_string(udp.get_packet().get_string_from_utf8())
        $WorldEnvironment.environment.background_energy_multiplier = 1.0 + state.lighting[0]
```

**Unity (C#):**
```csharp
[Serializable] public class NeuroState { public string mode; public float confidence; public float[] lighting, motion, scene; }
var client = new UdpClient(new IPEndPoint(IPAddress.Loopback, 9555));
var remote = new IPEndPoint(IPAddress.Any, 0);
var state = JsonUtility.FromJson<NeuroState>(Encoding.UTF8.GetString(client.Receive(ref remote)));   // on a worker thread
```

**Python:**
```python
import json, socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", 9555))
state = json.loads(s.recv(65535))
```

The stream stays on this machine unless you name another host and pass `allow_remote=True`.

## 5. Datasets: build them, then train any model

Recording (`--profile research` or `--record`) saves every step, rating, stored memory and generation to an encrypted session file in `autonomous/neurovisual/datasets/`. The format is specified in [DATASET.md](DATASET.md).

```python
from neurovisual.datasets import read_session, train_from_sessions, export_npz
from neurovisual.provenance import load_or_create_key
key = load_or_create_key(Path("autonomous/neurovisual/dataset.key"))
model, metrics = train_from_sessions(my_predictor, sessions, key)   # any predictor with trained()
export_npz(sessions, key, Path("train.npz"))                         # for PyTorch, JAX, scikit-learn...
```

**PyTorch, from the export:**
```python
d = np.load("train.npz")
x = torch.tensor(d["context"])[d["rated_rows"]]      # model inputs at rated moments
shown = torch.tensor(d["neural"])[d["rated_rows"]]   # what was shown
r = torch.tensor(d["ratings"])                       # how it was rated
```

**Hugging Face datasets:** `load_dataset("json", data_files="train.jsonl")` after `export --format jsonl`.

## 6. Provenance

`autonomous/neurovisual/provenance.jsonl` is a local hash chain. It records:
- each learning burst: the model fingerprint, a config hash, metrics, and a keyed digest of the ratings;
- each recorded dataset: its summary and SHA-256, as a keyed digest.

`ProvenanceLedger.verify()` detects any edit. Nothing from it is published to the shared research chain.
