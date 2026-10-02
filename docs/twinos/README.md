# TwinOS: the universal agent network

TwinOS lets a personal digital twin work as one agent among many: other twins, coding and development
agents, terminal and automation agents, MicroPython edge devices and GPU workers. Every agent states
what it can do and speaks the same message format, **U-A2A 1.0**. Each agent decides for itself what it
will run. The code is in [`twinos/`](../../twinos/), and the message contract is
[`rabbitsoftware-agent-message-v1`](../../schemas/rabbitsoftware-agent-message-v1.schema.json)
([API page](../api/agent-message.md)).

```
other agent ──U-A2A──▶ this agent: verify signature, freshness, nonce ─▶ pinned sender? ─▶ task type offered?
                                                                                │
                              policy allows its capability? ──yes──▶ run ──▶ TASK_RESULT
                                         │no
                                         ▼
                        queue ─▶ owner: python -m twinos approve|deny ─▶ run (on approve) ─▶ result kept for the sender
```

```
EEG (BrainFlow / LSL / simulated) ─┐
RF, audio drivers (plugins) ───────┼─▶ observations ─▶ personal baseline ─▶ lasting change? ─▶ proposed update_context ─▶ owner
                                   ┘                   (z-scores, per source)                     (never an action on its own)
```

## Using it

```powershell
python -m twinos status                                   # id, key, peers, waiting tasks, ledger check
python -m twinos serve                                    # listen on 127.0.0.1:8790

# A second agent on this PC, in its own folder:
python -m twinos --home autonomous/twinos-coder --name Coder --type coding_agent discover 127.0.0.1 8790
#   prints the agent's id and key, and the exact trust command to pin it
python -m twinos --home autonomous/twinos-coder trust agent-... <key>   # the coder trusts the twin's replies
python -m twinos trust agent-... <coder key>                            # the twin accepts the coder's tasks
python -m twinos --home autonomous/twinos-coder capabilities 127.0.0.1 8790 agent-...
python -m twinos --home autonomous/twinos-coder send 127.0.0.1 8790 agent-... status "how are you"

python -m twinos tasks                                    # tasks other agents sent here
python -m twinos approve task-...                         # runs it; written to the activity log
python -m twinos ledger                                   # the local ledger and whether it verifies
```

## Sensing, handlers and learning

```powershell
python -m twinos sense                                    # simulated EEG, 30 s at 10 Hz
python -m twinos sense --eeg brainflow --board-id -1      # BrainFlow's synthetic board (pip install brainflow)
python -m twinos sense --eeg lsl --rf mypkg.radar:Driver  # an LSL EEG stream plus your RF driver
python -m twinos context                                  # what the twin has recorded about itself
python -m twinos learn --device auto                      # train on recorded neurovisual sessions
python -m twinos serve --micropython-port COM3            # offer micropython_command tasks (pip install pyserial)
```

| Source | File | What it gives |
|---|---|---|
| EEG | `twinos/sensors.py` `EEGSource` | Log band powers, delta to gamma, averaged over channels, from `neurovisual`'s BrainFlow, LSL or simulated sensors. Quality is the share of channels carrying signal. |
| RF, audio, anything else | `PluginSource("rf", "package.module:Driver")` | Whatever the driver's `read()` returns as `{feature: number}`. RF measures physical things (range, Doppler, motion, breathing rate); it doesn't read DNA or thoughts. |
| Not connected | `Unavailable` | `available: false` and the reason. Nothing ever reports "connected" without a device. |

**State** (`twinos/state.py`): each source's features are compared with that person's own running
baseline (Welford mean and variance from `neurovisual/signals.py`). A change is reported when a source
stays more than 3 SD away for 3 readings in a row, after 20 readings of warm-up. A single spike isn't a
change. Deviating readings don't move the baseline until the change is confirmed; after that, the new
level becomes the baseline. Confidence is the mean quality of the sources that are there, times how
established the baselines are; with nothing connected it is 0. A change becomes a **proposed**
`update_context` task, which waits for the owner unless `policy.json` allows `write_context`. The ledger
gets a keyed digest of the state, never the feature values.

| Task type | Capability | Handler (`twinos/handlers.py`) |
|---|---|---|
| `status` | `read_context` (automatic) | id, type, waiting tasks, offered task types |
| `update_context` | `write_context` | appends `{category, summary}` (≤500 characters) to `autonomous/twinos/context.jsonl`. Anything `research_provenance.personal_information` flags is refused; it belongs in the encrypted vault (`dna_shell.py data-vault-store`). |
| `run_tests` | `run_tests` | `python -m pytest` on up to 20 named files under `tests/` (no options, no `..`), with a time limit of up to 15 minutes. Returns pass/fail and the last 20 lines. |
| `gpu_training` | `gpu_compute` (never automatic) | `neurovisual`'s training pipeline on `autonomous/neurovisual/datasets/*.nvds`, on CUDA when available. The dataset, training runs (with compute) and model version go to the neurovisual provenance ledger. With no sessions it fails and says so. |
| `micropython_command` | `micropython` (never automatic) | only when a board is attached: sends `{"command": ..., ...}` as one JSON line and returns the board's JSON reply |

