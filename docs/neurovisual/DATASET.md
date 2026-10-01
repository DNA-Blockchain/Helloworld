# Neurovisual session dataset v1

Schema id: `rabbitsoft-neurovisual-dataset.v1`. Writer: `neurovisual/datasets.py` (`SessionRecorder`).

## File layout (`<session_id>.nvds`)

| Bytes | Content |
|---|---|
| `NVDS1\n` | magic |
| 4 (big-endian) | header length *H* |
| *H* | header, JSON, **plaintext** |
| repeated: 4 + *n* | frame: length, then AES-256-GCM ciphertext (nonce included) of gzip-compressed JSON Lines |

- **Authentication:** each frame is authenticated with SHA-256(header) ‖ frame number. Editing the header, editing a frame or reordering frames all make decryption fail.
- **Frames:** a frame is written every `frame_steps` steps (default 300, 30 s at 10 Hz) and on close.
- **Key:** `autonomous/neurovisual/dataset.key`, 32 random bytes created on first use. **Back it up:** without it the sessions can't be read.

## Header (plaintext, nothing personal)

`schema`, `session_id`, `created_at` (Unix time), `profile`, `features` (names, in order), `include_raw`, `model_fingerprint`.

## Rows (encrypted)

| `type` | Fields |
|---|---|
| `step` | `index`, `t`, `mode`, `event_id`, `model_version`, `features_raw` (δ θ α β γ log power, then physiology), `features` (baseline z-scores, physiology × 0.25), `context`, `neural` (64), `scene` (64), `weights` [evidence, inference, generative], `confidence`, `quality`, `request` {`seed`, `prompt`, `guidance`, `strength`}, and `raw` {`sample_rate`, `data[channels][samples]`} when `include_raw` |
| `rating` | `step` (the step it rates), `rating` (−1…1), `notes`, `t` |
| `anchor` | `event_id`, `description`, `context` (a stored memory) |
| `generation` | `status`, and `path` + `sha256`, `prompt_id` or `error` |

## Size

About 2 KB per step without raw EEG. Raw 1-second windows add about 1 KB per channel per step after compression. Measured on BrainFlow's 16-channel synthetic board at 250 Hz: 98 steps = 1.57 MB, about 0.6 GB per hour at 10 Hz. Overlapping windows are stored whole, which keeps every row self-contained.

## Exports (plaintext)

| Command | Output |
|---|---|
| `python -m neurovisual export --format npz --out f.npz` | arrays `features`, `context`, `neural`, `scene`, `weights`, `confidence`, `quality`, `mode` (0 memory, 1 imagination), `session`, `rated_rows`, `ratings` |
| `python -m neurovisual export --format jsonl --out f.jsonl` | every row, with `session_id` |

Exports are decrypted copies for a training job. Keep them where training runs, and delete them afterwards.

## Privacy

- **What's personal:** EEG, physiology, ratings, notes and memory descriptions are personal data. They stay on this PC, encrypted at rest.
- **Ledger:** the provenance ledger records each dataset only as a keyed digest with counts.
- **Chain:** nothing from a dataset goes to the shared research chain.
- **Sharing:** sharing a dataset (for example to a private Hugging Face dataset for training) is a separate, explicit step that doesn't exist yet. It will ask first and say exactly what leaves.