The board runs a loop like this `main.py` (MicroPython):

```python
import sys, json, machine
while True:
    line = sys.stdin.readline()
    try:
        cmd = json.loads(line)
        if cmd.get("command") == "status":
            reply = {"ok": True, "freq_hz": machine.freq()}
        else:
            reply = {"ok": False, "error": "unknown command"}
    except ValueError:
        reply = {"ok": False, "error": "not JSON"}
    sys.stdout.write(json.dumps(reply) + "\n")
```

## How it works

| Part | File | What it does |
|---|---|---|
| Identity | `twinos/identity.py` | A persistent Ed25519 key in `autonomous/twinos/identity.pem` (PKCS#8, from `crypto_layer.py`). The agent id is `agent-` plus the first 24 hex digits of the key's SHA-256, so nobody can claim an id without its key. |
| Messages | `twinos/protocol.py` | Each message is signed with Ed25519 over its canonical JSON. A receiver checks the schema, that the id matches the key, the signature, a ±120 s clock window and a nonce not seen in that window. On the wire: a 4-byte length, then UTF-8 JSON, up to 1 MiB, with a 10 s read timeout. |
| Trust | `twinos/trust.py` | Peer keys pinned by the owner in `peers.json`. Anyone may ask who an agent is (`IDENTITY_REQUEST`); everything else needs a pinned sender signing with the pinned key. Nothing is ever pinned automatically. |
| Policy | `twinos/tasks.py` | Each task type needs one capability. `policy.json` lists those that run without asking (default: `read_context` only). Running code, terminal commands, writing files, network operations, MicroPython and GPU jobs always wait for approval, whatever the file says. |
| Tasks | `twinos/tasks.py` | The receiver builds each task from only its type, description (up to 2,000 characters) and parameters (up to 16 KiB), so a sender can't mark its own task approved. At most 100 tasks per peer may wait; one message makes at most one task. |
| Node | `twinos/node.py` | Answers messages, runs or queues tasks, and serves TCP on `127.0.0.1:8790` (the node network uses 8765). It offers only task types it has a handler for (see the table above). |
| Ledger | `autonomous/twinos/ledger.jsonl` | The hash-chained ledger from `neurovisual/provenance.py`, with keyed digests (HMAC-SHA-256) of messages from pinned peers and of every task decision and result. It never holds their content, and it isn't published. |

The server and the owner's commands are separate processes, so `tasks.json`, `peers.json` and the ledger
are re-read under a lock file for every change. A peer pinned while the server runs is trusted at once.
Changes to `policy.json` take effect when the server restarts.

## Limits

- **Signed, not encrypted.** Messages are authenticated and replay-protected, but anyone on the path can
  read them. Keep the default `127.0.0.1`, or use `--allow-remote` only on a network you trust, until
  encrypted sessions are added (the node network's X25519 + AES-GCM handshake is the model).
- **Replays across a restart.** Nonces are kept in memory for 120 s. A task request replayed right
  after a restart is still refused, because its message id already made a task; other request types are
  read-only.
- **No rate limit.** Unsigned and untrusted messages are answered but not stored. A pinned peer can
  queue at most 100 tasks. There's no per-connection rate limit yet (32 connections at a time).
- **Trust is manual.** Check the key that `discover` prints through another channel before pinning,
  because whoever answers on that address could be an impostor.
- **Clocks.** Both agents' clocks must be within 120 s of each other.
- **Signals are not thoughts.** EEG band power and RF measurements describe signals and the body. The
  state is a deviation from a personal baseline, which the owner can choose to act on. It doesn't decode
  intentions or memories ([EEG to image reconstruction](../research/eeg-to-image-reconstruction.md) covers
  what EEG can and can't decode).
- **No mood or emotion.** The state is a deviation, never a label such as "stressed" or "calm". Inferring
  affect from EEG is emotion recognition under the EU AI Act (transparency duties now, high-risk duties
  from December 2027), so don't add it. A state signal is also all a forehead headset like the Muse can
  give; decoding visual content needs occipital channels (see the report).
- **EEG stays on this PC.** No handler returns features or the state to another agent. The context
  entry a change creates says only which source deviated and by how much, and it waits for your approval.
  The ledger's keyed digests are still personal data under the EDPB's 2026 guidance: deleting
  `autonomous/twinos/ledger.key` makes them unlinkable (crypto-shredding).
- **Not tested with hardware here.** BrainFlow's synthetic board and the simulated EEG exercise the live
  path. The MicroPython link is tested against a fake serial port, not a real board.
- **Code generation and terminal commands** have no handler, so they're rejected rather than faked.
